# -*- coding: utf-8 -*-
from config import *
import sys, re, io, os, json, math, time, warnings
from datetime import datetime
from difflib import SequenceMatcher
import requests
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")

def _make_soup(html_text: str):
    """BeautifulSoup parser — lxml varsa kullan, yoksa html.parser'a düş."""
    try:
        return BeautifulSoup(html_text, "lxml")
    except Exception:
        return BeautifulSoup(html_text, "html.parser")


def _clean_team(name: str) -> str:
    """Takım adından gereksiz kısaltmaları ve stray sayıları temizle."""
    # Yaygın kısaltmalar
    name = re.sub(r'A\.Ş\.?\.?', '', name, flags=re.I)
    name = re.sub(r'F\.\s*K\.?', '', name, flags=re.I)
    name = re.sub(r'\bF\.\s*C\.?', '', name, flags=re.I)
    name = re.sub(r'\bFK\b', '', name)
    name = re.sub(r'\bAIŞ\.?\b', '', name, flags=re.I)
    name = re.sub(r'\bAŞ\.?\b', '', name, flags=re.I)
    name = re.sub(r'\bA\.S\.?\b', '', name, flags=re.I)
    name = re.sub(r'\bS\.K\.?\b', '', name, flags=re.I)
    name = re.sub(r'\bR\.A\.?\b', '', name, flags=re.I)
    # Sondaki sayı ve nokta: "A. 5." "A. 6." "A..."
    name = re.sub(r'\s+\d{1,2}\.\s*$', '', name)  # Stray kısa rakam+nokta: 'A. 6.' → '' (COMO 1907 gibi yıl içeren isimler korunur)
    name = re.sub(r'\.{2,}\s*$', '', name)
    name = re.sub(r'\bA\.\s*$', '', name)
    name = re.sub(r'[\.\s]+$', '', name)
    # Baştaki / işareti
    name = re.sub(r'^[/\s]+', '', name)
    name = re.sub(r'\s{2,}', ' ', name)
    return name.strip()


def _parse_sportoto_json(data) -> list:
    """Sportoto API JSON yanıtından maç listesi çıkar."""
    items = (
        data.get("matches") or data.get("Matches") or
        data.get("data", {}).get("matches") or
        data.get("result") or
        (data if isinstance(data, list) else None)
    )
    if not items:
        return []
    out = []
    for i, m in enumerate(items[:15], 1):
        home = (m.get("homeTeam") or m.get("HomeTeam") or
                m.get("home") or m.get("ev") or f"Ev{i}")
        away = (m.get("awayTeam") or m.get("AwayTeam") or
                m.get("away") or m.get("dep") or f"Dep{i}")
        out.append({
            "no": i,
            "home": _clean_team(str(home)),
            "away": _clean_team(str(away)),
            "date": m.get("date", ""),
            "time": m.get("time", ""),
            "odds": {"1": None, "X": None, "2": None},
        })
    return out


def _source_sportoto_api() -> list:
    """Kaynak 1: webapi.sportoto.gov.tr — bilinen endpoint'leri dene."""
    for url in SPORTOTO_API_CANDIDATES:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code == 200 and "json" in r.headers.get("Content-Type", ""):
                result = _parse_sportoto_json(r.json())
                if result:
                    print(f"    ✓ webapi bulundu: {url}")
                    return result
        except (ValueError, TypeError, KeyError, AttributeError, requests.exceptions.RequestException):
            continue
    return []


def _source_sportoto_js() -> list:
    """Kaynak 1b: Angular bundle'ından API URL'si çıkar, çalıştır."""
    try:
        r = requests.get("https://www.sportoto.gov.tr", headers=HEADERS, timeout=10)
        soup = _make_soup(r.text)
        js_files = [
            t["src"] for t in soup.find_all("script", src=True)
            if any(k in t["src"] for k in ("main", "chunk", "runtime"))
        ]
        for path in js_files[:6]:
            url = path if path.startswith("http") else "https://www.sportoto.gov.tr" + path
            try:
                js = requests.get(url, headers=HEADERS, timeout=10).text
                endpoints = re.findall(
                    r'https://webapi\.sportoto\.gov\.tr/[A-Za-z0-9/_.-]+', js
                )
                for ep in dict.fromkeys(endpoints):
                    if ep.endswith((".jpg", ".png", ".svg")):
                        continue
                    try:
                        tr = requests.get(ep, headers=HEADERS, timeout=6)
                        if tr.status_code == 200 and len(tr.text) > 80:
                            result = _parse_sportoto_json(tr.json())
                            if result:
                                print(f"    ✓ JS endpoint: {ep}")
                                return result
                    except (ValueError, TypeError, KeyError, AttributeError, requests.exceptions.RequestException):
                        continue
            except (ValueError, TypeError, KeyError, AttributeError, requests.exceptions.RequestException):
                continue
    except (ValueError, TypeError, KeyError, AttributeError, requests.exceptions.RequestException):
        pass
    return []


