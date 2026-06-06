# -*- coding: utf-8 -*-
"""
lprm_v3.py — LPRM v3: Bağlamsal Güç Modeli
=============================================
Lig sıralaması bazlı form analizi + H2H + güç farkı.

v2'den farkı:
  v2 → Spor Toto liste pozisyonu (rastgele, gürültülü)
  v3 → Lig sıralama bandı (yapısal, anlamlı)

4 Sinyal:
  1. Ev bağlamsal form  — ev takımının kendi bant rakiplerine ev maçları
  2. Dep bağlamsal form — dep takımının kendi bant rakiplerine dep maçları
  3. H2H               — bu iki takımın doğrudan geçmişi (decay'li)
  4. Güç farkı         — anlık puan/maç farkı

Öncelik: Yeni sezon → Eski sezon (2526 → 2425 → 2324)
Ağırlık: Güncel sezon veri miktarına göre otomatik ayarlanır.

Kullanım:
    from model.lprm_v3 import get_lprm_v3_result
    result = get_lprm_v3_result(
        home="Samsunspor", away="Galatasaray",
        league_code="T1", season="2526",
        match_date="2026-05-24",
        past_seasons=["2425","2324"],
    )
    # result: {"lprm_score": float, "lambda_adj_h": float,
    #          "lambda_adj_a": float, "confidence": float, "detail": dict}
"""

from __future__ import annotations

import math
import os
from typing import Optional

import pandas as pd

# ── Sabitler ────────────────────────────────────────────────────────────────
MAX_LAMBDA_ADJ   = 0.10   # ±%10 maksimum lambda düzeltmesi
MIN_MATCHES_FORM = 3      # Bağlamsal form için minimum maç
MIN_MATCHES_H2H  = 2      # H2H sinyali için minimum maç

# Sezon ağırlıkları H2H için (yeni → eski)
H2H_SEASON_DECAY = {0: 0.55, 1: 0.30, 2: 0.15}  # indeks = sezon eskiliği

# Form penceresi: son N maç
FORM_WINDOW = 6


# ── Yardımcı ────────────────────────────────────────────────────────────────

def _norm(name: str) -> str:
    if not name:
        return ""
    return str(name).strip().upper()


def _fuzzy_match(target: str, candidates: list[str]) -> str | None:
    """Basit prefix eşleşmesi. Yeterli değilse None."""
    tn = _norm(target)
    for c in candidates:
        cn = _norm(c)
        if cn == tn:
            return c
        if len(tn) >= 4 and (tn[:4] in cn or cn[:4] in tn):
            return c
    return None


def _result_to_points(result: str, is_home: bool) -> float:
    """FTR → puan (1.0 = galibiyet, 0.5 = beraberlik, 0.0 = mağlubiyet)"""
    if result == "H":
        return 1.0 if is_home else 0.0
    if result == "A":
        return 0.0 if is_home else 1.0
    return 0.5  # "D"


def _wdl_to_score(wins: int, draws: int, losses: int, n: int) -> float:
    """W/D/L → 0-1 normalised form skoru."""
    if n == 0:
        return 0.5
    return (wins + draws * 0.5) / n


# ── Sinyal 1 & 2: Bağlamsal Form ────────────────────────────────────────────

