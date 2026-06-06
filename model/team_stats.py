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

# ═══════════════════════════════════════════════════════════════
# BÖLÜM 5 — PROXY xG & TAKIM İSTATİSTİKLERİ
# ═══════════════════════════════════════════════════════════════

def calc_xg(df: pd.DataFrame) -> pd.DataFrame:
    """Şut kolonu varsa proxy xG üret, yoksa ham gol kullan."""
    if all(c in df.columns for c in ["HS","AS","HST","AST"]):
        for col in ["HS","AS","HST","AST"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["xG_home"] = df["HST"]*0.33 + (df["HS"]-df["HST"]).clip(0)*0.09
        df["xG_away"] = df["AST"]*0.33 + (df["AS"]-df["AST"]).clip(0)*0.09
    else:
        df["xG_home"] = df["FTHG"]
        df["xG_away"] = df["FTAG"]
    return df


def _date_decay_weights(matches: pd.DataFrame,
                        decay_k: float = None) -> np.ndarray:
    """
    Tarih bazlı üstel decay ağırlıkları.

    Her maç için weight_i = exp(-k * gün_farkı)
    k=0.007 → ~100 günlük yarı-ömür.
    Tarih kolonu yoksa eşit ağırlık döner.

    Akademik referans:
    Dixon & Coles (1997) "Modelling Association Football Scores"
    — zaman weighting φ(t) = exp(-ξ·t) ile λ'nın daha doğru tahmin edilmesi.
    """
    if decay_k is None:
        decay_k = CFG.get("time_decay_k", 0.007)
    n = len(matches)
    if n == 0:
        return np.ones(0)

    if "Date" not in matches.columns:
        return np.ones(n) / n

    try:
        dates = pd.to_datetime(matches["Date"], dayfirst=True, errors="coerce")
        today = pd.Timestamp.now()
        days_ago = (today - dates).dt.days.fillna(180).clip(lower=0).values
        weights  = np.exp(-decay_k * days_ago.astype(float))
        w_sum    = weights.sum()
        if w_sum < 1e-12:
            return np.ones(n) / n
        return weights / w_sum
    except Exception:
        return np.ones(n) / n


def _team_venue_stats(matches: pd.DataFrame,
                      gf_col: str, ga_col: str,
                      xgf_col: str, xga_col: str,
                      ftr_win: str, lg_avg: float,
                      lg_xg: float, form_n: int,
                      season_phase_weight: float = 1.0) -> dict:
    """
    Belirli mekan (ev/dep) için istatistik hesapla.
    season_phase_weight: sezon sonu yaklaşınca son maçlara daha fazla ağırlık.

    Tarih bazlı üstel decay (k=0.007):
    Eski gol ortalamaları yerine son maçlara exp(-k*gün) ağırlığı atar.
    Bu sayede kadro değişiklikleri, teknik direktör değişiklikleri ve form
    dalgalanmaları model tarafından daha doğru yansıtılır.
    """
    n = len(matches)
    if n == 0:
        return None

    gf  = pd.to_numeric(matches[gf_col],  errors="coerce").fillna(0).values
    ga  = pd.to_numeric(matches[ga_col],  errors="coerce").fillna(0).values
    xgf = pd.to_numeric(matches[xgf_col], errors="coerce").fillna(0).values
    xga = pd.to_numeric(matches[xga_col], errors="coerce").fillna(0).values

    # ── Tarih bazlı üstel decay ağırlıkları ─────────────────────
    decay_w = _date_decay_weights(matches)   # normalize, sum=1

    # Ağırlıklı ortalamalar (decay uygulanmış)
    gf_avg  = float(np.dot(gf,  decay_w))
    ga_avg  = float(np.dot(ga,  decay_w))
    xgf_avg = float(np.dot(xgf, decay_w))
    xga_avg = float(np.dot(xga, decay_w))

    # Sezon evresi ek ağırlığı (eski yaklaşım — decay üstüne ek düzeltme)
    if season_phase_weight > 1.0:
        phase_n = min(form_n * 2, n)
        recent  = matches.tail(phase_n)
        r_dw    = _date_decay_weights(recent)
        r_gf    = pd.to_numeric(recent[gf_col],  errors="coerce").fillna(0).values
        r_ga    = pd.to_numeric(recent[ga_col],  errors="coerce").fillna(0).values
        r_xgf   = pd.to_numeric(recent[xgf_col], errors="coerce").fillna(0).values
        r_xga   = pd.to_numeric(recent[xga_col], errors="coerce").fillna(0).values
        # Ek ağırlık: phase_weight - 1 kadar son maçları öne çıkar
        boost = season_phase_weight - 1.0
        gf_avg  = (gf_avg  + boost * float(np.dot(r_gf,  r_dw))) / (1.0 + boost)
        ga_avg  = (ga_avg  + boost * float(np.dot(r_ga,  r_dw))) / (1.0 + boost)
        xgf_avg = (xgf_avg + boost * float(np.dot(r_xgf, r_dw))) / (1.0 + boost)
        xga_avg = (xga_avg + boost * float(np.dot(r_xga, r_dw))) / (1.0 + boost)

    # Son form_n maç rolling — üstel decay (exponential)
    # α = 0.75: her önceki maç 0.75x daha az ağırlıklı
    # Örnek 5 maç: [0.31, 0.24, 0.19, 0.14, 0.12] (en son en ağır)
    recent = matches.tail(form_n)
    r_n    = max(len(recent), 1)

    ALPHA = 0.75   # decay faktörü — 0.75 = makul, 0.9 = daha hafızalı
    if len(recent) >= 2:
        # Üstel ağırlıklar: w_i = α^(n-1-i), normalize
        w_arr = np.array([ALPHA ** (len(recent)-1-i) for i in range(len(recent))],
                         dtype=float)
        w_arr /= w_arr.sum()

        gf_vals = pd.to_numeric(recent[gf_col], errors="coerce").fillna(0).values
        ga_vals = pd.to_numeric(recent[ga_col], errors="coerce").fillna(0).values
        roll5_gf = float(np.dot(gf_vals, w_arr))
        roll5_ga = float(np.dot(ga_vals, w_arr))

        if "FTR" in recent.columns:
            ftr_vals = recent["FTR"].values
            pts_vals = np.array([3 if f==ftr_win else (1 if f=="D" else 0)
                                   for f in ftr_vals], dtype=float)
            roll5_pts = float(np.dot(pts_vals, w_arr))
            win_vals  = np.array([1.0 if f==ftr_win else 0.0 for f in ftr_vals])
            roll5_win = float(np.dot(win_vals, w_arr))
        else:
            roll5_pts = 1.0
            roll5_win = 0.33
    else:
        roll5_gf  = float(pd.to_numeric(recent[gf_col], errors="coerce").fillna(0).mean()) if len(recent) else gf_avg
        roll5_ga  = float(pd.to_numeric(recent[ga_col], errors="coerce").fillna(0).mean()) if len(recent) else ga_avg
        roll5_pts = float(
            ((recent["FTR"] == ftr_win).sum() * 3 +
             (recent["FTR"] == "D").sum()) / r_n
        ) if "FTR" in recent.columns else 1.0
        roll5_win = float((recent["FTR"] == ftr_win).mean()) \
            if "FTR" in recent.columns and len(recent) else 0.33

    return {
        "att":       gf_avg  / (lg_avg + 1e-9),
        "def":       ga_avg  / (lg_avg + 1e-9),
        "xg_att":    xgf_avg / (lg_xg  + 1e-9),
        "xg_def":    xga_avg / (lg_xg  + 1e-9),
        "roll5_gf":  roll5_gf,
        "roll5_ga":  roll5_ga,
        "roll5_pts": roll5_pts,
        "roll5_win": roll5_win,
        "xg_for":    max(0.2, xgf_avg),
        "xg_ag":     max(0.2, xga_avg),
        "n":         n,
    }


def _season_phase_weight(df: pd.DataFrame) -> float:
    """
    Sezon evresine göre ağırlık faktörü hesapla.
    Son 8 haftada (toplam maç sayısının %25'i) form daha kritik.
    """
    if "Date" not in df.columns:
        return 1.0
    try:
        n_matches = len(df[df["FTR"].notna()]) if "FTR" in df.columns else len(df)
        # Bir takımın sezon başına düşen ortalama maç sayısı
        n_per_team = n_matches / 20  # 20 takım ortalama
        if n_per_team >= 28:   # sezon sonu yakın
            return 1.6
        elif n_per_team >= 22: # sezon ortası-sonu
            return 1.3
        else:
            return 1.0
    except (ValueError, TypeError, KeyError, AttributeError):
        return 1.0


def get_h2h_stats(home: str, away: str,
                  df: pd.DataFrame, last_n: int = 5) -> dict:
    """
    İki takım arasındaki son last_n karşılaşmadan H2H istatistik çıkar.

    İyileştirmeler:
      - Üstel decay: yakın tarihli maçlar daha ağırlıklı
      - Venue split: ev+dep ayrı, gerçek ev sahası avantajı
      - Draw oranı: beraberlik eğilimi ayrıca ölçülür

    Döner: {"h_wins": f, "draws": f, "a_wins": f,
             "h_goals_avg": f, "a_goals_avg": f,
             "draw_rate": f, "venue_h_wins": f,
             "n": n}
    Eşleşme yoksa None.
    """
    if df is None or "FTR" not in df.columns:
        return None

    try:
        h2h = df[
            ((df["HomeTeam"] == home) & (df["AwayTeam"] == away)) |
            ((df["HomeTeam"] == away) & (df["AwayTeam"] == home))
        ].copy()

        if "Date" in df.columns:
            h2h = h2h.sort_values("Date")

        h2h = h2h[h2h["FTR"].notna()].tail(last_n)
        n   = len(h2h)

        if n == 0:
            return None

        # Üstel decay ağırlıkları — yakın maç daha önemli
        ALPHA   = 0.75
        weights = np.array([ALPHA ** (n-1-i) for i in range(n)], dtype=float)
        weights /= weights.sum()

        h_wins = 0.0; a_wins = 0.0; draws = 0.0
        h_goals = 0.0; a_goals = 0.0
        # Ev sahası ayrımı: bu maçta gerçekten ev sahibi olarak kaç kazandı?
        venue_h_wins = 0.0
        home_h2h_n   = 0

        for i, (_, row) in enumerate(h2h.iterrows()):
            w = weights[i]
            ftr = row["FTR"]
            if row["HomeTeam"] == home:
                # home gerçekten ev sahibi
                hg = float(row.get("FTHG", 0))
                ag = float(row.get("FTAG", 0))
                if ftr == "H":   h_wins += w; venue_h_wins += 1
                elif ftr == "D": draws  += w
                else:            a_wins += w
                home_h2h_n += 1
            else:
                # home deplasman
                hg = float(row.get("FTAG", 0))
                ag = float(row.get("FTHG", 0))
                if ftr == "A":   h_wins += w
                elif ftr == "D": draws  += w
                else:            a_wins += w
            h_goals += hg * w
            a_goals += ag * w

        # Ev sahası H2H kazanma oranı (sadece home gerçekten ev sahibiyken)
        venue_h_rate = venue_h_wins / home_h2h_n if home_h2h_n else h_wins

        return {
            "h_wins":       h_wins,       # ağırlıklı kazanma oranı
            "draws":        draws,         # ağırlıklı beraberlik oranı
            "a_wins":       a_wins,        # ağırlıklı kayıp oranı
            "h_goals_avg":  h_goals,       # ağırlıklı ortalama gol
            "a_goals_avg":  a_goals,
            "draw_rate":    draws,         # beraberlik eğilimi (0-1)
            "venue_h_wins": venue_h_rate,  # gerçek ev sahası avantajı
            "n":            n,
        }
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def build_team_stats(df: pd.DataFrame) -> tuple:
    """
    Her takım için EV/DEPLASMAN ayrı istatistik + rolling form + sezon evresi.
    Döner: (stats_dict, league_avg_goals, standings_dict)
    """
    lg_avg = (df["FTHG"].mean() + df["FTAG"].mean()) / 2
    lg_xg  = (df["xG_home"].mean() + df["xG_away"].mean()) / 2
    teams  = set(df["HomeTeam"]) | set(df["AwayTeam"])
    stats  = {}
    pts_dict = {}
    fg     = CFG["form_games"]
    spw    = _season_phase_weight(df)   # sezon evresi ağırlığı

    if spw > 1.0:
        print(f"  [Sezon evresi] Ağırlık={spw:.1f}x (son maçlar daha kritik)")

    for t in teams:
        hm = df[df["HomeTeam"] == t].copy()
        am = df[df["AwayTeam"] == t].copy()
        n  = len(hm) + len(am)
        if n == 0:
            continue

        home_s = _team_venue_stats(
            hm, "FTHG","FTAG","xG_home","xG_away","H",
            lg_avg, lg_xg, fg, spw
        )
        away_s = _team_venue_stats(
            am, "FTAG","FTHG","xG_away","xG_home","A",
            lg_avg, lg_xg, fg, spw
        )

        g_sc = hm["FTHG"].sum() + am["FTAG"].sum()
        g_cn = hm["FTAG"].sum() + am["FTHG"].sum()
        x_sc = hm["xG_home"].sum() + am["xG_away"].sum()
        x_cn = hm["xG_away"].sum() + am["xG_home"].sum()

        all_m = pd.concat([hm, am]).sort_values("Date") \
            if "Date" in df.columns else pd.concat([hm, am])
        recent = all_m.tail(fg)
        r_n    = max(len(recent), 1)
        gen_form = float(
            ((recent["FTR"] == "H") & (recent["HomeTeam"] == t) |
             (recent["FTR"] == "A") & (recent["AwayTeam"] == t)).sum() * 3 +
            (recent["FTR"] == "D").sum()
        ) / r_n if "FTR" in recent.columns else 1.0

        overall = {
            "att":    (g_sc/n) / (lg_avg + 1e-9),
            "def":    (g_cn/n) / (lg_avg + 1e-9),
            "xg_att": (x_sc/n) / (lg_xg  + 1e-9),
            "xg_def": (x_cn/n) / (lg_xg  + 1e-9),
            "form":   gen_form / (lg_avg  + 1e-9),
            "n":      n,
        }

        if "FTR" in df.columns:
            completed_hm = hm[hm["FTR"].notna()]
            completed_am = am[am["FTR"].notna()]
            pts = (
                (completed_hm["FTR"] == "H").sum() * 3 +
                (completed_hm["FTR"] == "D").sum() +
                (completed_am["FTR"] == "A").sum() * 3 +
                (completed_am["FTR"] == "D").sum()
            )
            gd = int(g_sc - g_cn)
            pts_dict[t] = {"pts": int(pts), "gd": gd, "n": n}

        stats[t] = {
            "home":    home_s or overall,
            "away":    away_s or overall,
            "overall": overall,
        }

    standings = {}
    if pts_dict:
        sorted_teams = sorted(
            pts_dict.items(),
            key=lambda x: (x[1]["pts"], x[1]["gd"]),
            reverse=True
        )
        total = len(sorted_teams)
        for rank, (t, info) in enumerate(sorted_teams, 1):
            standings[t] = {
                "rank":     rank,
                "rank_pct": rank / total,
                "pts":      info["pts"],
                "n":        info["n"],
            }

    return stats, lg_avg, standings
