# -*- coding: utf-8 -*-
"""
Sonuç eşleştirme modülü.
CSV, API-Football ve DOCX kaynaklarından haftalık sonuçları
st_predictions.json ile karşılaştırır ve STMemory'yi günceller.
"""
import os
import re
import json
from difflib import SequenceMatcher

import pandas as pd

from config import LEAGUES, CURRENT_SEASON, ST_SEASON_TAG
from data.downloader import download_league
from input.team_resolver import _normalize


def _auto_results_from_api(mem) -> int:
    """
    API-Football /fixtures ile sonuçları otomatik çek.
    CSV ve sofascore başarısız olunca bu devreye girer.

    Akış:
    1. st_predictions.json'dan maç listesi al
    2. Her maç için fixture ID bul (/fixtures?date=...)
    3. Sonuçları normalize et
    4. mem.enter_results_auto() ile kaydet

    Returns: başarılı eşleşme sayısı
    """
    print("\n  [API-Football] Sonuçlar çekiliyor...")

    try:
        from data.api_football import APIFootball, LEAGUE_ID_MAP, SEASON_MAP
        api = APIFootball()
        if not api.key:
            print("  ✗ API_KEY eksik — api_football_plan.md'deki adımları takip et")
            return 0
    except ImportError:
        print("  ✗ api_football.py bulunamadı")
        return 0

    log           = mem._load_pred_log()
    total_matched = 0

    def _api_wk_key(item):
        _wm = re.match(r'ST(\d+)-(\d+)', item[0])
        return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)

    for week_id, wd in sorted(log.items(), key=_api_wk_key, reverse=True):
        matches    = wd.get("matches", [])
        unresolved = [m for m in matches if not m.get("actual")]
        if not unresolved:
            continue

        print(f"\n  [{week_id}] {len(unresolved)} sonuç bekleniyor...")

        dates = set()
        for m in unresolved:
            from datetime import datetime, timedelta
            today = datetime.now()
            for delta in range(14):
                d = today - timedelta(days=delta)
                if d.weekday() in (5, 6):
                    dates.add(d.strftime("%Y-%m-%d"))

        api_results = {}

        for league_code, league_id in LEAGUE_ID_MAP.items():
            season = SEASON_MAP.get(ST_SEASON_TAG, 2025)
            for date_str in sorted(dates, reverse=True)[:7]:
                fixtures = api.fixtures(league_id, season,
                                        date=date_str, status="FT")
                for f in fixtures:
                    if f["home_score"] is None:
                        continue
                    h, a = f["home_score"], f["away_score"]
                    result = "H" if h > a else ("D" if h == a else "A")
                    key  = f"{f['home'].upper()}_{f['away'].upper()}"
                    api_results[key] = result
                    key2 = f"{f['home_raw'].upper()}_{f['away_raw'].upper()}"
                    api_results[key2] = result

        week_matched = 0
        for m in unresolved:
            home = str(m.get("home", m.get("fd_home", ""))).upper().strip()
            away = str(m.get("away", m.get("fd_away", ""))).upper().strip()
            key  = f"{home}_{away}"

            result = None
            if key in api_results:
                result = api_results[key]
            else:
                home3 = home[:4]; away3 = away[:4]
                for k, v in api_results.items():
                    parts = k.split("_")
                    if len(parts) == 2:
                        if parts[0][:4] == home3 and parts[1][:4] == away3:
                            result = v
                            break

            if result:
                m["actual"] = result
                week_matched  += 1
                total_matched += 1
                ftr_str = {"H":"1 (Ev)", "D":"X (Bera)", "A":"2 (Dep)"}
                print(f"    ✓ #{m.get('no','?')} "
                      f"{m.get('home','?')[:12]} vs "
                      f"{m.get('away','?')[:12]} → {ftr_str.get(result,result)}")

        if week_matched > 0:
            print(f"  [{week_id}] {week_matched} sonuç eşleştirildi")
            log[week_id]["matches"] = matches
            mem._save_pred_log(log)
            mem._learn_from_week(week_id, matches)
            mem.save()

    if total_matched == 0:
        print("  ⚠ Eşleşen sonuç bulunamadı")
        print("  → Maç tarihleri/ligler kontrol edildi")
        print("  → Manuel giriş için Menü 2 kullan")

    return total_matched


