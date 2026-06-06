# -*- coding: utf-8 -*-
"""
lprm_standings.py — Haftalık Lig Sıralaması Hesaplayıcı
=========================================================
football-data.co.uk CSV'sinden tarih sıralı maç verisiyle
kümülatif puan tablosu üretir.

Öncelik: Güncel sezon (2526) → Önceki sezon (2425) → Daha öncesi (2324)
Cache: fd_cache/lprm_standings_{sezon}_{kod}.pkl

Kullanım:
    from model.lprm_standings import get_standings, get_band
    st = get_standings("E0", "2526", match_date="2026-05-01")
    band_h = get_band(st, "Arsenal")    # "ÜST" | "ORTA" | "ALT"
"""

from __future__ import annotations

import os
import pickle
import hashlib
from datetime import datetime, date, timedelta
from typing import Optional

import pandas as pd

# ── Sabitler ────────────────────────────────────────────────────────────────
_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_D = os.path.join(_DIR, "fd_cache")

BAND_THRESHOLDS = {
    # (toplam takım, üst sınır, alt sınır) → üst <= x < alt arası ORTA
    20: (5,  15),   # Premier League, La Liga, Serie A, Süper Lig, Ligue 1
    18: (4,  13),   # Bundesliga
    16: (4,  12),   # Eredivisie, Scottish
    14: (3,  10),   # Küçük ligler
}
DEFAULT_THRESHOLDS = (5, 15)

CACHE_TTL_HOURS = 48   # Güncel sezon cache süresi


# ── Yardımcı ────────────────────────────────────────────────────────────────

def _cache_path(code: str, season: str) -> str:
    return os.path.join(CACHE_D, f"lprm_standings_{season}_{code}.pkl")


def _save_cache(path: str, data: object) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "wb") as f:
            pickle.dump(data, f)
    except (OSError, IOError):
        pass


def _load_cache(path: str, ttl_h: float = CACHE_TTL_HOURS) -> object | None:
    if not os.path.exists(path):
        return None
    age_h = (datetime.now().timestamp() - os.path.getmtime(path)) / 3600
    if age_h > ttl_h:
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _normalize_team(name: str) -> str:
    """Takım adını normalize et — fuzzy match için."""
    if not name:
        return ""
    return str(name).strip().upper()


def _team_size(df: pd.DataFrame) -> int:
    """CSV'den toplam takım sayısını çıkar."""
    teams = set()
    if "HomeTeam" in df.columns:
        teams |= set(df["HomeTeam"].dropna().unique())
    if "AwayTeam" in df.columns:
        teams |= set(df["AwayTeam"].dropna().unique())
    n = len(teams)
    return n if n >= 8 else 20


def _band_limits(n_teams: int) -> tuple[int, int]:
    """Lig büyüklüğüne göre üst/alt sınır döner."""
    for size, (top_end, bot_start) in BAND_THRESHOLDS.items():
        if n_teams <= size + 1:
            return (top_end, bot_start)
    return DEFAULT_THRESHOLDS


# ── Sıralama Hesabı ─────────────────────────────────────────────────────────

