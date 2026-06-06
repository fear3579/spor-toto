# -*- coding: utf-8 -*-
"""
API-Football v3 — Otomatik sonuç çekici.
https://www.api-football.com/documentation-v3

Endpoint: GET /fixtures?date=YYYY-MM-DD
Header:   x-apisports-key: {API_KEY}
"""
from config import *
from input.team_resolver import _normalize
import json, time, os
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import requests

# API anahtarı gerekli: https://www.api-football.com adresinden ücretsiz hesap açın.
# Termux: export APIFOOTBALL_KEY="api_anahtariniz"
# Windows/Linux: .env dosyasına APIFOOTBALL_KEY=api_anahtariniz ekleyin
APIFOOTBALL_KEY  = os.environ.get("APIFOOTBALL_KEY", "")
if not APIFOOTBALL_KEY:
    import warnings
    warnings.warn(
        "APIFOOTBALL_KEY ortam değişkeni tanımlı değil — "
        "sofascore.py (otomatik sonuç çekici) çalışmayacak.\n"
        "  Termux: export APIFOOTBALL_KEY='anahtariniz'\n"
        "  https://www.api-football.com (ücretsiz plan yeterli)",
        RuntimeWarning, stacklevel=2
    )
APIFOOTBALL_BASE = "https://v3.football.api-sports.io"
APIFOOTBALL_HDR  = {
    "x-apisports-key": APIFOOTBALL_KEY,
    "Accept":          "application/json",
}
APIFOOTBALL_TIMEOUT = 12

# İlgilenilen lig ID'leri (API-Football)
# Haftalık listede çıkabilecek tüm ligler
LEAGUE_IDS = {
    203,   # Süper Lig (Türkiye)
    39,    # Premier League
    78,    # Bundesliga
    135,   # Serie A
    140,   # La Liga
    61,    # Ligue 1
    2,     # Champions League
    3,     # Europa League
}


def _fetch_day(date_str: str) -> list:
    """
    Belirli tarih için API-Football'dan maç listesi çek.
    date_str: "2026-04-19"
    Döner: [{"home", "away", "hs", "as", "status"}, ...]
    """
    url = f"{APIFOOTBALL_BASE}/fixtures"
    params = {"date": date_str, "timezone": "Europe/Istanbul"}
    try:
        r = requests.get(url, headers=APIFOOTBALL_HDR,
                         params=params, timeout=APIFOOTBALL_TIMEOUT)
        if r.status_code != 200:
            print(f"  [API-Football] {date_str}: HTTP {r.status_code}")
            return []

        data     = r.json()
        errors   = data.get("errors", {})
        if errors:
            print(f"  [API-Football] Hata: {errors}")
            return []

        fixtures = data.get("response", [])
        result   = []

        for fix in fixtures:
            league_id = fix.get("league", {}).get("id", 0)
            if league_id not in LEAGUE_IDS:
                continue

            fixture  = fix.get("fixture", {})
            goals    = fix.get("goals", {})
            teams    = fix.get("teams", {})
            status   = fixture.get("status", {}).get("short", "")

            # Durum: FT/AET/PEN = bitti, NS = başlamadı, 1H/2H/HT = devam
            if status in ("FT", "AET", "PEN", "AWD", "WO"):
                st = "finished"
            elif status in ("1H", "2H", "HT", "ET", "BT", "P", "SUSP", "INT", "LIVE"):
                st = "inprogress"
            else:
                st = "notstarted"

            hs  = goals.get("home")
            as_ = goals.get("away")

            result.append({
                "id":       fixture.get("id"),
                "home":     teams.get("home", {}).get("name", ""),
                "away":     teams.get("away", {}).get("name", ""),
                "hs":       hs,
                "as":       as_,
                "status":   st,
                "league":   fix.get("league", {}).get("name", ""),
                "league_id": league_id,
            })

        return result

    except (OSError, IOError, ValueError, TypeError, RuntimeError) as e:
        print(f"  [API-Football] {date_str} hata: {e}")
        return []


def _score_to_result(hs, as_) -> str:
    """Skor → 1/X/2"""
    if hs is None or as_ is None:
        return None
    if int(hs) > int(as_):  return "1"
    if int(hs) < int(as_):  return "2"
    return "X"


def _match_score(name_a: str, name_b: str) -> float:
    return SequenceMatcher(
        None, _normalize(name_a), _normalize(name_b)
    ).ratio()


def fetch_results(matches: list,
                  date_from: str = None,
                  date_to:   str = None) -> dict:
    """
    Haftalık tahmin listesi için API-Football'dan sonuç çek.

    matches   : [{"no", "mac", "home", "away"}, ...]
    date_from : "2026-04-17"
    date_to   : "2026-04-21"

    Döner: {no: {"result":"1/X/2", "score":"2-1",
                  "status":"finished", "conf":0.95}}
    """
    if date_from is None:
        # Ücretsiz plan: sadece son 3 gün erişilebilir
        date_from = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    if date_to is None:
        date_to   = datetime.now().strftime("%Y-%m-%d")

    all_events = []
    cur = datetime.strptime(date_from, "%Y-%m-%d")
    end = datetime.strptime(date_to,   "%Y-%m-%d")

    print(f"  API-Football: {date_from} → {date_to}...")
    while cur <= end:
        ds     = cur.strftime("%Y-%m-%d")
        events = _fetch_day(ds)
        all_events.extend(events)
        cur += timedelta(days=1)
        time.sleep(0.25)

    # Sadece ilgili liglerdeki maçlar
    print(f"  Bulunan: {len(all_events)} maç (ilgili liglerde)")

    results = {}
    THRESHOLD = 0.72

    for m in matches:
        no    = m["no"]
        mhome = m.get("home", "")
        maway = m.get("away", "")
        if not mhome and "-" in m.get("mac",""):
            parts = m["mac"].split("-", 1)
            mhome, maway = parts[0].strip(), parts[1].strip()

        best_score = 0.0
        best_event = None

        for ev in all_events:
            sh = (_match_score(mhome, ev["home"]) +
                  _match_score(maway, ev["away"])) / 2
            # Ters de dene (deplasman/ev karışık olabilir)
            sa = (_match_score(mhome, ev["away"]) +
                  _match_score(maway, ev["home"])) / 2
            score = max(sh, sa)
            if score > best_score:
                best_score = score
                best_event = ev

        if best_event and best_score >= THRESHOLD:
            status = best_event["status"]
            hs     = best_event["hs"]
            as_    = best_event["as"]
            res    = _score_to_result(hs, as_) if status == "finished" else None
            results[no] = {
                "result":  res,
                "score":   f"{hs}-{as_}" if hs is not None else "?-?",
                "status":  status,
                "ss_home": best_event["home"],
                "ss_away": best_event["away"],
                "league":  best_event.get("league",""),
                "conf":    round(best_score, 2),
            }

    done    = sum(1 for v in results.values() if v["result"])
    pending = sum(1 for v in results.values() if v["status"] != "finished")
    missed  = len(matches) - len(results)
    print(f"  Eşleşti: {done} bitti | {pending} devam | {missed} bulunamadı")

    return results


# Geriye dönük uyumluluk için alias
fetch_results_sofascore = fetch_results