def _auto_results_from_csv(mem) -> int:
    """
    Güncel sezon CSV'lerini indir, st_predictions.json ile karşılaştır,
    sonuçları otomatik işle ve modeli güncelle.

    Akış:
    1. Her lig CSV'sini indir (güncel sezon)
    2. Tahmin log'undaki maçları ara (HomeTeam + AwayTeam eşleşmesi)
    3. FTR kolonu doluysa → sonuç mevcut
    4. Tahmin ile karşılaştır → STMemory'yi güncelle

    Döner: işlenen maç sayısı
    """
    print("\n" + "═"*60)
    print("  GÜNCEL SEZON — OTOMATİK SONUÇ KARŞILAŞTIRMA")
    print("═"*60)

    all_dfs = {}
    print("\n  Veriler indiriliyor...")
    for code in LEAGUES.keys():
        df = download_league(code, CURRENT_SEASON)
        if df is not None and "FTR" in df.columns:
            played = df[df["FTR"].notna()].copy()
            if not played.empty:
                all_dfs[code] = played
                print(f"    [{code}] {len(played)} oynanan maç")

    if not all_dfs:
        print("  ! CSV verisi alınamadı. VPN aktif mi?")
        return 0

    all_played = pd.concat(all_dfs.values(), ignore_index=True)

    def _norm(s):
        return _normalize(str(s))

    played_index = {}
    for _, row in all_played.iterrows():
        k = f"{_norm(row['HomeTeam'])}_{_norm(row['AwayTeam'])}"
        played_index[k] = str(row["FTR"])

    log = mem._load_pred_log()
    if not log:
        print("  Tahmin geçmişi boş — önce Menü 1 ile analiz yap.")
        return 0

    total_matched = 0
    total_updated = 0
    already_done  = 0

    def _csv_wk_key(item):
        _wm = re.match(r'ST(\d+)-(\d+)', item[0])
        return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)

    for week_id, wd in sorted(log.items(), key=_csv_wk_key, reverse=True):
        matches = wd.get("matches", [])
        week_changes = 0

        for m in matches:
            if m.get("actual"):
                already_done += 1
                continue

            fd = m.get("fd_match","")
            if " / " in fd:
                fd_h, fd_a = fd.split(" / ", 1)
            else:
                fd_h = m.get("home", "")
                fd_a = m.get("away", "")

            k = f"{_norm(fd_h)}_{_norm(fd_a)}"

            k2 = None
            _fd_raw = m.get("fd_match", "")
            if _fd_raw in ("(varsayilan λ)", "", None) or not fd_h or not fd_a:
                _rh = m.get("home", "")
                _ra = m.get("away", "")
                if _rh and _ra:
                    k2 = f"{_norm(_rh)}_{_norm(_ra)}"

            ftr = played_index.get(k) or (played_index.get(k2) if k2 else None)

            if not ftr:
                best_k, best_sc = None, 0.0
                for pk in played_index:
                    parts = pk.split("_", 1)
                    if len(parts) < 2:
                        continue
                    sh = SequenceMatcher(None, _norm(fd_h), parts[0]).ratio()
                    sa = SequenceMatcher(None, _norm(fd_a), parts[1]).ratio()
                    sc = (sh + sa) / 2
                    if sc > best_sc and sh >= 0.65 and sa >= 0.65:
                        best_sc = sc
                        best_k  = pk
                if best_k:
                    ftr = played_index[best_k]

            if ftr and ftr in ("H","D","A"):
                m["actual"] = ftr
                total_matched += 1
                week_changes  += 1

        if week_changes:
            log[week_id]["matches"] = matches
            mem._save_pred_log(log)
            mem._learn_from_week(week_id, matches)
            total_updated += week_changes
            print(f"\n  [{week_id}] {week_changes} yeni sonuç işlendi")
            mem._print_learning_report(week_id, matches)
            try:
                from output.xlsx_export import refresh_memory_sheet
                refresh_memory_sheet(mem, week_id, matches)
                print(f"  [Excel] st_arsiv.xlsx güncellendi")
            except Exception as _e:
                print(f"  [Excel] Güncelleme atlandı: {_e}")

    mem.save()

    print(f"\n{'─'*60}")
    print(f"  Sonuç: {total_matched} maç CSV'den eşleşti")
    print(f"         {already_done} maç zaten kayıtlıydı")
    if total_matched == 0:
        print("  ! Eşleşme yok — maçlar henüz oynanmamış olabilir")
        sample_preds = []
        for wd in list(log.values())[:1]:
            for m in wd.get("matches",[])[:3]:
                sample_preds.append(m.get("fd_match",""))
        sample_csv = list(played_index.keys())[:3]
        print(f"    Tahmin fd_match : {sample_preds}")
        print(f"    CSV normalize   : {sample_csv}")
    print(f"{'═'*60}")
    return total_matched