def _source_iddaa() -> list:
    """Kaynak 2: iddaa.com HTML scraper."""
    try:
        r = requests.get("https://www.iddaa.com/spor-toto",
                         headers=HEADERS, timeout=12)
        soup = _make_soup(r.text)
        out = []
        for row in soup.select("tr, .match-row, [class*='event']"):
            cells = row.find_all(["td", "th", "span"])
            text  = " ".join(c.get_text(strip=True) for c in cells)
            m = re.search(
                r'([A-Za-zğüşıöçĞÜŞİÖÇ0-9\s\.\-]{3,35})\s*[-–]\s*'
                r'([A-Za-zğüşıöçĞÜŞİÖÇ0-9\s\.\-]{3,35})',
                text
            )
            if m and len(out) < 15:
                home = _clean_team(m.group(1))
                away = _clean_team(m.group(2))
                if (len(home) > 3 and len(away) > 3 and
                        not home[:2].isdigit() and not away[:2].isdigit()):
                    out.append({
                        "no": len(out) + 1,
                        "home": home, "away": away,
                        "date": "", "time": "",
                        "odds": {"1": None, "X": None, "2": None},
                    })
        if len(out) >= 13:
            print(f"    ✓ iddaa.com: {len(out)} maç")
            return out
    except (OSError, IOError, ValueError, TypeError, AttributeError) as e:
        print(f"    iddaa.com: {e}")
    return []


def _source_nesine() -> list:
    """Kaynak 3: nesine.com HTML scraper."""
    try:
        r = requests.get("https://www.nesine.com/sportoto",
                         headers=HEADERS, timeout=12)
        soup = _make_soup(r.text)
        out = []
        pattern = re.compile(
            r'^([A-Za-zğüşıöçĞÜŞİÖÇ\s\.\-]{3,35})'
            r'\s*[-–]\s*'
            r'([A-Za-zğüşıöçĞÜŞİÖÇ\s\.\-]{3,35})$'
        )
        for el in soup.find_all(string=pattern):
            if len(out) >= 15:
                break
            m = pattern.match(el.strip())
            if m:
                home = _clean_team(m.group(1))
                away = _clean_team(m.group(2))
                if len(home) > 3 and len(away) > 3:
                    out.append({
                        "no": len(out) + 1,
                        "home": home, "away": away,
                        "date": "", "time": "",
                        "odds": {"1": None, "X": None, "2": None},
                    })
        if len(out) >= 13:
            print(f"    ✓ nesine.com: {len(out)} maç")
            return out
    except (OSError, IOError, ValueError, TypeError, AttributeError) as e:
        print(f"    nesine.com: {e}")
    return []


