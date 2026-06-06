# -*- coding: utf-8 -*-
"""
memory/performance_xray.py — Performans Röntgeni
=================================================
Sistemin tahmin kalitesini 6 boyutta analiz eder.

Bölümler:
  1. Genel Skor Kartı
  2. Pozisyon Bazlı Performans
  3. Bahis Türü Analizi (BANKO/ÇİFT/KAOS)
  4. Olasılık Kalibrasyon Analizi
  5. Hata Deseni Analizi
  6. Aksiyon Önerileri

Veri Kaynağı:
  st_memory.json  → istatistikler, hafta geçmişi
  st_predictions.json → maç detayları, P1/PX/P2

Kullanım:
  from memory.performance_xray import run_xray
  run_xray(mem)   # mem = STMemory nesnesi
"""

from __future__ import annotations
import json, os, math
from collections import defaultdict
from typing import Optional

# ─── ANSI renkler ──────────────────────────────────────────────────────────────
R  = "\033[0m"
B  = "\033[1m"
G  = "\033[32m"
Y  = "\033[33m"
C  = "\033[36m"
RE = "\033[31m"
M  = "\033[35m"
DM = "\033[2m"
W  = "\033[37m"


# ══════════════════════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════════════════════════════

def _bar(val: float, max_val: float = 1.0, width: int = 10,
         low_good: bool = False) -> str:
    """ASCII ilerleme çubuğu."""
    ratio = min(1.0, max(0.0, val / max_val)) if max_val else 0.0
    filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    if low_good:
        color = G if ratio < 0.4 else (Y if ratio < 0.65 else RE)
    else:
        color = G if ratio >= 0.65 else (Y if ratio >= 0.45 else RE)
    return f"{color}{bar}{R}"


def _grade(acc: float) -> str:
    """Doğruluk → not."""
    if acc >= 0.85: return f"{G}{B}A+{R}"
    if acc >= 0.75: return f"{G}A{R}"
    if acc >= 0.65: return f"{G}B+{R}"
    if acc >= 0.55: return f"{Y}B{R}"
    if acc >= 0.45: return f"{Y}C{R}"
    return f"{RE}D{R}"


def _brier_grade(b: float) -> str:
    if b < 0.15: return f"{G}Mükemmel{R}"
    if b < 0.22: return f"{G}İyi{R}"
    if b < 0.28: return f"{Y}Orta{R}"
    return f"{RE}Zayıf{R}"


def _trend_arrow(vals: list) -> str:
    """Son değerlere göre trend oku."""
    if len(vals) < 2:
        return f"{DM}─{R}"
    delta = vals[-1] - vals[0]
    if delta > 0.03:  return f"{G}↑ İyileşiyor (+{delta*100:.1f}%){R}"
    if delta < -0.03: return f"{RE}↓ Kötüleşiyor ({delta*100:.1f}%){R}"
    return f"{Y}→ Stabil{R}"


def _sep(width: int = 60, char: str = "─") -> str:
    return f"  {DM}{char * width}{R}"


