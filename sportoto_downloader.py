"""
sportoto_downloader.py — Spor Toto Geçmiş Veri İndirici
=========================================================
webapi.sportoto.gov.tr/api/GameMatch/GetGameMatches/?gameRoundId=N

Kapsam:
  2022/2023 Sezonu: ID 315 → 367  (53 hafta)
  2023/2024 Sezonu: ID 368 → 417  (50 hafta)
  2024/2025 Sezonu: ID 418 → 469  (52 hafta)
  2025/2026 Sezonu: ID 470 → 513+ (44+ hafta, devam ediyor)
  Toplam: ~199 hafta × 15 maç = ~2.985 maç

Kullanım:
  python sportoto_downloader.py              # tümünü indir
  python sportoto_downloader.py --season 2324 # sadece 2023/2024
  python sportoto_downloader.py --start 381   # belirli ID'den başla

Çıktı:
  sportoto_data/raw/ID_SEZON_HAFTA.json      # ham JSON
  sportoto_data/matches.csv                  # birleşik CSV
  sportoto_data/summary.json                 # özet
"""

import os, json, time, argparse, csv
import urllib.request, urllib.error
from datetime import datetime

# ─── Sabitler ────────────────────────────────────────────────────────────────
API_BASE    = "https://webapi.sportoto.gov.tr/api/GameMatch/GetGameMatches/"
RESULT_API  = "https://webapi.sportoto.gov.tr/api/GameMatch/GetGameMatches/"
HEADERS     = {
    "User-Agent":    "Mozilla/5.0 (Android 16; Mobile; rv:147.0) Gecko/147.0 Firefox/147.0",
    "Accept":        "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,en-GB;q=0.9",
    "Origin":        "https://www.sportoto.gov.tr",
    "Referer":       "https://www.sportoto.gov.tr/",
}
SLEEP_SEC   = 1.2    # İstek arası bekleme (sunucuya nazik ol)
OUTPUT_DIR  = "sportoto_data"
RAW_DIR     = os.path.join(OUTPUT_DIR, "raw")

# ─── Sezon ID haritası ───────────────────────────────────────────────────────
# Kaynak: gameRoundId=381 → 2023/2024 14. Hafta (doğrulandı)
SEASON_MAP = {
    "2223": {"start": 315, "end": 367, "label": "2022/2023", "total": 53},
    "2324": {"start": 368, "end": 417, "label": "2023/2024", "total": 50},
    "2425": {"start": 418, "end": 469, "label": "2024/2025", "total": 52},
    "2526": {"start": 470, "end": 520, "label": "2025/2026", "total": None},  # devam ediyor
}


def get_season_for_id(gid: int) -> tuple:
    """gameRoundId → (sezon_kodu, hafta_no)"""
    for code, s in SEASON_MAP.items():
        if s["start"] <= gid <= s["end"]:
            return code, gid - s["start"] + 1
    return "unknown", 0