def _parse_bulk(text: str) -> list:
    """
    Toplu yapıştırılan metni maç listesine çevir.

    Desteklenen formatlar (hepsi aynı anda karışık olabilir):
      1. Antalyaspor - Konyaspor
      2  Fenerbahçe – Rizespor
      Trabzonspor vs Başakşehir
      Man City - Arsenal  2.20 3.40 3.20
      Chelsea-ManUnited

    Özel durumlar:
      - Numara ayrı satırda: "1.\nALANYASPOR - KAYSERISPOR"
      - Sonda stray sayı: "TRABZONSPOR A. 6." → "TRABZONSPOR"
      - Yanlış numara: "71." → "11."
      - Telefon OCR NFD unicode: Ş→S+cedilla, NFC'ye normalize edilir
      - OCR tire yutması: "4. SKIVE KKISHOEJIF" → failed_lines listesine alınır
    """
    import unicodedata
    out = []

    # ── NFD → NFC normalize (telefon clipboard'ından NFD gelirse Türkçe
    # karakterler U+0327 gibi birleştirici karakterlere dönüşür ve regex'i kırar)
    text = unicodedata.normalize('NFC', text)

    # OCR hata duzeltme
    ocr_fixes = [
        ('$',  'S'), ('\uff04', 'S'),
        ('|',  'I'), ('\u00a6', 'I'),
        ('\u2013', '-'), ('\u2014', '-'), ('\u2212', '-'),
        ('\u00e2\u0080\u0093', '-'),
    ]
    for frm, to in ocr_fixes:
        text = text.replace(frm, to)
    text = re.sub(r'A\.\$\.', 'A.S.', text)
    text = re.sub(r'A\$',     'AS',   text)

    # ── OCR satır yapıştırma düzeltmesi ──────────────────────────────
    text = re.sub(r'([A-ZÇĞİÖŞÜ])\s+A\.\s*Ş\.?\s+([A-ZÇĞİÖŞÜ])', r'\1 - \2', text)
    text = re.sub(r'([A-ZÇĞİÖŞÜ])\s+A\.\s*Ş\.?\s*-\s*', r'\1 - ', text)
    ocr_team_fixes = {
        'KO CAELISPOR':   'KOCAELISPOR',
        'KOCAELI SPOR':   'KOCAELISPOR',
        'BASAKŞEHIR':     'BAŞAKŞEHIR',
        'BASAKSEHIR':     'BAŞAKŞEHIR',
        'GAZIANTEP F K':  'GAZIANTEP FK',
        'GAZIANTEP F. K': 'GAZIANTEP FK',
        'ÇAYKUR RIZESPOR A': 'ÇAYKUR RİZESPOR',
        'RIZESPOR A':     'RİZESPOR',
        'TRABZONSPOR A':  'TRABZONSPOR',
        'KASIMPASA':      'KASIMPAŞA',
        'ACLENS':         'LENS',
        'AC LENS':        'LENS',
        'GENCLERBIRLIGI': 'GENÇLERBİRLİĞİ',
        'GALATASARAYA':   'GALATASARAY',
        'GALATASARAY.Ş':  'GALATASARAY',
        'GALATASARAYA.Ş': 'GALATASARAY',
        'KASIMPAŞA AŞ.-': 'KASIMPAŞA -',
        'KASIMPAŞA AŞ. -': 'KASIMPAŞA -',
        'ANTALYASPOR KO CAELISPOR': 'ANTALYASPOR - KOCAELISPOR',
        '1 ÇAYKUR':      'ÇAYKUR',
        'ÇAYKUR RIZESPOR  - BEŞİKTAŞ': 'ÇAYKUR RİZESPOR - BEŞİKTAŞ',
        'RIZESPOR  -':   'RİZESPOR -',
        'BEŞİKT ':       'BEŞİKTAŞ ',
        'ANTALYASPOR - KOCAELISPOR': 'ANTALYASPOR - KOCAELISPOR',
    }
    for wrong, correct in ocr_team_fixes.items():
        text = text.replace(wrong, correct)

    text = re.sub(r'(\w)\s+A\.\s*[SŞ]\.?\s*-\s*', r'\1 - ', text)
    text = re.sub(r'(\w)\s+A[SŞ]\.?\s*-\s*', r'\1 - ', text)
    text = re.sub(r'(\w)\s+A\.\s*[SŞ]\.?\s+([A-ZÇĞİÖŞÜ])', r'\1 - \2', text)
    text = re.sub(r'\s+A\.\s*\d+\.\s*$', '', text, flags=re.M)
    text = re.sub(r'\s+A\.\s*\d+\.(\s*-)', r'\1', text)
    text = re.sub(r'\s+A\.\s*\d+\.', '', text)
    text = re.sub(r'\s+A\.{2,}\s+', ' - ', text)
    text = re.sub(r'\.{3,}\s+', ' - ', text)
    # BUG FIX: boşluk zorunlu — EKRANAS/NEPTUNAS gibi isimlerin AS ekini yutmayı önler
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{4,})\s+A\.?[SŞ]\.?\s*$', r'\1', text, flags=re.M)
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{4,})\s+A\.?[SŞ]\.?(\s)', r'\1\2', text)
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{4,})\s+A\.\s+[SŞ]([A-ZÇĞİÖŞÜ])', r'\1 - \2', text)
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{6,})\s+([A-ZÇĞİÖŞÜ]{2,4})\s+([A-ZÇĞİÖŞÜ]{4,})',
                  lambda m: m.group(0)
                  if '-' in m.group(0)
                  else f"{m.group(1)} - {m.group(2)}{m.group(3)}"
                  if len(m.group(2)) <= 3
                  else m.group(0),
                  text)

    # ── ÖN İŞLEME: Numara ayrı satırda ise bir sonraki satırla birleştir ──
    raw_lines = text.splitlines()

    # Başlık satırını bul
    _header = ""
    for _l in raw_lines[:6]:
        if any(ay in _l.lower() for ay in ["ocak","şubat","mart","nisan","mayıs","mayis",
                                             "haziran","temmuz","ağustos","agustos",
                                             "eylül","eylul","ekim","kasım","kasim","aralık","aralik"]):
            _header = _l.strip()
            break

    merged = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()
        if re.match(r'^\d{1,2}\.?\s*$', line) and i + 1 < len(raw_lines):
            next_line = raw_lines[i+1].strip()
            if next_line and not re.match(r'^\d{1,2}\.?\s*$', next_line):
                num = int(re.search(r'\d+', line).group())
                if num > 15:
                    num = len(merged) + 1
                merged.append(f"{num}. {next_line}")
                i += 2
                continue
        line = re.sub(r'^\d\s+(?=[A-ZÇĞİÖŞÜ])', '', line)
        merged.append(line)
        i += 1

    processed_text = "\n".join(merged)

    _tc = r'[^\n]'
    line_re = re.compile(
        r'^(?:\d{1,2}[\.\):\s]+)?'
        r'(' + _tc + r'{3,50}?)'
        r'(?:\s{1,6}[-]\s{1,6}|\.{2,3}|\s{1,6}vs\.?\s{1,6})'
        r'(' + _tc + r'{3,60})'
        r'(?:\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+))?'
        r'\s*$',
        re.UNICODE
    )
    nospace_re = re.compile(
        r'^(?:\d{1,2}[\.\):\s]+)?(' + _tc + r'{3,40})-(' + _tc + r'{3,40})$',
        re.UNICODE
    )
    # Numara+içerik var ama ayraç yok: "4. SKIVE KKISHOEJIF" gibi OCR hataları
    numbered_no_sep_re = re.compile(r'^(\d{1,2})[\.\):\s]+(.{4,})$', re.UNICODE)

    skip_words = ['hafta', 'liste', 'toto', 'tahmin', 'bolum', 'sezon', 'program',
                  'ocak', 'subat', 'mart', 'mayis', 'haziran', 'temmuz',
                  'agustos', 'eylul', 'ekim', 'aralik']
    month_standalone = ['nisan', 'kasim']

    # Kaçan numaralı satırları izle
    failed_lines = {}   # {pos_no: raw_line}

    for raw_line in processed_text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 7:
            continue
        if re.match(r'^\d{1,2}[\.\):]?\s*$', line):
            continue
        # Çizgi / tire ayraç satırları: "___", "---", "==="
        if re.match(r'^[_\-=]{3,}$', line):
            continue
        if any(w in line.lower() for w in skip_words):
            continue
        line_l = line.lower()
        if any(re.search(r'\b' + w + r'\b', line_l) and
               not re.search(r'[a-z]' + w, line_l)
               for w in month_standalone):
            continue

        home = away = None
        o1 = ox = o2 = None

        m = line_re.match(line)
        if m:
            home = _clean_team(m.group(1))
            away = _clean_team(m.group(2))
            o1 = float(m.group(3)) if m.group(3) else None
            ox = float(m.group(4)) if m.group(4) else None
            o2 = float(m.group(5)) if m.group(5) else None
        else:
            m2 = nospace_re.match(line)
            if m2:
                home = _clean_team(m2.group(1))
                away = _clean_team(m2.group(2))
            else:
                # Numaralı ama ayraç yok → OCR hatası, kaydet
                mf = numbered_no_sep_re.match(line)
                if mf:
                    pos = int(mf.group(1))
                    if 1 <= pos <= 15:
                        failed_lines[pos] = mf.group(2).strip()
                continue

        if not home or not away:
            continue
        if len(home) < 3 or len(away) < 3:
            continue
        entry = {
            "no":   len(out) + 1,
            "home": home,
            "away": away,
            "date": "", "time": "",
            "odds": {"1": o1, "X": ox, "2": o2},
        }
        if len(out) == 0 and _header:
            entry["week_header"] = _header
        out.append(entry)
        if len(out) == 15:
            break

    # Kaçan maçları out'a ekle (pozisyon bilgisiyle)
    # _ParseResult: list + _failed dict taşıyan hafif wrapper
    class _ParseResult(list):
        pass
    result = _ParseResult(out)
    result._failed = failed_lines
    return result
    import unicodedata
    out = []

    # ── NFD → NFC normalize (telefon clipboard'ından NFD gelirse Türkçe
    # karakterler U+0327 gibi birleştirici karakterlere dönüşür ve regex'i kırar)
    text = unicodedata.normalize('NFC', text)

    # OCR hata duzeltme
    ocr_fixes = [
        ('$',  'S'), ('\uff04', 'S'),
        ('|',  'I'), ('\u00a6', 'I'),
        ('\u2013', '-'), ('\u2014', '-'), ('\u2212', '-'),
        ('\u00e2\u0080\u0093', '-'),
    ]
    for frm, to in ocr_fixes:
        text = text.replace(frm, to)
    text = re.sub(r'A\.\$\.', 'A.S.', text)
    text = re.sub(r'A\$',     'AS',   text)

    # ── OCR satır yapıştırma düzeltmesi ──────────────────────────────
    # "FENERBAHÇE A. ŞEYUPSPOR" → "FENERBAHÇE - EYÜPSPOR" değil
    # ama "A. Ş" kısaltmasını takım adından ayır
    # Yaygın birleşme hataları: "A.Ş" → boşluk
    text = re.sub(r'([A-ZÇĞİÖŞÜ])\s+A\.\s*Ş\.?\s+([A-ZÇĞİÖŞÜ])', r'\1 - \2', text)
    text = re.sub(r'([A-ZÇĞİÖŞÜ])\s+A\.\s*Ş\.?\s*-\s*', r'\1 - ', text)
    # "KO CAELISPOR" gibi OCR kelime bölünmelerini birleştir (kısa parça + uzun parça)
    # Bu agresif olabilir, sadece bilinen takımları düzelt
    ocr_team_fixes = {
        'KO CAELISPOR':   'KOCAELISPOR',
        'KOCAELI SPOR':   'KOCAELISPOR',
        'BASAKŞEHIR':     'BAŞAKŞEHIR',
        'BASAKSEHIR':     'BAŞAKŞEHIR',
        'GAZIANTEP F K':  'GAZIANTEP FK',
        'GAZIANTEP F. K': 'GAZIANTEP FK',
        'ÇAYKUR RIZESPOR A': 'ÇAYKUR RİZESPOR',
        'RIZESPOR A':     'RİZESPOR',
        'TRABZONSPOR A':  'TRABZONSPOR',
        'KASIMPASA':      'KASIMPAŞA',
        'ACLENS':         'LENS',
        'AC LENS':        'LENS',
        'GENCLERBIRLIGI': 'GENÇLERBİRLİĞİ',
        'GALATASARAYA':   'GALATASARAY',
        'GALATASARAY.Ş':  'GALATASARAY',
        'GALATASARAYA.Ş': 'GALATASARAY',
        'KASIMPAŞA AŞ.-': 'KASIMPAŞA -',
        'KASIMPAŞA AŞ. -': 'KASIMPAŞA -',
        # Kelime bölünmesi düzeltmeleri
        'ANTALYASPOR KO CAELISPOR': 'ANTALYASPOR - KOCAELISPOR',
        'KO CAELISPOR':  'KOCAELISPOR',
        # Çaykur stray rakam: "1 ÇAYKUR" merge edilince
        '1 ÇAYKUR':      'ÇAYKUR',
        'ÇAYKUR RIZESPOR  - BEŞİKTAŞ': 'ÇAYKUR RİZESPOR - BEŞİKTAŞ',
        'RIZESPOR  -':   'RİZESPOR -',
        'BEŞİKT ':       'BEŞİKTAŞ ',  # kırpma düzeltme
        'ANTALYASPOR - KOCAELISPOR': 'ANTALYASPOR - KOCAELISPOR',
    }
    for wrong, correct in ocr_team_fixes.items():
        text = text.replace(wrong, correct)

    # ── A.Ş. kısaltmasını ayraç olarak kullan ─────────────────────────
    text = re.sub(r'(\w)\s+A\.\s*[SŞ]\.?\s*-\s*', r'\1 - ', text)
    text = re.sub(r'(\w)\s+A[SŞ]\.?\s*-\s*', r'\1 - ', text)
    text = re.sub(r'(\w)\s+A\.\s*[SŞ]\.?\s+([A-ZÇĞİÖŞÜ])', r'\1 - \2', text)

    # ── Sondaki A. 5. / A. 6. temizle ───────────────────────────────
    text = re.sub(r'\s+A\.\s*\d+\.\s*$', '', text, flags=re.M)
    text = re.sub(r'\s+A\.\s*\d+\.(\s*-)', r'\1', text)
    text = re.sub(r'\s+A\.\s*\d+\.', '', text)

    # ── "..." ile ayrılan takımlar → tire ────────────────────────────
    text = re.sub(r'\s+A\.{2,}\s+', ' - ', text)
    text = re.sub(r'\.{3,}\s+', ' - ', text)

    # ── GALATASARAYA.Ş. → GALATASARAY ────────────────────────────────
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{4,})A\.?[SŞ]\.?\s*$', r'\1', text, flags=re.M)
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{4,})A\.?[SŞ]\.?(\s)', r'\1\2', text)

    # ── "FENERBAHÇE A. Ş" → "FENERBAHÇE" (A.Ş. takım adına yapışmış) ─
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{4,})\s+A\.\s+[SŞ]([A-ZÇĞİÖŞÜ])', r'\1 - \2', text)

    # ── "ANTALYASPOR KO CAELISPOR" → "ANTALYASPOR KOCAELISPOR" ───────
    # Kelime bölünmesi: 2-3 harf + büyük devam → birleştir
    text = re.sub(r'([A-ZÇĞİÖŞÜ]{6,})\s+([A-ZÇĞİÖŞÜ]{2,4})\s+([A-ZÇĞİÖŞÜ]{4,})',
                  lambda m: m.group(0)
                  if '-' in m.group(0)
                  else f"{m.group(1)} - {m.group(2)}{m.group(3)}"
                  if len(m.group(2)) <= 3
                  else m.group(0),
                  text)

    # ── ÖN İŞLEME: Numara ayrı satırda ise bir sonraki satırla birleştir ──
    # "1.\n" + "ALANYASPOR - KAYSERISPOR" → "1. ALANYASPOR - KAYSERISPOR"
    raw_lines = text.splitlines()

    # Başlık satırını bul: "8 MAYIS - 12 MAYIS 2026"
    _header = ""
    for _l in raw_lines[:6]:
        if any(ay in _l.lower() for ay in ["ocak","şubat","mart","nisan","mayıs","mayis",
                                             "haziran","temmuz","ağustos","agustos",
                                             "eylül","eylul","ekim","kasım","kasim","aralık","aralik"]):
            _header = _l.strip()
            break

    merged = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i].strip()
        # Sadece numara olan satır (örn: "1.", "2.", "71.")
        if re.match(r'^\d{1,2}\.?\s*$', line) and i + 1 < len(raw_lines):
            next_line = raw_lines[i+1].strip()
            if next_line and not re.match(r'^\d{1,2}\.?\s*$', next_line):
                # Yanlış numaraları düzelt: 71 → 11, vs.
                num = int(re.search(r'\d+', line).group())
                if num > 15:
                    num = len(merged) + 1  # sıradaki doğru no
                merged.append(f"{num}. {next_line}")
                i += 2
                continue
        # Baştaki stray rakamı temizle: "1 ÇAYKUR" → "ÇAYKUR"
        line = re.sub(r'^\d\s+(?=[A-ZÇĞİÖŞÜ])', '', line)
        merged.append(line)
        i += 1

    processed_text = "\n".join(merged)

    # ── REGEX: [^\d\n] kullanımı — sabit Unicode aralığına bağımlı değil,
    # NFD birleştirici karakterler (U+0327 gibi) dahil tüm harfler eşleşir.
    # Ayraç etrafında {1,6} boşluk — bazı OCR/kopya sistemleri fazla boşluk ekler.
    # vs. ayracı da desteklenir.
    _tc = r'[^\n]'  # takım adı karakteri: yeni satır dışı her şey (COMO 1907 gibi rakam içeren isimler için)
    line_re = re.compile(
        r'^(?:\d{1,2}[\.\):\s]+)?'
        r'(' + _tc + r'{3,50}?)'
        r'(?:\s{1,6}[-]\s{1,6}|\.{2,3}|\s{1,6}vs\.?\s{1,6})'
        r'(' + _tc + r'{3,60})'
        r'(?:\s+([\d\.]+)\s+([\d\.]+)\s+([\d\.]+))?'
        r'\s*$',
        re.UNICODE
    )
    # Bosluksuz tire
    nospace_re = re.compile(
        r'^(' + _tc + r'{3,40})-(' + _tc + r'{3,40})$',
        re.UNICODE
    )

    skip_words = ['hafta', 'liste', 'toto', 'tahmin', 'bolum', 'sezon', 'program',
                  'ocak', 'subat', 'mart', 'mayis', 'haziran', 'temmuz',
                  'agustos', 'eylul', 'ekim', 'aralik']
    month_standalone = ['nisan', 'kasim']

    for raw_line in processed_text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 7:
            continue
        if re.match(r'^\d{1,2}[\.\):]?\s*$', line):
            continue
        if any(w in line.lower() for w in skip_words):
            continue
        line_l = line.lower()
        if any(re.search(r'\b' + w + r'\b', line_l) and
               not re.search(r'[a-z]' + w, line_l)
               for w in month_standalone):
            continue

        home = away = None
        o1 = ox = o2 = None

        m = line_re.match(line)
        if m:
            home = _clean_team(m.group(1))
            away = _clean_team(m.group(2))
            o1 = float(m.group(3)) if m.group(3) else None
            ox = float(m.group(4)) if m.group(4) else None
            o2 = float(m.group(5)) if m.group(5) else None
        else:
            m2 = nospace_re.match(line)
            if m2:
                home = _clean_team(m2.group(1))
                away = _clean_team(m2.group(2))

        if not home or not away:
            continue
        if len(home) < 3 or len(away) < 3:
            continue
        entry = {
            "no":   len(out) + 1,
            "home": home,
            "away": away,
            "date": "", "time": "",
            "odds": {"1": o1, "X": ox, "2": o2},
        }
        # İlk maça hafta başlığını ekle (week_id için)
        if len(out) == 0 and _header:
            entry["week_header"] = _header
        out.append(entry)
        if len(out) == 15:
            break
    return out


