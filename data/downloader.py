import io
# -*- coding: utf-8 -*-
from config import *
from input.team_resolver import _normalize
import sys, re, io, os, json, math, time, warnings
from datetime import datetime
from difflib import SequenceMatcher
import requests
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")

def _detect_odds_cols(df, league: str = None):
    """En iyi dolu oran setini bul — lig bazlı öncelikle."""
    sets_to_try = ODDS_COL_SETS_BY_LEAGUE.get(league, ODDS_COL_SETS) \
                  if league else ODDS_COL_SETS
    for h, d, a in sets_to_try:
        if all(c in df.columns for c in [h, d, a]):
            valid = df[h].notna().sum() if hasattr(df, '__len__') else 1
            if valid > 0:
                return h, d, a
    for h, d, a in ODDS_COL_SETS:
        if all(c in df.columns for c in [h, d, a]):
            return h, d, a
    return None, None, None


def _clean_df(df):
    for col in ["FTHG","FTAG","HTHG","HTAG","HS","AS","HST","AST"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    h, d, a = _detect_odds_cols(df)
    if h:
        for col in [h, d, a]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        df = df.sort_values("Date")
    return df.dropna(subset=["HomeTeam","AwayTeam"]).copy()


def _cache_path(name):
    os.makedirs(FD_CACHE_DIR, exist_ok=True)
    return os.path.join(FD_CACHE_DIR, name)


def _cache_fresh(path, ttl_h):
    if not os.path.exists(path):
        return False
    return (time.time() - os.path.getmtime(path)) / 3600 < ttl_h


def _save_pkl(df, path):
    # FIX #5: Atomik yazma — crash durumunda cache bozulmasını önler.
    # ml_engine.save() ile tutarlı (.tmp → os.replace).
    try:
        import pickle
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(df, f)
        os.replace(tmp, path)
    except (OSError, IOError, ValueError, TypeError, requests.exceptions.RequestException):
        # .tmp dosyası kaldıysa temizle
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def _load_pkl(path):
    try:
        import pickle
        with open(path, "rb") as f:
            return pickle.load(f)
    except (OSError, IOError, ValueError, TypeError, requests.exceptions.RequestException):
        return None


def _normalize_extra_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extra lig CSV kolonlarını standart formata çevir.
    - Res  → FTR
    - FTR değerleri: 1/X/2 → H/D/A
    - HomeTeam / AwayTeam kolonları zaten var
    """
    renames = {}
    if "Res" in df.columns and "FTR" not in df.columns:
        renames["Res"] = "FTR"
    df = df.rename(columns=renames)
    if "FTR" in df.columns:
        ftr_map = {"1": "H", "X": "D", "2": "A",
                   "H": "H", "D": "D", "A": "A"}
        df["FTR"] = df["FTR"].map(ftr_map)
    return df


def _filter_by_season(df: pd.DataFrame, season: str) -> pd.DataFrame:
    """
    Sezon kodu (örn: "2526") → tarih aralığına göre filtrele.

    Avrupa sezonu (T1/E0/D1...): Ağu Y1 → Tem Y2
    Yaz ligleri (SWE/NOR/FIN/JPN/CHN): Mart Y1 → Kasım Y1

    Strateji: önce Avrupa aralığını dene, boşsa Y1 takvim yılını al.
    """
    if "Date" not in df.columns:
        return df
    y1 = int("20" + season[:2])
    y2 = int("20" + season[2:])

    # Avrupa sezonu: Ağu Y1 → Tem Y2
    start_eu = pd.Timestamp(f"{y1}-08-01")
    end_eu   = pd.Timestamp(f"{y2}-07-31")
    filtered = df[(df["Date"] >= start_eu) & (df["Date"] <= end_eu)].copy()

    # Yaz ligleri için Y1 takvim yılı (Mart–Kasım Y1)
    if len(filtered) == 0:
        start_alt = pd.Timestamp(f"{y1}-01-01")
        end_alt   = pd.Timestamp(f"{y1}-12-31")
        filtered = df[(df["Date"] >= start_alt) & (df["Date"] <= end_alt)].copy()

    return filtered


def _download_extra_league(code: str, season: str = CURRENT_SEASON) -> "pd.DataFrame | None":
    """
    football-data.co.uk/new_leagues/{code}.csv indir.
    Tek CSV'de tüm tarihsel veri — cache'te all olarak saklanır,
    sezon filtresi uygulanır.
    """
    cache_pkl = _cache_path(f"{code}_all.pkl")
    cache_csv = _cache_path(f"{code}_all.csv")

    # Pickle cache (72 saat TTL — extra ligler daha seyrek güncellenir)
    if _cache_fresh(cache_pkl, FD_EXTRA_TTL_H):
        df_all = _load_pkl(cache_pkl)
        if df_all is not None:
            df_season = _filter_by_season(df_all, season)
            played = df_season.dropna(subset=["FTHG","FTAG"]).copy() \
                     if "FTHG" in df_season.columns else df_season
            h, _, _ = _detect_odds_cols(played, code)
            age = (time.time() - os.path.getmtime(cache_pkl)) / 3600
            print(f"    [{code}/{season}] cache({age:.0f}sa) "
                  f"{len(played)} mac" + (f" | {h}" if h else ""))
            return played if len(played) > 0 else None

    # CSV yedek
    if os.path.exists(cache_csv) and not _cache_fresh(cache_pkl, FD_EXTRA_TTL_H):
        try:
            df_all = pd.read_csv(cache_csv, encoding="utf-8", on_bad_lines="skip")
            df_all = _normalize_extra_df(df_all)
            df_all = _clean_df(df_all)
            if len(df_all) > 0:
                _save_pkl(df_all, cache_pkl)
                df_season = _filter_by_season(df_all, season)
                played = df_season.dropna(subset=["FTHG","FTAG"]).copy() \
                         if "FTHG" in df_season.columns else df_season
                print(f"    [{code}/{season}] CSV yedekten {len(played)} mac")
                return played if len(played) > 0 else None
        except (OSError, IOError, ValueError, TypeError, requests.exceptions.RequestException):
            pass

    # İnternetten indir
    url = FD_URL_EXTRA.format(code=code)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        df_all = pd.read_csv(io.BytesIO(r.content), encoding="latin1", on_bad_lines="skip")
        if not all(c in df_all.columns for c in ["HomeTeam","AwayTeam"]):
            print(f"    [HATA] {code}: HomeTeam/AwayTeam kolonu yok")
            return None
        df_all = _normalize_extra_df(df_all)
        df_all = _clean_df(df_all)
        # Tüm veriyi cache'e yaz
        _save_pkl(df_all, cache_pkl)
        try:
            df_all.to_csv(cache_csv, index=False, encoding="utf-8")
        except (OSError, IOError):
            pass
        # Sezon filtresi
        df_season = _filter_by_season(df_all, season)
        played = df_season.dropna(subset=["FTHG","FTAG"]).copy() \
                 if "FTHG" in df_season.columns else df_season
        h, _, _ = _detect_odds_cols(played, code)
        print(f"    [{code}/{season}] {len(played)} mac indirildi"
              + (f" | oran:{h}" if h else ""))
        return played if len(played) > 0 else None
    except (OSError, IOError, ValueError, TypeError, RuntimeError,
            requests.exceptions.RequestException) as e:
        print(f"    [HATA] {code} extra: {e}")
        return None


def download_league(code: str, season: str = CURRENT_SEASON) -> "pd.DataFrame | None":
    """
    Football-data CSV indir.
    Extra ligler (SWE/NOR/JPN/FIN/...) → new_leagues URL, tek CSV
    Ana ligler (T1/E0/D1/...)          → mmz4281 URL, sezon CSV
    """
    # ── Extra lig yönlendirmesi ──────────────────────────────────
    if code in EXTRA_LEAGUES:
        return _download_extra_league(code, season)

    # ── Ana lig mantığı (değişmeden) ────────────────────────────
    cache_pkl = _cache_path(f"{code}_{season}.pkl")
    cache_csv = _cache_path(f"{code}_{season}.csv")

    if _cache_fresh(cache_pkl, FD_CACHE_TTL_H):
        df = _load_pkl(cache_pkl)
        if df is not None:
            h, _, _ = _detect_odds_cols(df)
            age = (time.time() - os.path.getmtime(cache_pkl)) / 3600
            print(f"    [{code}/{season}] cache({age:.0f}sa) "
                  f"{len(df)} mac" + (f" | {h}" if h else ""))
            return df

    if os.path.exists(cache_csv) and not _cache_fresh(cache_pkl, FD_CACHE_TTL_H):
        try:
            df = pd.read_csv(cache_csv, encoding="utf-8", on_bad_lines="skip")
            df = _clean_df(df)
            if len(df) > 0:
                h, _, _ = _detect_odds_cols(df)
                print(f"    [{code}/{season}] CSV yedekten yüklendi "
                      f"{len(df)} mac" + (f" | {h}" if h else ""))
                _save_pkl(df, cache_pkl)
                return df
        except (OSError, IOError, ValueError, TypeError, requests.exceptions.RequestException):
            pass

    url = FD_URL.format(season=season, code=code)
    try:
        # Sezon başında bazı ligler 404 verebilir — 2 deneme
        _last_exc = None
        r = None
        for _attempt in range(2):
            try:
                r = requests.get(url, headers=HEADERS, timeout=15)
                if r.status_code == 404 and _attempt == 0:
                    import time as _time; _time.sleep(2)
                    continue
                r.raise_for_status()
                break
            except requests.exceptions.RequestException as _e:
                _last_exc = _e
                if _attempt == 0:
                    import time as _time; _time.sleep(2)
        if r is None or not r.ok:
            raise (_last_exc or Exception("fetch failed"))
        df = pd.read_csv(io.BytesIO(r.content), encoding="latin1", on_bad_lines="skip")
        if not all(c in df.columns for c in ["HomeTeam","AwayTeam"]):
            return None
        df = _clean_df(df)
        played = df.dropna(subset=["FTHG","FTAG"]).copy()
        h, _, _ = _detect_odds_cols(played)
        print(f"    [{code}/{season}] {len(played)} mac"
              + (f" | oran:{h}" if h else ""))
        _save_pkl(played, cache_pkl)
        try:
            played.to_csv(cache_csv, index=False, encoding="utf-8")
        except (OSError, IOError, ValueError, TypeError, requests.exceptions.RequestException):
            pass
        return played
    except (OSError, IOError, ValueError, TypeError, RuntimeError,
            requests.exceptions.RequestException) as e:
        print(f"    [HATA] {code}/{season}: {e}")
        return None


def download_fixtures():
    """fixtures.csv indir — yaklaşan maçlar + açılış oranları."""
    cache = _cache_path("fixtures.pkl")

    today_wd   = datetime.now().weekday()
    cache_date = (datetime.fromtimestamp(os.path.getmtime(cache)).date()
                  if os.path.exists(cache) else None)

    is_list_day   = (today_wd == 4)
    is_result_day = (today_wd == 1)
    is_update_day = is_list_day or is_result_day

    if _cache_fresh(cache, FD_FIX_TTL_H):
        if not (is_update_day and cache_date < datetime.now().date()):
            df = _load_pkl(cache)
            if df is not None:
                h, _, _ = _detect_odds_cols(df)
                age = (time.time() - os.path.getmtime(cache)) / 3600
                next_ev = "Salı (sonuçlar)" if today_wd < 1 or today_wd > 4 \
                          else "Cuma (yeni liste)" if 1 < today_wd < 4 \
                          else "Perşembe" if today_wd == 3 else "bekle"
                print(f"  Fikstur cache ({age:.0f}sa): {len(df)} mac"
                      + (f" | oran:{h}" if h else "")
                      + f"  [Sonraki: {next_ev}]")
                return df

    print("  fixtures.csv indiriliyor...")
    try:
        r = requests.get(FD_FIXTURES_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.BytesIO(r.content), encoding="latin1", on_bad_lines="skip")
        df = _clean_df(df)
        h, _, _ = _detect_odds_cols(df)
        reason = "(yeni liste)" if is_list_day else \
                 "(sonuç günü)" if is_result_day else ""
        print(f"  fixtures.csv {reason}: {len(df)} mac"
              + (f" | oran:{h}" if h else " | oran yok"))
        _save_pkl(df, cache)
        return df
    except (OSError, IOError, ValueError, TypeError, RuntimeError,
            requests.exceptions.RequestException) as e:
        print(f"  fixtures.csv hatasi: {e}")
        return None


def download_past_seasons(codes: list) -> dict:
    """Geçmiş sezonları indir (oran DB için)."""
    result = {}
    for code in codes:
        result[code] = {}
        # Extra ligler tek CSV'de tüm tarih içeriyor — 3 sezon ayrı çekilmez
        if code in EXTRA_LEAGUES:
            for season in PAST_SEASONS:
                df = download_league(code, season)
                if df is not None and len(df) > 0:
                    result[code][season] = df
        else:
            for season in PAST_SEASONS:
                df = download_league(code, season)
                if df is not None:
                    result[code][season] = df
            current_csv = _cache_path(f"{code}_{CURRENT_SEASON}.csv")
            if os.path.exists(current_csv):
                try:
                    df_cur = pd.read_csv(current_csv, encoding="utf-8", on_bad_lines="skip")
                    df_cur = _clean_df(df_cur)
                    if len(df_cur) > 0:
                        result[code][f"{CURRENT_SEASON}_live"] = df_cur
                except (OSError, IOError, ValueError, TypeError,
                        requests.exceptions.RequestException):
                    pass
    return result


def accumulate_current_season(code: str, df: pd.DataFrame):
    """Güncel sezon CSV'sini kümülatif arşiv dosyasına ekle."""
    if df is None or df.empty:
        return
    # Extra ligler için arşiv mantığı farklı — all.csv zaten tüm tarih
    if code in EXTRA_LEAGUES:
        return

    arsiv_csv = _cache_path(f"{code}_{CURRENT_SEASON}_arsiv.csv")
    try:
        if os.path.exists(arsiv_csv):
            existing = pd.read_csv(arsiv_csv, encoding="utf-8", on_bad_lines="skip")
            combined = pd.concat([existing, df], ignore_index=True)
            key_cols  = [c for c in ["Date","HomeTeam","AwayTeam"]
                         if c in combined.columns]
            if key_cols:
                combined = combined.drop_duplicates(subset=key_cols, keep="last")
            combined.to_csv(arsiv_csv, index=False, encoding="utf-8")
            new_count = len(combined) - len(existing)
            if new_count > 0:
                print(f"    [{code}] Arşive {new_count} yeni maç eklendi "
                      f"(toplam {len(combined)})")
        else:
            df.to_csv(arsiv_csv, index=False, encoding="utf-8")
            print(f"    [{code}] Arşiv oluşturuldu ({len(df)} maç)")
    except (OSError, IOError, ValueError, TypeError, RuntimeError,
            requests.exceptions.RequestException):
        pass


def _get_row_odds(row, league: str = None) -> tuple:
    """Bir fixtures satırından geçerli oran üçlüsünü bul."""
    import math as _math
    sets_to_try = ODDS_COL_SETS_BY_LEAGUE.get(league, ODDS_COL_SETS) \
                  if league else ODDS_COL_SETS
    for col_sets in [sets_to_try, ODDS_COL_SETS]:
        for h_c, d_c, a_c in col_sets:
            try:
                if not all(c in row.index for c in [h_c, d_c, a_c]):
                    continue
                o1 = float(row[h_c])
                ox = float(row[d_c])
                o2 = float(row[a_c])
                if all(not _math.isnan(x) and 1.01 <= x <= 50
                       for x in [o1, ox, o2]):
                    return round(o1, 2), round(ox, 2), round(o2, 2)
            except (ValueError, TypeError, KeyError):
                continue
    return None, None, None


def merge_fixture_odds(matches: list, fixtures_df,
                       league_data: dict = None) -> list:
    """fixtures.csv oranlarını maç listesiyle birleştir."""
    if fixtures_df is None or (hasattr(fixtures_df,"empty") and fixtures_df.empty):
        return matches

    fix_index = {}
    for idx, row in fixtures_df.iterrows():
        rh = _normalize(str(row.get("HomeTeam","")))
        ra = _normalize(str(row.get("AwayTeam","")))
        if rh and ra:
            fix_index[(rh, ra)] = row

    enriched = 0
    no_odds  = 0

    for m in matches:
        if all(m["odds"].get(k) is not None for k in ["1","X","2"]):
            continue

        candidates = []
        fd_h = m.get("fd_home","")
        fd_a = m.get("fd_away","")
        if fd_h and fd_a:
            candidates.append((_normalize(fd_h), _normalize(fd_a), "fd"))
        candidates.append((_normalize(m["home"]), _normalize(m["away"]), "ocr"))

        best_row = None
        best_src = ""

        for hn, an, src in candidates:
            if (hn, an) in fix_index:
                best_row = fix_index[(hn, an)]
                best_src = src + "_tam"
                break
            best_sc = 0.0
            for (rh, ra), row in fix_index.items():
                sh = SequenceMatcher(None, hn, rh).ratio()
                sa = SequenceMatcher(None, an, ra).ratio()
                if sh >= 0.70 and sa >= 0.70:
                    sc = (sh + sa) / 2
                    if sc > best_sc:
                        best_sc = sc
                        best_row = row
                        best_src = src + f"_fuzzy({sc:.2f})"
            if best_row is not None:
                break

        if best_row is not None:
            league = m.get("league", None)
            o1, ox, o2 = _get_row_odds(best_row, league)
            if o1 is not None:
                m["odds"]["1"] = o1
                m["odds"]["X"] = ox
                m["odds"]["2"] = o2
                enriched += 1
                # ── Açılış oranı (delta hesabı için) ────────
                # B365H = açılış, B365CH = kapanış
                try:
                    o1_open = best_row.get("B365H") or best_row.get("AvgH")
                    ox_open = best_row.get("B365D") or best_row.get("AvgD")
                    o2_open = best_row.get("B365A") or best_row.get("AvgA")
                    if o1_open is not None:
                        m["odds_open"] = {
                            "1": float(o1_open),
                            "X": float(ox_open) if ox_open else None,
                            "2": float(o2_open) if o2_open else None,
                        }
                except (ValueError, TypeError, AttributeError):
                    pass
            else:
                no_odds += 1

    total = len(matches)
    if enriched:
        print(f"  {enriched}/{total} maca fixtures orani eklendi ✓")

    missing = [m for m in matches
               if not all(m["odds"].get(k) is not None for k in ["1","X","2"])]
    if missing:
        print(f"  \u26a0 Oran eksik ({len(missing)} maç):")
        for m in missing:
            fd_h = m.get("fd_home", m["home"])
            fd_a = m.get("fd_away", m["away"])
            print(f"    #{m['no']:>2} {m['home'][:20]}-{m['away'][:20]}")
            print(f"         → Oranı elle ekle: "
                  f"{m['home'][:18]} vs {m['away'][:18]}")
    return matches