def _contextual_form(
    df: pd.DataFrame,
    team: str,
    opponent_band: str,          # "ÜST" | "ORTA" | "ALT"
    is_home_team: bool,
    match_date: Optional[str],
    standings_fn,                # get_standings callable
    season: str,
    league_code: str,
    form_window: int = FORM_WINDOW,
) -> dict | None:
    """
    Takımın, belirli banttaki rakiplere karşı son N maçını analiz eder.
    is_home_team=True → ev maçları; False → deplasman maçları.

    Returns: {"score":float, "n":int, "W":int, "D":int, "L":int}
             None → yeterli veri yok
    """
    if df is None or df.empty:
        return None

    needed = {"HomeTeam", "AwayTeam", "FTR"}
    if not needed.issubset(df.columns):
        return None

    # Tarih filtresi
    rows = df.dropna(subset=["FTR"]).copy()
    if match_date and "Date" in rows.columns:
        from model.lprm_standings import _build_table  # tarih parse yardımı
        try:
            def _pd(d):
                from datetime import datetime
                for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(str(d).strip(), fmt).date()
                    except ValueError:
                        continue
                return None
            from datetime import datetime
            cutoff = datetime.strptime(match_date, "%Y-%m-%d").date()
            rows["_date"] = rows["Date"].apply(_pd)
            rows = rows[rows["_date"].apply(lambda x: x is None or x < cutoff)]
        except Exception:
            pass

    team_norm = _norm(team)
    all_teams = (list(rows["HomeTeam"].dropna().unique()) +
                 list(rows["AwayTeam"].dropna().unique()))
    matched = _fuzzy_match(team, all_teams)
    if not matched:
        return None

    # Takımın maçlarını filtrele
    if is_home_team:
        team_rows = rows[rows["HomeTeam"].apply(_norm) == _norm(matched)].copy()
    else:
        team_rows = rows[rows["AwayTeam"].apply(_norm) == _norm(matched)].copy()

    if team_rows.empty:
        return None

    # Son N maça kısıt (kronolojik sıra — tarihe göre veya dosya sırasına göre)
    team_rows = team_rows.tail(form_window * 3)  # Bant filtresi için geniş tut

    # Her maçta rakibin bandını bul
    results = []
    for _, row in team_rows.iterrows():
        if is_home_team:
            opponent = str(row.get("AwayTeam", ""))
        else:
            opponent = str(row.get("HomeTeam", ""))

        # Rakibin bandını sıralamayla bul
        try:
            st = standings_fn(league_code, season,
                              match_date=match_date)
            band = _get_band_from_table(st, opponent)
        except Exception:
            band = "?"

        if band != opponent_band:
            continue  # Sadece hedef banttaki rakipleri al

        ftr    = str(row.get("FTR", ""))
        score  = _result_to_points(ftr, is_home=is_home_team)
        results.append(score)

    results = results[-form_window:]  # Son N tanesi
    if len(results) < MIN_MATCHES_FORM:
        return None

    wins   = sum(1 for s in results if abs(s - 1.0) < 1e-9)
    draws  = sum(1 for s in results if abs(s - 0.5) < 1e-9)
    losses = sum(1 for s in results if abs(s) < 1e-9)
    n      = len(results)

    return {
        "score": _wdl_to_score(wins, draws, losses, n),
        "n":     n,
        "W":     wins,
        "D":     draws,
        "L":     losses,
    }


def _get_band_from_table(standings: pd.DataFrame, team: str) -> str:
    """Standings tablosundan takımın bandını al."""
    from model.lprm_standings import get_band
    return get_band(standings, team)


# ── Sinyal 3: H2H ───────────────────────────────────────────────────────────

def _h2h_score(
    home: str,
    away: str,
    seasons: list[str],
    league_code: str,
    match_date: Optional[str],
    get_df_fn,
) -> dict | None:
    """
    H2H: Sezon listesindeki maçlarda bu iki takım karşılaştığında ne olmuş?
    Ağırlık: yeni → eski (H2H_SEASON_DECAY).

    Returns: {"home_score": float, "n": int} | None
    """
    weighted_home = 0.0
    weighted_n    = 0.0
    total_matches = 0

    for i, season in enumerate(seasons):
        decay = H2H_SEASON_DECAY.get(i, 0.0)
        if decay == 0:
            continue

        try:
            df = get_df_fn(league_code, season)
        except Exception:
            continue

        if df is None or df.empty:
            continue

        needed = {"HomeTeam", "AwayTeam", "FTR"}
        if not needed.issubset(df.columns):
            continue

        rows = df.dropna(subset=["FTR"])

        # Tarih filtresi (yalnızca mevcut sezon için)
        if i == 0 and match_date and "Date" in rows.columns:
            try:
                def _pd2(d):
                    from datetime import datetime
                    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                        try:
                            return datetime.strptime(str(d).strip(), fmt).date()
                        except ValueError:
                            continue
                    return None
                from datetime import datetime
                cutoff = datetime.strptime(match_date, "%Y-%m-%d").date()
                rows = rows.copy()
                rows["_date"] = rows["Date"].apply(_pd2)
                rows = rows[rows["_date"].apply(lambda x: x is None or x < cutoff)]
            except Exception:
                pass

        # Bu iki takımın maçlarını bul
        hn = _norm(home)
        an = _norm(away)

        all_teams = (list(df["HomeTeam"].dropna().unique()) +
                     list(df["AwayTeam"].dropna().unique()))
        home_m = _fuzzy_match(home, all_teams)
        away_m = _fuzzy_match(away, all_teams)

        if not home_m or not away_m:
            continue

        h2h = rows[
            ((rows["HomeTeam"].apply(_norm) == _norm(home_m)) &
             (rows["AwayTeam"].apply(_norm) == _norm(away_m))) |
            ((rows["HomeTeam"].apply(_norm) == _norm(away_m)) &
             (rows["AwayTeam"].apply(_norm) == _norm(home_m)))
        ]

        for _, row in h2h.iterrows():
            ftr = str(row.get("FTR", ""))
            is_home = _norm(str(row.get("HomeTeam", ""))) == _norm(home_m)
            score = _result_to_points(ftr, is_home=is_home)
            weighted_home += score * decay
            weighted_n    += decay
            total_matches += 1

    if total_matches < MIN_MATCHES_H2H:
        return None

    home_score = weighted_home / weighted_n if weighted_n > 0 else 0.5

    return {
        "home_score": home_score,
        "n":          total_matches,
    }