def fetch_week(game_round_id: int) -> dict | None:
    """Tek hafta verisini API'den çek."""
    url = f"{API_BASE}?gameRoundId={game_round_id}"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status == 204:   # No Content — geçersiz ID
                return None
            data = json.loads(r.read().decode("utf-8"))
            if data.get("isSucceed") and data.get("object"):
                return data
            return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print(f"    HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"    Hata: {e}")
        return None


def parse_week(data: dict, game_round_id: int) -> list:
    """
    API yanıtından maç listesi çıkar.
    Her maç: no, homeTeam, awayTeam, date, score, result, isNational
    """
    matches = []
    season_code, week_no = get_season_for_id(game_round_id)

    for i, item in enumerate(data.get("object", []), 1):
        m = item.get("match", {})
        if not m:
            continue

        home = m.get("homeTeam", {})
        away = m.get("awayTeam", {})
        score = m.get("score") or {}

        # Sonuç: fullTimeWin 1=ev, 0=X, 2=dep (None=oynanmadı)
        ftw = m.get("fullTimeWin")
        result = {1: "1", 0: "X", 2: "2"}.get(ftw, "")

        # Skor
        home_sc = score.get("homeRegular")
        away_sc = score.get("awayRegular")
        score_str = f"{home_sc}-{away_sc}" if home_sc is not None else ""

        matches.append({
            "game_round_id": game_round_id,
            "season":        season_code,
            "week_no":       week_no,
            "pos":           i,
            "home":          home.get("mediumName") or home.get("name", ""),
            "away":          away.get("mediumName") or away.get("name", ""),
            "home_id":       home.get("id"),
            "away_id":       away.get("id"),
            "is_national":   home.get("isNational", False),
            "tournament_id": m.get("tournamentId"),
            "date":          m.get("date", "")[:10],
            "time":          m.get("date", "")[11:16],
            "score":         score_str,
            "result":        result,
            "home_ht":       score.get("homeHalfTime"),
            "away_ht":       score.get("awayHalfTime"),
        })
    return matches


def run(season_filter: str = None, start_id: int = None, end_id: int = None):
    """Ana indirme döngüsü."""
    os.makedirs(RAW_DIR, exist_ok=True)

    # ID aralığı belirle
    if start_id and end_id:
        id_range = range(start_id, end_id + 1)
    elif season_filter and season_filter in SEASON_MAP:
        s = SEASON_MAP[season_filter]
        id_range = range(s["start"], s["end"] + 1)
    else:
        # Tümü
        all_start = min(s["start"] for s in SEASON_MAP.values())
        all_end   = max(s["end"]   for s in SEASON_MAP.values())
        id_range  = range(all_start, all_end + 1)

    all_matches = []
    ok = skip = fail = 0

    print(f"\n  Spor Toto Geçmiş Veri İndirici")
    print(f"  ID aralığı: {id_range.start} → {id_range.stop - 1}  ({len(id_range)} hafta)")
    print(f"  {'─'*50}")

    for gid in id_range:
        season_code, week_no = get_season_for_id(gid)
        raw_file = os.path.join(RAW_DIR, f"{gid}_{season_code}_w{week_no:02d}.json")

        # Cache kontrolü
        if os.path.exists(raw_file):
            with open(raw_file, encoding="utf-8") as f:
                data = json.load(f)
            matches = parse_week(data, gid)
            all_matches.extend(matches)
            season_lbl = SEASON_MAP.get(season_code, {}).get("label", season_code)
            print(f"  ⊙ ID {gid:>4} | {season_lbl} {week_no:>2}. Hafta | {len(matches):>2} maç (cache)")
            skip += 1
            continue

        # İndir
        print(f"  ↓ ID {gid:>4} | {season_code} {week_no:>2}. Hafta ...", end="", flush=True)
        data = fetch_week(gid)

        if data is None:
            print(" ✗ (boş/geçersiz)")
            fail += 1
            time.sleep(SLEEP_SEC)
            continue

        # Ham JSON kaydet
        with open(raw_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        matches = parse_week(data, gid)
        all_matches.extend(matches)

        game_round_name = ""
        if data.get("object"):
            game_round_name = data["object"][0].get("gameRoundName", "")

        print(f" {len(matches):>2} maç ✓  [{game_round_name}]")
        ok += 1
        time.sleep(SLEEP_SEC)

    # CSV çıktısı
    if all_matches:
        csv_path = os.path.join(OUTPUT_DIR, "matches.csv")
        fieldnames = list(all_matches[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(all_matches)

        # Özet
        summary = {
            "indirildi":     datetime.now().isoformat(),
            "toplam_hafta":  ok + skip,
            "toplam_mac":    len(all_matches),
            "lig_mac":       sum(1 for m in all_matches if not m["is_national"]),
            "milli_mac":     sum(1 for m in all_matches if m["is_national"]),
            "sezonlar":      {
                code: sum(1 for m in all_matches if m["season"] == code)
                for code in SEASON_MAP
            }
        }
        with open(os.path.join(OUTPUT_DIR, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"\n  {'─'*50}")
        print(f"  ✅ Tamamlandı!")
        print(f"     İndirilen : {ok} hafta")
        print(f"     Cache     : {skip} hafta")
        print(f"     Başarısız : {fail} hafta")
        print(f"     Toplam maç: {len(all_matches)}")
        print(f"     Lig maç   : {summary['lig_mac']}")
        print(f"     Milli maç : {summary['milli_mac']}")
        print(f"     CSV çıktı : {csv_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Spor Toto geçmiş veri indirici")
    ap.add_argument("--season",  help="Sezon kodu: 2223 / 2324 / 2425 / 2526")
    ap.add_argument("--start",   type=int, help="Başlangıç gameRoundId")
    ap.add_argument("--end",     type=int, help="Bitiş gameRoundId")
    args = ap.parse_args()

    run(
        season_filter = args.season,
        start_id      = args.start,
        end_id        = args.end,
    )
