# -*- coding: utf-8 -*-
from config import *
from data.downloader import _detect_odds_cols
import sys, re, io, os, json, math, time, warnings
from datetime import datetime
from difflib import SequenceMatcher
import requests
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")

def _odds_range(o: float) -> str:
    """Oran değerini aralık etiketine çevir."""
    if o < 1.40:  return "cok_favori"   # 1.01-1.39
    if o < 1.70:  return "favori"       # 1.40-1.69
    if o < 2.20:  return "hafif_fav"    # 1.70-2.19
    if o < 3.00:  return "denge"        # 2.20-2.99
    return "outsider"                    # 3.00+

def _rank_zone(rank_pct: float) -> str:
    """Sıralama yüzdesini bölge etiketine çevir."""
    if rank_pct <= 0.25:  return "zirve"   # ilk %25
    if rank_pct <= 0.55:  return "orta"    # orta
    if rank_pct <= 0.80:  return "alt"     # alt orta
    return "dusme"                          # son %20

def _make_profile_key(o1, ox, o2, venue: str,
                      home_rank_pct: float, away_rank_pct: float) -> str:
    """
    3-boyutlu profil anahtarı:
      oran_aralığı + mekan + ev_bölgesi + dep_bölgesi
    Örnek: "favori_ev_zirve_dusme"
    """
    odds_label = _odds_range(float(o1))
    h_zone = _rank_zone(home_rank_pct)
    a_zone = _rank_zone(away_rank_pct)
    return f"{odds_label}_{venue}_{h_zone}_{a_zone}"


def build_odds_history(current_data: dict, past_data: dict) -> dict:
    """
    İki katmanlı tarihsel veritabanı:
    1. Oran bin DB  — "{o1}-{ox}-{o2}" → H/D/A sayımı
    2. Profil DB    — "oran_mekan_ev_dep" → H/D/A sayımı
    """
    from data.downloader import _detect_odds_cols
    bins     = {}
    profiles = {}

    def _add(df, weight=1.0, standings_map=None, league=None):
        h_col, d_col, a_col = _detect_odds_cols(df, league)
        if not h_col:
            return
        played = df[df["FTR"].notna()].copy() if "FTR" in df.columns else df.iloc[:0]
        if played.empty:
            return

        for _, row in played.iterrows():
            try:
                o1  = round(float(row[h_col]), 1)
                ox  = round(float(row[d_col]), 1)
                o2  = round(float(row[a_col]), 1)
                ftr = str(row["FTR"])
                if not all(1.01 <= x <= 50 for x in [o1, ox, o2]):
                    continue
                if ftr not in ("H","D","A"):
                    continue

                # ── 1. Oran bin ──────────────────────────────────
                bk = f"{o1}-{ox}-{o2}"
                if bk not in bins:
                    bins[bk] = {"H":0.0,"D":0.0,"A":0.0,"n":0.0}
                bins[bk][ftr] = bins[bk].get(ftr,0) + weight
                bins[bk]["n"] += weight

                # ── 2. Profil bin ────────────────────────────────
                if standings_map is not None:
                    ht = str(row.get("HomeTeam",""))
                    at = str(row.get("AwayTeam",""))
                    h_info = standings_map.get(ht, {})
                    a_info = standings_map.get(at, {})
                    if h_info and a_info:
                        pk = _make_profile_key(
                            o1, ox, o2, "ev",
                            h_info.get("rank_pct", 0.5),
                            a_info.get("rank_pct", 0.5)
                        )
                        if pk not in profiles:
                            profiles[pk] = {"H":0.0,"D":0.0,"A":0.0,"n":0.0}
                        profiles[pk][ftr] = profiles[pk].get(ftr,0) + weight
                        profiles[pk]["n"] += weight

            except (ValueError, TypeError, KeyError, ZeroDivisionError):
                continue

    # Güncel sezon (standings var)
    for code, ld in current_data.items():
        if ld.get("df") is not None:
            _add(ld["df"], 1.0, ld.get("standings"), league=code)

    # Geçmiş sezonlar — asimptotik ağırlık (Katman 6)
    # Sezon başında geçmiş sezon daha değerli, sezon ortasında azalır
    try:
        from config import get_past_season_weight, st_week_id
        _cur_week = st_week_id()  # "ST42-2526" → 42
        _week_no  = int(_cur_week.split("-")[0].replace("ST","")) if _cur_week else 20
    except Exception:
        _week_no  = 20  # fallback: sezon ortası
        get_past_season_weight = lambda tag, w: PAST_SEASON_WEIGHTS.get(tag, 0.0)

    for code, seasons in past_data.items():
        for season, df in seasons.items():
            w = get_past_season_weight(season, _week_no)
            _add(df, w, None, league=code)

    total_b = sum(v["n"] for v in bins.values())
    total_p = sum(v["n"] for v in profiles.values())
    print(f"  OranDB  : {len(bins):,} bin | {total_b:,.0f} ağırlıklı maç")
    print(f"  ProfilDB: {len(profiles):,} profil | {total_p:,.0f} ağırlıklı maç")
    return {"bins": bins, "profiles": profiles}