def _build_table(df: pd.DataFrame,
                 before_date: Optional[str] = None) -> pd.DataFrame:
    """
    CSV'deki maçlardan kümülatif puan tablosu üretir.

    Sütunlar: Team, P, W, D, L, GF, GA, GD, Pts, Pos
    before_date: "YYYY-MM-DD" — bu tarihten önceki maçları kullan.
    """
    needed = {"HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}
    if not needed.issubset(df.columns):
        return pd.DataFrame()

    rows = df.dropna(subset=["FTHG", "FTAG", "FTR"]).copy()

    # Tarih filtresi
    if before_date and "Date" in rows.columns:
        try:
            # football-data: "DD/MM/YY" veya "DD/MM/YYYY"
            def _parse(d):
                for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(str(d).strip(), fmt).date()
                    except ValueError:
                        continue
                return None

            rows["_date"] = rows["Date"].apply(_parse)
            cutoff = datetime.strptime(before_date, "%Y-%m-%d").date()
            # None dönen satırlar (parse edilemeyen tarih) dahil edilir —
            # tarihi bilinmeyen maç büyük ihtimalle geçmişte, güvenli dahil et.
            rows = rows[rows["_date"].apply(lambda x: x is None or x < cutoff)]
        except Exception:
            pass  # Tarih parse edilemezse filtre atla

    if rows.empty:
        return pd.DataFrame()

    # Sıralama tablosu
    table: dict[str, dict] = {}

    def _add(team, gf, ga, result):
        if team not in table:
            table[team] = {"P": 0, "W": 0, "D": 0, "L": 0,
                           "GF": 0, "GA": 0, "Pts": 0}
        t = table[team]
        t["P"]  += 1
        t["GF"] += int(gf)
        t["GA"] += int(ga)
        if result == "H":
            t["W"]   += 1
            t["Pts"] += 3
        elif result == "D":
            t["D"]   += 1
            t["Pts"] += 1
        else:
            t["L"] += 1

    for _, row in rows.iterrows():
        fthg = row["FTHG"]
        ftag = row["FTAG"]
        ftr  = row["FTR"]
        _add(str(row["HomeTeam"]).strip(), fthg, ftag, ftr)
        away_res = "H" if ftr == "A" else ("D" if ftr == "D" else "A")
        _add(str(row["AwayTeam"]).strip(), ftag, fthg, away_res)

    if not table:
        return pd.DataFrame()

    t_df = pd.DataFrame(table).T.reset_index().rename(columns={"index": "Team"})
    t_df["GD"]  = t_df["GF"] - t_df["GA"]
    t_df        = t_df.sort_values(["Pts", "GD", "GF"],
                                   ascending=[False, False, False])
    t_df        = t_df.reset_index(drop=True)
    t_df["Pos"] = t_df.index + 1
    return t_df


# ── Ana API ─────────────────────────────────────────────────────────────────

def get_standings(league_code: str,
                  season: str,
                  match_date: Optional[str] = None,
                  force_refresh: bool = False) -> pd.DataFrame:
    """
    Verilen lig ve sezon için haftalık sıralama tablosu döner.

    league_code: "E0", "T1", "SP1", ...
    season:      "2526", "2425", ...
    match_date:  "YYYY-MM-DD" — bu tarihten önceki maçları kullan.
                 None → tüm sezon.
    force_refresh: True → cache'i yoksay.

    Returns:
        pd.DataFrame: Team | P | W | D | L | GF | GA | GD | Pts | Pos
        Boş DataFrame → veri yok.
    """
    cache_key = f"{league_code}_{season}_{match_date or 'full'}"
    h = hashlib.md5(cache_key.encode()).hexdigest()[:8]
    cp = _cache_path(league_code, f"{season}_{h}")

    if not force_refresh:
        cached = _load_cache(cp)
        if cached is not None:
            return cached

    # CSV'yi yükle
    try:
        from data.downloader import download_league
        df = download_league(league_code, season)
    except Exception:
        df = None

    if df is None or df.empty:
        return pd.DataFrame()

    table = _build_table(df, before_date=match_date)
    if not table.empty:
        _save_cache(cp, table)

    return table


def get_band(standings: pd.DataFrame,
             team_name: str) -> str:
    """
    Takımın lig bandını döner: "ÜST" | "ORTA" | "ALT" | "?"

    standings: get_standings() çıktısı.
    team_name: CSV'deki tam takım adı.
    """
    if standings.empty or not team_name:
        return "?"

    n_teams = len(standings)
    top_end, bot_start = _band_limits(n_teams)

    # Normalize eşleştirme
    norm_target = _normalize_team(team_name)
    standings["_norm"] = standings["Team"].apply(_normalize_team)

    row = standings[standings["_norm"] == norm_target]

    if row.empty:
        # Fuzzy fallback: içerik eşleşmesi
        row = standings[standings["_norm"].str.contains(
            norm_target[:6], na=False, regex=False)]

    if row.empty:
        return "?"

    pos = int(row.iloc[0]["Pos"])

    if pos <= top_end:
        return "ÜST"
    if pos >= bot_start:
        return "ALT"
    return "ORTA"


def get_position(standings: pd.DataFrame, team_name: str) -> int | None:
    """Takımın sıralama pozisyonunu döner (1=lider). None = bulunamadı."""
    if standings.empty or not team_name:
        return None

    norm_target = _normalize_team(team_name)
    standings["_norm"] = standings["Team"].apply(_normalize_team)

    row = standings[standings["_norm"] == norm_target]
    if row.empty:
        row = standings[standings["_norm"].str.contains(
            norm_target[:6], na=False, regex=False)]
    if row.empty:
        return None

    return int(row.iloc[0]["Pos"])


def clear_standings_cache(league_code: str | None = None) -> int:
    """Standings cache dosyalarını sil. league_code=None → hepsini sil."""
    if not os.path.exists(CACHE_D):
        return 0
    deleted = 0
    for fn in os.listdir(CACHE_D):
        if not fn.startswith("lprm_standings_"):
            continue
        if league_code and league_code not in fn:
            continue
        try:
            os.remove(os.path.join(CACHE_D, fn))
            deleted += 1
        except OSError:
            pass
    return deleted


def refresh_current_season(season: str, verbose: bool = True) -> dict[str, int]:
    """
    Güncel sezonun tüm lig standings cache'ini yeniler.
    Menü 6a tarafından çağrılır.

    Returns: {league_code: maç_sayısı}
    """
    try:
        from config import LEAGUES
    except ImportError:
        LEAGUES = {
            "T1":"Süper Lig","E0":"Premier League","D1":"Bundesliga",
            "I1":"Serie A","SP1":"La Liga","F1":"Ligue 1",
        }

    results = {}
    today = date.today().strftime("%Y-%m-%d")

    if verbose:
        print(f"\n  Güncel sezon ({season}) standings güncelleniyor...")

    for code, name in LEAGUES.items():
        if verbose:
            print(f"    [{code}] {name}...", end=" ", flush=True)
        try:
            table = get_standings(code, season,
                                  match_date=today,
                                  force_refresh=True)
            n = len(table)
            results[code] = n
            if verbose:
                print(f"✓ {n} takım")
        except Exception as e:
            results[code] = 0
            if verbose:
                print(f"✗ {e}")

    if verbose:
        total = sum(v for v in results.values() if v > 0)
        ok    = sum(1 for v in results.values() if v > 0)
        print(f"\n  Tamamlandı: {ok}/{len(LEAGUES)} lig, toplam {total} takım")

    return results