def _sync_results_from_docx(weeks: list, mem) -> int:
    """
    DOCX'ten parse edilen haftalık sonuçları st_predictions.json ile eşleştirip yazar.
    Eşleştirme: pozisyon numarası (1-15) + fuzzy takım ismi doğrulaması.
    Döner: yeni yazılan sonuç sayısı.
    """
    def _norm(s):
        s = s.lower()
        for src, dst in [("ş","s"),("ğ","g"),("ü","u"),("ö","o"),
                         ("ç","c"),("ı","i"),("é","e"),("â","a")]:
            s = s.replace(src, dst)
        return re.sub(r'[^a-z0-9]', '', s)

    def _fuzzy(a, b):
        return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

    RESULT_MAP = {"1": "H", "X": "D", "2": "A", "0": "D"}

    log = mem._load_pred_log()
    if not log:
        return 0

    total_written = 0

    for week in weeks:
        if not week.get("matches"):
            continue

        docx_teams = {}
        for dm in week.get("matches", []):
            p = dm.get("pos")
            if p:
                docx_teams[p] = (_norm(dm.get("home", "")),
                                 _norm(dm.get("away", "")))

        target_id  = None
        best_score = 0
        for lid, ld in log.items():
            score = 0
            for lm in ld.get("matches", []):
                pos = lm.get("no")
                if pos in docx_teams:
                    dh, da = docx_teams[pos]
                    lh = _norm(lm.get("home", ""))
                    la = _norm(lm.get("away", ""))
                    if _fuzzy(dh, lh) >= 0.55 and _fuzzy(da, la) >= 0.55:
                        score += 1
            if score > best_score:
                best_score = score
                target_id  = lid

        if best_score < 2:
            continue

        pred_matches = log[target_id].get("matches", [])
        week_changes = 0

        for docx_m in week["matches"]:
            pos    = docx_m.get("pos")
            result = RESULT_MAP.get(docx_m.get("result", ""))
            if not result or not pos:
                continue

            pred = next((p for p in pred_matches if p.get("no") == pos), None)
            if not pred:
                continue

            if pred.get("actual"):
                continue

            dh = docx_m.get("home", "")
            da = docx_m.get("away", "")
            ph = pred.get("home", "")
            pa = pred.get("away", "")

            if dh and da and ph and pa:
                score_h = _fuzzy(dh, ph)
                score_a = _fuzzy(da, pa)
                if score_h < 0.45 and score_a < 0.45:
                    continue

            pred["actual"] = result
            week_changes  += 1
            total_written += 1

        if week_changes:
            log[target_id]["matches"] = pred_matches
            mem._save_pred_log(log)
            mem._learn_from_week(target_id, pred_matches)
            print(f"  [DOCX Sonuç] [{target_id}] {week_changes} maç sonucu işlendi")
            mem._print_learning_report(target_id, pred_matches)
            try:
                from output.xlsx_export import refresh_memory_sheet
                refresh_memory_sheet(mem, target_id, pred_matches)
                print(f"  [Excel] {target_id} güncellendi")
            except Exception:
                pass

    return total_written