# ── Sinyal 4: Güç Farkı ─────────────────────────────────────────────────────

def _power_diff_score(
    home: str,
    away: str,
    standings: pd.DataFrame,
) -> dict | None:
    """
    Anlık puan/maç farkı → normalize skor.
    Pozitif → ev takımı güçlü, negatif → dep takımı güçlü.
    """
    if standings.empty:
        return None

    from model.lprm_standings import get_position

    all_teams = list(standings["Team"].unique())
    home_m = _fuzzy_match(home, all_teams)
    away_m = _fuzzy_match(away, all_teams)

    if not home_m or not away_m:
        return None

    def _ppm(team_name):
        row = standings[standings["Team"] == team_name]
        if row.empty:
            return None
        r = row.iloc[0]
        p = int(r.get("P", 0))
        pts = int(r.get("Pts", 0))
        return pts / p if p > 0 else 0

    h_ppm = _ppm(home_m)
    a_ppm = _ppm(away_m)

    if h_ppm is None or a_ppm is None:
        return None

    # Farkı 0-1 aralığına sıkıştır (max 3 puan/maç fark)
    raw_diff = h_ppm - a_ppm
    norm = max(-1.0, min(1.0, raw_diff / 3.0))

    # 0.5 = eşit güç, >0.5 = ev üstün, <0.5 = dep üstün
    home_score = 0.5 + norm * 0.5

    return {
        "home_score": home_score,
        "h_ppm":      round(h_ppm, 3),
        "a_ppm":      round(a_ppm, 3),
        "diff":       round(raw_diff, 3),
    }


# ── Ağırlık Matrisi ─────────────────────────────────────────────────────────

def _get_weights(n_current: int) -> dict[str, float]:
    """
    Güncel sezon veri miktarına göre ağırlık matrisi.
    n_current = güncel sezondaki toplam maç sayısı (ev + dep form toplam).
    """
    if n_current >= MIN_MATCHES_FORM * 2:
        # Yeterli güncel veri
        return {
            "form_h":  0.30,
            "form_a":  0.20,
            "h2h":     0.25,
            "power":   0.25,
        }
    else:
        # Sezon başı / az veri → geçmiş sezon ağırlığı H2H'de
        return {
            "form_h":  0.15,
            "form_a":  0.10,
            "h2h":     0.45,
            "power":   0.30,
        }


# ── Ana API ─────────────────────────────────────────────────────────────────