def _load_predictions(pred_file: str) -> dict:
    """st_predictions.json'u yükle."""
    if not os.path.exists(pred_file):
        return {}
    try:
        with open(pred_file, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _normalize_pred(pred: str) -> str:
    """pred_label → kategori: BANKO/ÇİFT/KAOS."""
    p = pred.upper() if pred else ""
    if "1X2" in p or ("1X" in p and "2" in p): return "KAOS"
    if "1X" in p or "X2" in p or "12" in p:    return "ÇİFT"
    if "TEK" in p or p in ("1","X","2"):        return "BANKO"
    if "ÇİFT" in p or "CIFT" in p:             return "ÇİFT"
    return "DİĞER"


def _actual_to_result(actual: str) -> str:
    """H/D/A veya 1/X/2 veya 0 → 1/X/2"""
    return {"H":"1","D":"X","A":"2","1":"1","X":"X","2":"2","0":"X"}.get(actual, "")


def _is_correct(pred: str, actual: str) -> Optional[bool]:
    """Tahmin doğru mu? H/D/A ve 1/X/2 ve 0 formatlarını kabul eder."""
    if not actual:
        return None
    res = _actual_to_result(actual)
    if not res:
        return None
    p = pred.upper() if pred else ""
    if res in p: return True
    if p in ("1","X","2") and p == res: return True
    if "TEK" in p:
        tag = p.replace("TEK","").strip()
        return tag == res
    return False


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 1 — GENEL SKOR KARTI
# ══════════════════════════════════════════════════════════════════════════════

def _section_genel(mem_data: dict, wh: list) -> list:
    """Genel skor kartı satırları."""
    lines = []
    ss    = mem_data.get("season_summary", {})
    total = ss.get("total", 0)
    corr  = ss.get("correct", 0)

    # season_summary boşsa weekly_history'den hesapla
    if total == 0 and wh:
        total = sum(h.get("total", 0) for h in wh)
        corr  = sum(h.get("correct", 0) for h in wh)

    acc   = corr / total if total else 0.0

    brierlst = [h["brier"] for h in wh
                if h.get("brier") is not None and h.get("status") == "completed"]
    brier_avg = sum(brierlst) / len(brierlst) if brierlst else None

    loglst = [h["logloss"] for h in wh
              if h.get("logloss") is not None and h.get("status") == "completed"]
    llog_avg  = sum(loglst) / len(loglst) if loglst else None

    acc_trend = [h["acc"] for h in wh[-5:]
                 if h.get("acc") is not None and h.get("status") == "completed"]

    # Kalibrasyon (overconfidence değeri — dict içinde)
    calib_vals = []
    for h in wh:
        c = h.get("calibration")
        if isinstance(c, dict):
            oc = c.get("overconfidence")
            if oc is not None:
                calib_vals.append(abs(float(oc)))
        elif isinstance(c, (int, float)) and c is not None:
            calib_vals.append(abs(float(c)))
    calib_avg  = sum(calib_vals)/len(calib_vals) if calib_vals else None

    lines.append(f"\n  {B}{C}① GENEL SKOR KARTI{R}")
    lines.append(_sep())
    lines.append(f"  Toplam Tahmin  : {B}{total}{R} maç  ({corr} doğru)")
    lines.append(f"  Genel Doğruluk : {B}%{acc*100:.1f}{R}  "
                 f"{_bar(acc)}  {_grade(acc)}")
    if brier_avg is not None:
        lines.append(f"  Brier Skoru    : {B}{brier_avg:.3f}{R}  "
                     f"{_bar(brier_avg, 0.33, low_good=True)}  {_brier_grade(brier_avg)}")
    if llog_avg is not None:
        lines.append(f"  Log-Loss       : {B}{llog_avg:.3f}{R}")
    if len(acc_trend) >= 2:
        lines.append(f"  Son 5H Trendi  : {_trend_arrow(acc_trend)}")
    if calib_avg is not None:
        cal_str = f"{G}İyi{R}" if calib_avg < 0.06 else \
                  (f"{Y}Orta{R}" if calib_avg < 0.12 else f"{RE}Zayıf{R}")
        lines.append(f"  Kalibrasyon    : ±{calib_avg:.3f}  {cal_str}")

    # Haftalık tablo
    if wh:
        lines.append(f"\n  {'Hafta':<14} {'Doğru':>6} {'%':>6} "
                     f"{'Brier':>7} {'Zorluk':<10} {'Durum'}")
        lines.append(f"  {DM}{'─'*58}{R}")
        for h in wh[-8:]:
            if h.get("status") != "completed": continue
            ha  = h.get("acc", 0)
            hb  = f"{h['brier']:.3f}" if h.get("brier") else "  —  "
            hdl = h.get("diff_label", "")
            hok = f"{G}✓{R}" if ha >= 0.70 else (f"{Y}~{R}" if ha >= 0.55 else f"{RE}✗{R}")
            lines.append(
                f"  {h['week']:<14} {h['correct']:>3}/{h['total']:<2}"
                f"  {ha*100:>5.1f}%  {hb:>6}  {hdl:<10}  {hok}")
    return lines


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 2 — POZİSYON BAZLI PERFORMANS
# ══════════════════════════════════════════════════════════════════════════════

def _section_pozisyon(pred_data: dict, genel_acc: float) -> list:
    """Pozisyon bazlı performans (1-15)."""
    lines = []
    pos_stats = defaultdict(lambda: {"correct": 0, "total": 0})

    for wk, wd in pred_data.items():
        for m in wd.get("matches", []):
            pos = m.get("no")
            if not pos: continue
            actual  = m.get("actual", "")
            _norm_a = {"1":"H","X":"D","2":"A","0":"D"}
            actual  = _norm_a.get(actual, actual)
            pred_lbl = m.get("pred_label", m.get("pred",""))
            if not actual or actual not in ("H","D","A"): continue
            ok = _is_correct(pred_lbl, actual)
            if ok is None: continue
            pos_stats[int(pos)]["total"]   += 1
            pos_stats[int(pos)]["correct"] += int(ok)

    if not pos_stats:
        return [f"\n  {DM}Pozisyon verisi yok (sonuçlar girilmemiş){R}"]

    # genel_acc 0 ise pred_data'dan hesapla
    if genel_acc == 0:
        _total = sum(s["total"] for s in pos_stats.values())
        _corr  = sum(s["correct"] for s in pos_stats.values())
        genel_acc = _corr / _total if _total else 0.0

    lines.append(f"\n  {B}{C}② POZİSYON BAZLI PERFORMANS{R}")
    lines.append(_sep())
    lines.append(f"  {'Pos':>4}  {'N':>4}  {'Doğru':>6}  {'Oran':>6}  "
                 f"{'vs Genel':>9}  {'Durum'}")
    lines.append(f"  {DM}{'─'*56}{R}")

    weak, strong = [], []
    for pos in sorted(pos_stats):
        s   = pos_stats[pos]
        n   = s["total"]
        if n < 3: continue
        acc = s["correct"] / n
        diff = acc - genel_acc
        diff_str = f"{diff*100:+.1f}%"
        diff_color = G if diff > 0.05 else (RE if diff < -0.10 else Y)
        bar  = _bar(acc, 1.0, 8)
        if acc < genel_acc - 0.10 and n >= 5:
            icon = f"{RE}⚠ ZAYIF{R}"
            weak.append(pos)
        elif acc >= genel_acc + 0.05:
            icon = f"{G}✅ İYİ{R}"
            strong.append(pos)
        else:
            icon = f"{DM}Orta{R}"
        lines.append(
            f"  {pos:>4}  {n:>4}  {s['correct']:>4}/{n:<2}  "
            f"{acc*100:>5.1f}%  {diff_color}{diff_str:>8}{R}  {icon}")

    if weak:
        lines.append(f"\n  {RE}⚠ Zayıf Pozisyonlar: {weak}{R}")
        lines.append(f"  {DM}  → Bu pozisyonlarda BANKO verme eşiğini yükselt{R}")
    if strong:
        lines.append(f"  {G}✅ Güçlü Pozisyonlar: {strong}{R}")
    return lines


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 3 — BAHİS TÜRÜ ANALİZİ
# ══════════════════════════════════════════════════════════════════════════════

def _section_bahis_turu(pred_data: dict) -> list:
    """BANKO / ÇİFT / KAOS başarı analizi."""
    lines   = []
    buckets = defaultdict(lambda: {"correct": 0, "total": 0})
    result_dist = defaultdict(lambda: defaultdict(int))

    for wk, wd in pred_data.items():
        for m in wd.get("matches", []):
            actual   = m.get("actual", "")
            _norm_a  = {"1":"H","X":"D","2":"A","0":"D"}
            actual   = _norm_a.get(actual, actual)
            pred_lbl = m.get("pred_label", m.get("pred",""))
            if not actual or actual not in ("H","D","A"): continue
            cat = _normalize_pred(pred_lbl)
            ok  = _is_correct(pred_lbl, actual)
            if ok is None: continue
            buckets[cat]["total"]   += 1
            buckets[cat]["correct"] += int(ok)
            result_dist[cat][_actual_to_result(actual)] += 1

    if not buckets:
        return [f"\n  {DM}Bahis türü verisi yok{R}"]

    lines.append(f"\n  {B}{C}③ BAHİS TÜRÜ ANALİZİ{R}")
    lines.append(_sep())
    lines.append(f"  {'Tür':<8}  {'N':>4}  {'Doğru':>6}  {'Oran':>7}  "
                 f"{'Değerlendirme'}")
    lines.append(f"  {DM}{'─'*52}{R}")

    order = ["BANKO","ÇİFT","KAOS","DİĞER"]
    for cat in order:
        if cat not in buckets: continue
        s   = buckets[cat]
        n   = s["total"]
        acc = s["correct"] / n
        bar = _bar(acc, 1.0, 8)
        if acc >= 0.70:   verdict = f"{G}✅ Güvenilir{R}"
        elif acc >= 0.55: verdict = f"{Y}⚠ Orta{R}"
        else:             verdict = f"{RE}✗ Zayıf{R}"

        dist = result_dist[cat]
        dist_str = (f"[1:{dist.get('1',0)} X:{dist.get('X',0)} "
                    f"2:{dist.get('2',0)}]")
        lines.append(f"  {cat:<8}  {n:>4}  "
                     f"{s['correct']:>4}/{n:<2}  "
                     f"{acc*100:>5.1f}%  {bar}  {verdict}")
        lines.append(f"  {DM}{'':8}  {'':4}  {'':6}  Sonuç dağılımı: {dist_str}{R}")
    return lines


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 4 — OLASILIK KALİBRASYON ANALİZİ
# ══════════════════════════════════════════════════════════════════════════════

def _section_kalibrasyon(pred_data: dict) -> list:
    """Güven aralıkları → gerçek kazanma oranı karşılaştırması."""
    lines  = []
    # 5 aralık: <50, 50-60, 60-70, 70-80, 80+
    bins   = [(0,50),(50,60),(60,70),(70,80),(80,101)]
    bstats = {b: {"win":0,"total":0} for b in bins}

    for wk, wd in pred_data.items():
        for m in wd.get("matches", []):
            actual = m.get("actual","")
            _norm_a = {"1":"H","X":"D","2":"A","0":"D"}
            actual  = _norm_a.get(actual, actual)
            if not actual or actual not in ("H","D","A"): continue
            # En yüksek olasılığı al
            p1 = float(m.get("P1") or 0)
            px = float(m.get("PX") or 0)
            p2 = float(m.get("P2") or 0)
            max_p  = max(p1, px, p2)
            pred_lbl = m.get("pred_label", m.get("pred",""))
            ok = _is_correct(pred_lbl, actual)
            if ok is None: continue
            for lo, hi in bins:
                if lo <= max_p < hi:
                    bstats[(lo,hi)]["total"] += 1
                    if ok: bstats[(lo,hi)]["win"] += 1
                    break

    has_data = any(v["total"] > 0 for v in bstats.values())
    if not has_data:
        return [f"\n  {DM}Kalibrasyon verisi yok{R}"]

    lines.append(f"\n  {B}{C}④ OLASILIK KALİBRASYON{R}")
    lines.append(_sep())
    lines.append(f"  {'Güven Aralığı':<16}  {'N':>4}  "
                 f"{'Söylenen':>9}  {'Gerçek':>8}  {'Fark':>7}  {'Durum'}")
    lines.append(f"  {DM}{'─'*62}{R}")

    for lo, hi in bins:
        s = bstats[(lo,hi)]
        n = s["total"]
        if n == 0: continue
        real_acc  = s["win"] / n
        mid_guess = (lo + min(hi,100)) / 200.0   # aralık ortası
        diff      = real_acc - mid_guess
        diff_str  = f"{diff*100:+.1f}%"
        if abs(diff) < 0.08:
            verdict = f"{G}✅ İyi kalibre{R}"
        elif diff > 0:
            verdict = f"{G}↑ Hafife düşük güven{R}"
        else:
            verdict = f"{RE}↓ Fazla güveniyor{R}"
        hi_str = "100" if hi == 101 else str(hi)
        lines.append(
            f"  %{lo:>2}–%{hi_str:<4}          {n:>4}  "
            f"~%{(lo+min(hi,100))//2:>2} tahmin  "
            f"%{real_acc*100:>5.1f}    "
            f"{diff_str:>7}  {verdict}")

    lines.append(f"\n  {DM}Not: 'Fazla güveniyor' → sistem o aralıkta gerçekte daha az doğru{R}")
    return lines


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 5 — HATA DESENİ ANALİZİ
# ══════════════════════════════════════════════════════════════════════════════

def _section_hata_deseni(mem_data: dict, pred_data: dict) -> list:
    """Sistematik hata analizi."""
    lines = []
    ep    = mem_data.get("error_patterns", {})

    # Ek hesaplamalar: maç bazlı
    kaos_actual = defaultdict(int)   # KAOS tahmininde gerçek sonuç
    high_conf_miss = {"draw": 0, "total": 0}
    result_after_loss = {"correct": 0, "total": 0}   # deplasman sonrası

    for wk, wd in pred_data.items():
        for m in wd.get("matches", []):
            actual   = m.get("actual", "")
            _norm_a  = {"1":"H","X":"D","2":"A","0":"D"}
            actual   = _norm_a.get(actual, actual)
            if not actual or actual not in ("H","D","A"): continue
            pred_lbl = m.get("pred_label", m.get("pred",""))
            cat      = _normalize_pred(pred_lbl)
            p1 = float(m.get("P1") or 0)
            px = float(m.get("PX") or 0)
            p2 = float(m.get("P2") or 0)
            max_p = max(p1, px, p2)

            if cat == "KAOS":
                kaos_actual[_actual_to_result(actual)] += 1
            if max_p >= 60 and actual == "D":
                high_conf_miss["draw"] += 1
            if max_p >= 60:
                high_conf_miss["total"] += 1

    lines.append(f"\n  {B}{C}⑤ HATA DESENİ ANALİZİ{R}")
    lines.append(_sep())

    # Kayıtlı hata desenleri
    pattern_labels = {
        "banko_fail_home_fav": ("Ev favorisi BANKO yanılma",    False),
        "banko_fail_away_fav": ("Dep favorisi BANKO yanılma",   False),
        "kaos_actual_draw":    ("KAOS → gerçekte beraberlik",   False),
        "high_conf_draw_miss": ("Yüksek güvende X kaçırma",     False),
    }

    any_pattern = False
    for key, (label, _) in pattern_labels.items():
        d = ep.get(key, {})
        n = d.get("total", 0)
        w = d.get("wrong", 0)
        if n < 3: continue
        any_pattern = True
        rate = w / n
        bar  = _bar(rate, 1.0, 8, low_good=True)
        if rate >= 0.55:   verdict = f"{RE}⚠ KRİTİK{R}"
        elif rate >= 0.40: verdict = f"{Y}⚠ DİKKAT{R}"
        else:              verdict = f"{G}✅ Normal{R}"
        lines.append(
            f"  {label:<38} "
            f"%{rate*100:.0f} ({w}/{n})  {bar}  {verdict}")

    # KAOS sonuç dağılımı
    total_kaos = sum(kaos_actual.values())
    if total_kaos > 0:
        lines.append(f"\n  {DM}KAOS tahminlerinde gerçek sonuç dağılımı:{R}")
        for res, cnt in sorted(kaos_actual.items()):
            pct = cnt / total_kaos * 100
            lines.append(f"  {DM}  {res}: {cnt} ({pct:.0f}%){R}")

    if not any_pattern:
        lines.append(f"  {DM}Yeterli veri yok (en az 3 örnek gerekli){R}")

    return lines


# ══════════════════════════════════════════════════════════════════════════════
# BÖLÜM 6 — AKSİYON ÖNERİLERİ
# ══════════════════════════════════════════════════════════════════════════════

def _print_aksiyonlar(mem_data: dict, pred_data: dict,
                      pos_stats: dict, genel_acc: float,
                      buckets: dict, ep: dict) -> None:
    """Aksiyon önerilerini sys.stdout.write + CRLF ile basar."""
    import sys

    def _w(text: str = "") -> None:
        """Satırı CR+LF ile yaz — Pydroid3 uyumlu."""
        sys.stdout.write(text + "\r\n")
        sys.stdout.flush()

    actions = []

    # Zayıf pozisyonlar
    weak_pos = []
    for pos, s in pos_stats.items():
        if s["total"] < 5: continue
        acc = s["correct"] / s["total"]
        if acc < genel_acc - 0.10:
            weak_pos.append(pos)
    if weak_pos:
        actions.append((RE,
            f"Pozisyon {sorted(weak_pos)}'de BANKO esigini +0.05 artir",
            "Tarihsel dogruluk genel ortalamanin >10% altinda"))

    # KAOS hatası
    kaos_ep = ep.get("kaos_actual_draw", {})
    if kaos_ep.get("total", 0) >= 5:
        kaos_rate = kaos_ep.get("wrong", 0) / kaos_ep["total"]
        if kaos_rate >= 0.55:
            actions.append((Y,
                "KAOS esigini 0.03-0.05 artir",
                f"KAOS tahminleri beraberlik kaciriyor (%{kaos_rate*100:.0f})"))

    # Dep BANKO hatası
    dep_ep = ep.get("banko_fail_away_fav", {})
    if dep_ep.get("total", 0) >= 5:
        dep_rate = dep_ep.get("wrong", 0) / dep_ep["total"]
        if dep_rate >= 0.50:
            actions.append((Y,
                "Dep BANKO esigini 0.75'e yukselt",
                f"Mevcut esik altinda %{dep_rate*100:.0f} yanilma"))

    # Fazla güven
    for cat, s in buckets.items():
        if s["total"] < 8: continue
        acc = s["correct"] / s["total"]
        if acc < 0.50:
            actions.append((RE,
                f"{_normalize_pred(cat)} esigini gozden gecir",
                f"Yalnizca %{acc*100:.0f} dogruluk ({s['total']} tahmin)"))

    # Trend
    wh = mem_data.get("weekly_history", [])
    acc_trend = [h["acc"] for h in wh[-4:]
                 if h.get("acc") and h.get("status") == "completed"]
    if len(acc_trend) >= 3 and acc_trend[-1] - acc_trend[0] < -0.08:
        actions.append((RE,
            "Son haftalarda dusus var -- parametreleri gozden gecir",
            f"%{acc_trend[0]*100:.0f} -> %{acc_trend[-1]*100:.0f}"))

    if not actions:
        actions.append((G,
            "Sistem iyi durumda -- parametreleri koru",
            f"Genel dogruluk: %{genel_acc*100:.1f}"))

    _w()
    _w(f"  {B}{C}6. AKSIYON ONERILERI{R}")
    _w(f"  {DM}{'─'*50}{R}")
    for i, (color, action, reason) in enumerate(actions, 1):
        _w(f"  {color}{B}{i}.{R} {action}")
        _w(f"     -- {reason}")
        _w()


# ══════════════════════════════════════════════════════════════════════════════
# ANA GİRİŞ NOKTASI
# ══════════════════════════════════════════════════════════════════════════════

def run_xray(mem_obj) -> None:
    """
    Performans Röntgeni'ni çalıştır.
    mem_obj: STMemory nesnesi
    """
    # Veri yükle
    mem_data  = mem_obj.mem if hasattr(mem_obj, "mem") else {}
    wh        = [h for h in mem_data.get("weekly_history", [])
                 if h.get("status") == "completed"]

    # st_predictions.json yolu
    try:
        from config import PRED_LOG_FILE
        pred_file = PRED_LOG_FILE
    except Exception:
        import os
        pred_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "st_predictions.json")
    pred_data = _load_predictions(pred_file)

    # Genel doğruluk
    ss = mem_data.get("season_summary", {})
    total_m = ss.get("total", 0)
    corr_m  = ss.get("correct", 0)
    genel_acc = corr_m / total_m if total_m else 0.0

    # Pozisyon istatistikleri (Bölüm 6 için önceden hesapla)
    pos_stats = defaultdict(lambda: {"correct": 0, "total": 0})
    for wk, wd in pred_data.items():
        for m in wd.get("matches", []):
            pos = m.get("no")
            actual = m.get("actual","")
            _norm_a = {"1":"H","X":"D","2":"A","0":"D"}
            actual  = _norm_a.get(actual, actual)
            pred_lbl = m.get("pred_label", m.get("pred",""))
            if not actual or actual not in ("H","D","A") or not pos: continue
            ok = _is_correct(pred_lbl, actual)
            if ok is None: continue
            pos_stats[int(pos)]["total"]   += 1
            pos_stats[int(pos)]["correct"] += int(ok)

    # Bahis türü istatistikleri (Bölüm 6 için)
    buckets_raw = defaultdict(lambda: {"correct":0,"total":0})
    for wk, wd in pred_data.items():
        for m in wd.get("matches", []):
            actual   = m.get("actual","")
            _norm_a  = {"1":"H","X":"D","2":"A","0":"D"}
            actual   = _norm_a.get(actual, actual)
            pred_lbl = m.get("pred_label", m.get("pred",""))
            if not actual or actual not in ("H","D","A"): continue
            cat = _normalize_pred(pred_lbl)
            ok  = _is_correct(pred_lbl, actual)
            if ok is None: continue
            buckets_raw[cat]["total"]   += 1
            buckets_raw[cat]["correct"] += int(ok)

    # ── Başlık ──────────────────────────────────────────────────────────────
    print()
    print(f"  {B}{C}{'═'*60}{R}")
    print(f"  {B}{C}  🔬 PERFORMANS RÖNTGENİ — AUGUR ENGINE{R}")
    print(f"  {B}{C}{'═'*60}{R}")
    if not wh and not pred_data:
        print(f"\n  {Y}Henüz yeterli veri yok.{R}")
        print(f"  {DM}En az 1 hafta sonuç girilmeli (Menü 2){R}")
        return

    # ── Bölümler ────────────────────────────────────────────────────────────
    sections = [
        _section_genel(mem_data, wh),
        _section_pozisyon(pred_data, genel_acc),
        _section_bahis_turu(pred_data),
        _section_kalibrasyon(pred_data),
        _section_hata_deseni(mem_data, pred_data),
    ]

    for sec in sections:
        for line in sec:
            for subline in line.split('\n'):
                print(subline)
        print()

    # Aksiyon bölümü direkt print ile
    _print_aksiyonlar(
        mem_data, pred_data,
        dict(pos_stats), genel_acc,
        dict(buckets_raw),
        mem_data.get("error_patterns", {}))

    print(_sep(60, "═"))
    print(f"  {DM}Rapor {len(wh)} tamamlanan hafta ve "
          f"{sum(len(w.get('matches',[])) for w in pred_data.values())} "
          f"maç üzerinden oluşturuldu.{R}")
    print(_sep(60, "═"))