def lookup_odds_history(o1, ox, o2, history: dict, min_n: float = 8.0):
    """Oran bin'inden H/D/A olasılığı dondur."""
    if None in (o1, ox, o2) or not history:
        return None
    bins = history.get("bins", history)  # eski format uyumluluğu
    k = f"{round(float(o1),1)}-{round(float(ox),1)}-{round(float(o2),1)}"
    e = bins.get(k)
    if e and e["n"] >= min_n:
        return (e["H"]/e["n"], e["D"]/e["n"], e["A"]/e["n"])
    # Fuzzy ±0.2
    best = None
    for hk, e in bins.items():
        if e["n"] < min_n:
            continue
        try:
            a = [float(x) for x in k.split("-")]
            b = [float(x) for x in hk.split("-")]
            if max(abs(x-y) for x,y in zip(a,b)) <= 0.2:
                if best is None or e["n"] > best["n"]:
                    best = e
        except (ValueError, TypeError, KeyError, ZeroDivisionError):
            continue
    if best:
        return (best["H"]/best["n"], best["D"]/best["n"], best["A"]/best["n"])
    return None


def lookup_profile(o1, ox, o2, venue: str,
                   home_rank_pct: float, away_rank_pct: float,
                   history: dict, min_n: float = 5.0) -> dict:
    """
    Profil DB'den 3-boyutlu istatistik ara.
    Döner: {"p1":f,"px":f,"p2":f,"n":int,"label":str} veya None
    """
    if None in (o1, ox, o2) or not history:
        return None
    profiles = history.get("profiles", {})
    if not profiles:
        return None

    pk = _make_profile_key(o1, ox, o2, venue, home_rank_pct, away_rank_pct)
    e  = profiles.get(pk)

    # Tam eşleşme
    if e and e["n"] >= min_n:
        return {
            "p1": e["H"]/e["n"], "px": e["D"]/e["n"], "p2": e["A"]/e["n"],
            "n":  int(e["n"]),   "label": pk,
        }

    # Gevşetilmiş arama: oran aralığı aynı, sıralama bölgesi ±1
    odds_label = _odds_range(float(o1))
    h_z = _rank_zone(home_rank_pct)
    a_z = _rank_zone(away_rank_pct)
    prefix = f"{odds_label}_{venue}"

    best   = None
    best_k = None
    for k, e in profiles.items():
        if e["n"] < min_n:
            continue
        if k.startswith(prefix):
            if best is None:
                best   = e
                best_k = k
            elif e["n"] > best["n"]:
                best   = e
                best_k = k

    if best and best_k:
        return {
            "p1": best["H"]/best["n"], "px": best["D"]/best["n"],
            "p2": best["A"]/best["n"], "n":  int(best["n"]),
            "label": f"{best_k}(~)",
        }
    return None



# ═══════════════════════════════════════════════════════════════