def get_lprm_v3_result(
    home:         str,
    away:         str,
    league_code:  str,
    season:       str,
    match_date:   Optional[str] = None,
    past_seasons: list[str]     = None,
) -> dict:
    """
    LPRM v3 ana fonksiyonu.

    Returns:
        {
          "lprm_score":    float,   # -1..+1 (pozitif = ev üstün)
          "lambda_adj_h":  float,   # çarpan (1.0 ± MAX_LAMBDA_ADJ)
          "lambda_adj_a":  float,   # çarpan (1.0 ± MAX_LAMBDA_ADJ)
          "confidence":    float,   # 0..1 (ne kadar sinyal var)
          "detail":        dict,    # debug bilgisi
        }

    Yetersiz veri durumunda nötr değerler döner (lambda_adj = 1.0).
    """
    if past_seasons is None:
        past_seasons = []

    all_seasons = [season] + past_seasons  # öncelik: yeni → eski

    # ── 1. Veri yükleme ──────────────────────────────────────────────────
    try:
        from data.downloader import download_league
        from model.lprm_standings import get_standings, get_band
    except Exception as e:
        return _neutral(f"import hatası: {e}")

    def _get_df(code, s):
        return download_league(code, s)

    def _get_st(code, s, match_date=None):
        return get_standings(code, s, match_date=match_date)

    # Güncel sezon standings
    curr_standings = _get_st(league_code, season, match_date=match_date)

    # Ev ve dep takımı bandı
    home_band = get_band(curr_standings, home) if not curr_standings.empty else "?"
    away_band = get_band(curr_standings, away) if not curr_standings.empty else "?"

    detail = {
        "home_band":  home_band,
        "away_band":  away_band,
        "signals":    {},
        "weights":    {},
        "warnings":   [],
    }

    if home_band == "?" or away_band == "?":
        detail["warnings"].append("Bant tespit edilemedi — veri yetersiz")

    # ── 2. Sinyal 1: Ev bağlamsal form ───────────────────────────────────
    form_h = None
    for s in all_seasons:
        try:
            df = _get_df(league_code, s)
            st_for_band = _get_st(league_code, s, match_date=match_date)
            form_h = _contextual_form(
                df=df, team=home, opponent_band=away_band,
                is_home_team=True, match_date=match_date,
                standings_fn=lambda code, season, match_date=None: _get_st(code, season, match_date),
                season=s, league_code=league_code,
            )
        except Exception:
            form_h = None
        if form_h and form_h["n"] >= MIN_MATCHES_FORM:
            detail["signals"]["form_h"] = form_h
            detail["signals"]["form_h"]["season"] = s
            break

    # ── 3. Sinyal 2: Dep bağlamsal form ──────────────────────────────────
    form_a = None
    for s in all_seasons:
        try:
            df = _get_df(league_code, s)
            form_a = _contextual_form(
                df=df, team=away, opponent_band=home_band,
                is_home_team=False, match_date=match_date,
                standings_fn=lambda code, season, match_date=None: _get_st(code, season, match_date),
                season=s, league_code=league_code,
            )
        except Exception:
            form_a = None
        if form_a and form_a["n"] >= MIN_MATCHES_FORM:
            detail["signals"]["form_a"] = form_a
            detail["signals"]["form_a"]["season"] = s
            break

    # ── 4. Sinyal 3: H2H ──────────────────────────────────────────────────
    h2h = None
    try:
        h2h = _h2h_score(
            home=home, away=away,
            seasons=all_seasons,
            league_code=league_code,
            match_date=match_date,
            get_df_fn=_get_df,
        )
        if h2h:
            detail["signals"]["h2h"] = h2h
    except Exception as e:
        detail["warnings"].append(f"H2H hatası: {e}")

    # ── 5. Sinyal 4: Güç farkı ────────────────────────────────────────────
    power = None
    if not curr_standings.empty:
        try:
            power = _power_diff_score(home, away, curr_standings)
            if power:
                detail["signals"]["power"] = power
        except Exception as e:
            detail["warnings"].append(f"Güç farkı hatası: {e}")

    # ── 6. Ağırlık ve birleştirme ─────────────────────────────────────────
    n_current = (form_h["n"] if form_h else 0) + (form_a["n"] if form_a else 0)
    weights   = _get_weights(n_current)
    detail["weights"] = weights

    composite     = 0.0   # 0 = nötr, pozitif = ev avantajlı
    total_weight  = 0.0
    signal_count  = 0

    def _add(score_raw, w, label):
        nonlocal composite, total_weight, signal_count
        # score_raw: 0..1 (0.5=nötr), composite -1..+1'e çevir
        composite    += (score_raw - 0.5) * 2 * w
        total_weight += w
        signal_count += 1

    if form_h:
        _add(form_h["score"], weights["form_h"], "form_h")
    if form_a:
        # Dep form: dep güçlüyse composite azalır
        _add(1.0 - form_a["score"], weights["form_a"], "form_a")
    if h2h:
        _add(h2h["home_score"], weights["h2h"], "h2h")
    if power:
        _add(power["home_score"], weights["power"], "power")

    if total_weight == 0 or signal_count == 0:
        return _neutral("hiç sinyal yok")

    # Normalize (ağırlıklı ortalama -1..+1)
    lprm_score = composite / total_weight
    lprm_score = max(-1.0, min(1.0, lprm_score))

    # Güven: sinyal sayısı ve veri miktarıyla orantılı
    confidence = min(1.0, signal_count / 4 * min(1.0, n_current / 10))

    # ── 7. Lambda düzeltmesi ──────────────────────────────────────────────
    # lprm_score > 0 → ev üstün → lam_h ↑, lam_a ↓
    # confidence ile ölçekleniyor — az veri → küçük düzeltme
    adj_magnitude = abs(lprm_score) * MAX_LAMBDA_ADJ * confidence

    if lprm_score > 0:
        lambda_adj_h = 1.0 + adj_magnitude
        lambda_adj_a = 1.0 - adj_magnitude * 0.5
    elif lprm_score < 0:
        lambda_adj_h = 1.0 - adj_magnitude * 0.5
        lambda_adj_a = 1.0 + adj_magnitude
    else:
        lambda_adj_h = lambda_adj_a = 1.0

    return {
        "lprm_score":   round(lprm_score, 4),
        "lambda_adj_h": round(lambda_adj_h, 4),
        "lambda_adj_a": round(lambda_adj_a, 4),
        "confidence":   round(confidence, 3),
        "signal_count": signal_count,
        "detail":       detail,
    }


def _neutral(reason: str = "") -> dict:
    """Veri yetersizliğinde nötr sonuç döner — lambda'ya dokunmaz."""
    return {
        "lprm_score":   0.0,
        "lambda_adj_h": 1.0,
        "lambda_adj_a": 1.0,
        "confidence":   0.0,
        "signal_count": 0,
        "detail":       {"warnings": [reason or "nötr"]},
    }