def _source_manual() -> list:
    """
    Kaynak 4: Hızlı toplu yapıştırma girişi.

    Kullanıcı tüm 15 maçı tek seferde yapıştırır,
    ardından boş satır (Enter) ile onaylar.
    OCR'ın tireyi yuttuğu satırlar tespit edilip tek tek sorulur.
    """
    print()
    print("  ┌─ TOPLU YAPIŞTIRIM MODU ─────────────────────────────────┐")
    print("  │ Tüm maçları kopyalayıp yapıştır, sonra BOŞ SATIR + Enter│")
    print("  │                                                          │")
    print("  │ Desteklenen formatlar:                                   │")
    print("  │   Antalyaspor - Konyaspor                                │")
    print("  │   1. Fenerbahce - Rizespor                               │")
    print("  │   Man City - Arsenal  2.20 3.40 3.20   (oran ekleyebilir)│")
    print("  └──────────────────────────────────────────────────────────┘")
    print()

    lines = []
    try:
        empty_count = 0
        while True:
            line = input()
            if line.strip() == "":
                empty_count += 1
                if empty_count >= 1 and lines:
                    break
            else:
                empty_count = 0
                lines.append(line)
    except (EOFError, KeyboardInterrupt):
        pass

    out = _parse_bulk("\n".join(lines))

    # ── Kaçan numaralı satırları ele al (OCR tire yutması) ───────────
    failed = getattr(out, '_failed', {})
    if failed:
        print(f"\n  ⚠  {len(failed)} maç parse edilemedi (OCR tire hatası):")
        for pos, raw in sorted(failed.items()):
            print(f"     Maç {pos:>2}: '{raw}'")
        print()
        for pos, raw in sorted(failed.items()):
            print(f"  Maç {pos} → '{raw}'")
            print(f"  Doğrusunu girin  (örn: EV TAKIMI - DEP TAKIMI): ", end="", flush=True)
            try:
                fix = input().strip()
            except (EOFError, KeyboardInterrupt):
                fix = ""
            if not fix:
                continue
            # Girişi parse et
            fixed = _parse_bulk(f"{pos}. {fix}")
            if fixed:
                entry = fixed[0]
                entry["no"] = pos
                # Doğru pozisyona yerleştir
                inserted = False
                for idx, existing in enumerate(out):
                    if existing["no"] >= pos:
                        out.insert(idx, entry)
                        inserted = True
                        break
                if not inserted:
                    out.append(entry)
                # Sonraki numaraları güncelle
                for idx, r in enumerate(out):
                    r["no"] = idx + 1
                print(f"  ✓ Maç {pos}: {entry['home']} - {entry['away']}")

    if len(out) >= 13:
        print(f"\n  ✓ {len(out)} maç parse edildi.")
        # Parse sonucu göster
        for r in out:
            print(f"    {r['no']:>2}. {r['home']} - {r['away']}")
        return out

    # Yeterli maç bulunamadıysa
    print(f"\n  {len(out)} maç parse edildi. Eksik satırları kontrol et.")
    for r in out:
        print(f"    {r['no']:>2}. {r['home']} - {r['away']}")

    if out:
        print("\n  Devam etmek için Enter, yeniden girmek için 'r': ", end="")
        try:
            ans = input().strip().lower()
        except (ValueError, TypeError, KeyError, AttributeError, requests.exceptions.RequestException):
            ans = ""
        if ans != "r":
            return out

    return _source_manual()


def _source_mht(path: str = None) -> list:
    """
    Kaynak 5: sportoto.gov.tr sayfasının MHT (MHTML) kaydından maç listesi çek.

    Chrome / Edge → Farklı Kaydet → 'Web Arşivi, tek dosya (.mht)'
    Firefox       → Farklı Kaydet → 'Web Arşivi (.mhtml)'

    Tablo yapısı:
        [sıra, maç, maç_günü, maç_saati, skor, sonuç]

    Hafta numarası:
        İndirme linkinden çıkarılır:
        webapi.sportoto.gov.tr/image/sportoto44-xxxx.png → 44

    path: MHT dosya yolu. None ise proje kökünde 'spor_toto.mht' aranır.
    """
    import email as _email, re as _re
    from bs4 import BeautifulSoup as _BS

    # Varsayılan yol
    if path is None:
        _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for candidate in ["spor_toto.mht", "spor_toto.mhtml",
                          "Spor_Toto_Listeler.mht", "sportoto.mht"]:
            _p = os.path.join(_base, candidate)
            if os.path.exists(_p):
                path = _p
                break
    if not path or not os.path.exists(path):
        return []

    try:
        with open(path, "rb") as f:
            raw = f.read()

        msg = _email.message_from_bytes(raw)
        html = ""
        for part in msg.walk():
            if "html" in part.get_content_type():
                payload = part.get_payload(decode=True)
                if payload:
                    html = payload.decode("utf-8", errors="replace")
                    break
        if not html:
            return []

        soup = _BS(html, "html.parser")

        # ── Hafta numarası — indirme linkinden ──────────────────────
        week_no = 0
        dl = soup.find("a", href=_re.compile(r"webapi.*image"))
        if dl:
            m = _re.search(r"sportoto(\d+)", dl["href"])
            if m:
                week_no = int(m.group(1))

        # ── Sezon ────────────────────────────────────────────────────
        season_str = ""
        for el in soup.find_all(string=_re.compile(r"\d{4}/\d{4}\s*Sezonu")):
            season_str = el.strip()
            break
        # "2025/2026 Sezonu" → "2526"
        sm = _re.search(r"\d{2}(\d{2})/\d{2}(\d{2})\s*Sezonu", season_str)
        season_code = (sm.group(1) + sm.group(2)) if sm else ""

        # ── Maç tablosu ───────────────────────────────────────────────
        tables = soup.find_all("table")
        if not tables:
            return []

        out = []
        week_header = f"ST{week_no}-{season_code}" if week_no else ""

        for row in tables[0].find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2 or not cells[0].isdigit():
                continue

            no   = int(cells[0])
            mac  = cells[1]   # "Galatasaray - Fenerbahce"
            gun  = cells[2] if len(cells) > 2 else ""   # "07.06.2026-Pazar"
            saat = cells[3] if len(cells) > 3 else ""   # "19:00"
            skor = cells[4] if len(cells) > 4 else ""   # "-" veya "2-1"
            sonuc= cells[5] if len(cells) > 5 else ""   # "1" / "X" / "2"

            # Skor parse: "2-1" → home_score=2, away_score=1
            skor_m = _re.match(r"(\d+)\s*-\s*(\d+)", skor)
            actual = sonuc.strip() if sonuc.strip() in ("1", "X", "2") else ""

            # Takım adları
            sep = _re.split(r"\s+-\s+", mac, maxsplit=1)
            if len(sep) != 2:
                continue
            home = _clean_team(sep[0])
            away = _clean_team(sep[1])
            if len(home) < 3 or len(away) < 3:
                continue

            # Tarih parse: "07.06.2026-Pazar" → "2026-06-07"
            date_str = ""
            dm = _re.match(r"(\d{2})\.(\d{2})\.(\d{4})", gun)
            if dm:
                date_str = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"

            entry = {
                "no":     no,
                "home":   home,
                "away":   away,
                "date":   date_str,
                "time":   saat,
                "actual": actual,          # Sonuç açıklandıysa doldurulur
                "score":  skor if skor_m else "",
                "odds":   {"1": None, "X": None, "2": None},
            }
            if no == 1 and week_header:
                entry["week_header"] = week_header

            out.append(entry)
            if len(out) == 15:
                break

        if out:
            print(f"    ✓ MHT: {len(out)} maç  |  "
                  f"Hafta: {week_header or '?'}  |  {path}")
        return out

    except Exception as e:
        print(f"    MHT parse hatası: {e}")
        return []


def fetch_weekly_list(force_manual=False, mht_path=None) -> list:
    """
    Haftalık listeyi çek. Sırayla kaynaklar denenir.
    force_manual=True ise direkt elle girişe geç.
    mht_path: MHT dosya yolu verilirse direkt parse edilir.
    """
    if force_manual:
        return _source_manual()

    # MHT yolu verilmişse direkt dene
    if mht_path:
        result = _source_mht(mht_path)
        if result:
            return result

    print("\n[ADIM 1] Haftalık liste çekiliyor...")
    sources = [
        ("MHT dosyası",            lambda: _source_mht()),
        ("webapi.sportoto.gov.tr", _source_sportoto_api),
        ("sportoto JS tarama",     _source_sportoto_js),
        ("iddaa.com",              _source_iddaa),
        ("nesine.com",             _source_nesine),
    ]
    for name, fn in sources:
        print(f"  → {name} deneniyor...")
        result = fn()
        if result:
            return result
    print("  ! Tüm kaynaklar başarısız → manuel girişe geçiliyor.")
    return _source_manual()

# ═══════════════════════════════════════════════════════════════

def _source_file(path: str) -> list:
    """Metin dosyasından mac listesi oku. Her satir bir mac."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        out = _parse_bulk(text)
        if out:
            print(f"  Dosyadan {len(out)} mac okundu: {path}")
        return out
    except (OSError, IOError, ValueError, TypeError, AttributeError) as e:
        print(f"  Dosya okuma hatasi: {e}")
        return []


def _source_image_ocr(path: str) -> list:
    """
    Resim dosyasindan OCR ile mac listesi cikar.
    Oncelik sirasi: pytesseract -> easyocr -> pillow+regex
    """
    # --- pytesseract dene ---
    try:
        import pytesseract
        from PIL import Image
        img  = Image.open(path)
        text = pytesseract.image_to_string(img, lang="tur+eng")
        out  = _parse_bulk(text)
        if out:
            print(f"  pytesseract OCR: {len(out)} mac")
            return out
    except ImportError:
        pass
    except (OSError, IOError, ValueError, TypeError, AttributeError) as e:
        print(f"  pytesseract hatasi: {e}")

    # --- easyocr dene ---
    try:
        import easyocr
        reader = easyocr.Reader(["tr", "en"], gpu=False, verbose=False)
        results = reader.readtext(path, detail=0)
        text = "\n".join(results)
        out  = _parse_bulk(text)
        if out:
            print(f"  easyocr OCR: {len(out)} mac")
            return out
    except ImportError:
        pass
    except (OSError, IOError, ValueError, TypeError, AttributeError) as e:
        print(f"  easyocr hatasi: {e}")

    print("  OCR kutuphanesi bulunamadi.")
    print("  Kurmak icin:")
    print("    pip install pytesseract pillow")
    print("    pkg install tesseract  (Termux)")
    print("  VEYA:")
    print("    pip install easyocr")
    return []


