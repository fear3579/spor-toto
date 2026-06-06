# -*- coding: utf-8 -*-
from config import *
from input.team_resolver import _normalize
from data.downloader import _cache_path, _save_pkl, _cache_fresh, _load_pkl
import sys, re, io, os, json, math, time, warnings, logging
from datetime import datetime
from difflib import SequenceMatcher
import requests
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# BÖLÜM 6 — CLUBELO + POISSON LAMBDA
# ═══════════════════════════════════════════════════════════════

_CLUBELO_MAP = {
    "Karagumruk":          "Fatih Karaguemruek",
    "Fatih Karagumruk":    "Fatih Karaguemruek",
    "Kayserispor":         "Kayseri",
    "Gaziantep":           "Gaziantep FK",
    "Istanbul Basaksehir": "Basaksehir",
    "Caykur Rizespor":     "Rizespor",
    "Ein Frankfurt":       "Frankfurt",
    "Bayern Munich":       "Bayern",
    "FC Koln":             "Koeln",
    "Man United":          "Man United",
    "Man City":            "Man City",
    "Nott'm Forest":       "Nott'm Forest",
    "AC Milan":            "Milan",
    "Verona":              "Hellas Verona",
    "Paris SG":            "Paris SG",
    "Ath Madrid":          "Atletico",
    "Ath Bilbao":          "Bilbao",
    "Espanol":             "Espanyol",
}

_clubelo_cache: dict = {}


def load_clubelo() -> dict:
    """ClubElo API'den güncel ELO puanlarını indir. 48sa cache."""
    global _clubelo_cache
    if _clubelo_cache:
        return _clubelo_cache

    today   = datetime.now().strftime("%Y-%m-%d")
    cache_f = _cache_path(f"clubelo_{today}.pkl")

    if _cache_fresh(cache_f, 48):
        data = _load_pkl(cache_f)
        if data:
            _clubelo_cache = data
            print(f"  ClubElo cache: {len(data)} kulüp")
            return _clubelo_cache

    print("  ClubElo indiriliyor...")
    try:
        r = requests.get(f"http://api.clubelo.com/{today}",
                         headers=HEADERS, timeout=12)
        if r.status_code == 200:
            import io as _io
            df = pd.read_csv(_io.StringIO(r.text))
            if "Club" in df.columns and "Elo" in df.columns:
                _clubelo_cache = {
                    str(row["Club"]): float(row["Elo"])
                    for _, row in df.iterrows()
                    if pd.notna(row.get("Elo"))
                }
                _save_pkl(_clubelo_cache, cache_f)
                print(f"  ClubElo: {len(_clubelo_cache)} kulüp yüklendi")
                return _clubelo_cache
    except (OSError, IOError, ValueError, TypeError) as e:
        print(f"  ClubElo yuklenemedi: {e}")
    return {}


def get_clubelo(team_fd: str, clubelo: dict) -> float:
    """Football-data takım adından ClubElo puanı al. Bulamazsa 1500."""
    if not clubelo:
        return 1500.0
    mapped = _CLUBELO_MAP.get(team_fd, team_fd)
    if mapped in clubelo:
        return clubelo[mapped]
    tn = _normalize(team_fd)
    for club, elo in clubelo.items():
        if _normalize(club) == tn:
            return elo
    for club, elo in clubelo.items():
        if tn in _normalize(club) or _normalize(club) in tn:
            return elo
    return 1500.0


def _get_xg_data(team_fd: str, league_code: str = "T1") -> dict:
    """
    FootyStats xG verisi — XG_BY_LEAGUE statik tablodan.
    3 aşamalı eşleştirme:
    1. Tam eşleşme
    2. Substring eşleşme
    3. difflib SequenceMatcher (≥0.72 benzerlik)
    """
    try:
        from config import XG_BY_LEAGUE
        xg_dict = XG_BY_LEAGUE.get(league_code, {})
        if not xg_dict and league_code == "T1":
            from config import T1_XG
            xg_dict = T1_XG
        if not xg_dict:
            return None

        tn = _normalize(team_fd)

        # 1. Tam eşleşme
        for k, v in xg_dict.items():
            if _normalize(k) == tn:
                return v

        # 2. Substring eşleşme
        for k, v in xg_dict.items():
            kn = _normalize(k)
            if kn in tn or tn in kn:
                return v

        # 3. difflib fuzzy (≥0.72)
        from difflib import SequenceMatcher
        best_score, best_val = 0.0, None
        for k, v in xg_dict.items():
            score = SequenceMatcher(None, tn, _normalize(k)).ratio()
            if score > best_score:
                best_score, best_val = score, v
        if best_score >= 0.72:
            return best_val

    except (OSError, IOError, ValueError, TypeError, KeyError,
            RuntimeError, ImportError, ModuleNotFoundError):
        pass
    return None


def _dynamic_home_adv(team: str, stats: dict, lg_avg: float) -> float:
    """
    Takım bazlı dinamik ev avantajı.
    Sabit 1.10 yerine her takımın gerçek ev/deplasman performansından hesaplar.
    Sonuç: 1.03 – 1.20 arasında sınırlı (aşırı sapmaları engeller).
    """
    base_ha = CFG["home_advantage"]   # 1.10 varsayılan
    t       = stats.get(team)
    if t is None:
        return base_ha

    home_st = t.get("home", {})
    away_st = t.get("away", {})
    if not home_st or not away_st:
        return base_ha

    h_att = home_st.get("att", 1.0)
    a_att = away_st.get("att", 1.0)
    if a_att < 0.05:
        return base_ha

    # Ev/deplasman saldırı oranı → ev avantaj multiplier
    venue_ratio = h_att / a_att          # >1 = evde daha üretken
    raw_ha      = base_ha * max(0.88, min(1.18, venue_ratio))

    # Güven: az maç varsa base_ha'ya yaklaştır
    n_home = home_st.get("n", 0)
    if n_home < 6:
        conf   = n_home / 6.0            # 0-1 arası güven skoru
        raw_ha = conf * raw_ha + (1.0 - conf) * base_ha

    return max(1.03, min(1.20, raw_ha))

  
def calc_lambda(home: str, away: str,
                stats: dict, lg_avg: float,
                clubelo: dict = None,
                h2h: dict = None,
                league_code: str = None,
                **kwargs) -> tuple:
    """
    5 katmanlı λ hesabı:
    Katman 1  — Temel istatistik
    Katman 1b — FootyStats/API-Football xG override (%40)
    Katman 2  — Rolling form (%25)
    Katman 3  — ClubElo (±%10)
    Katman 4  — H2H (±%8)
    Katman 5  — Şans düzeltmesi (luck regression ±%5)
    """
    def _get(team, venue):
        t = stats.get(team)
        if t is None:
            return {"att":1.0,"def":1.0,"xg_att":1.0,"xg_def":1.0,
                    "roll5_gf":1.2,"roll5_ga":1.2,"roll5_pts":1.0,
                    "xg_for":1.2,"xg_ag":1.2,"n":0}
        return t.get(venue, t.get("overall", t))

    hs  = _get(home, "home")
    as_ = _get(away, "away")
    ha  = _dynamic_home_adv(home, stats, lg_avg)  # Fix 2: takım bazlı ev avantajı

    # ── Katman 1: Temel Dixon-Coles istatistik ──────────────
    lam_h = lg_avg * hs["att"] * as_["def"] * ha
    lam_a = lg_avg * as_["att"] * hs["def"]

    # Proxy xG blend %20 (çifte etki riskini azaltmak için düşürüldü)
    lam_h = lam_h*0.80 + lg_avg*hs["xg_att"]*as_["xg_def"]*ha*0.20
    lam_a = lam_a*0.80 + lg_avg*as_["xg_att"]*hs["xg_def"]*0.20

    lam_h = max(lam_h, 0.20)
    lam_a = max(lam_a, 0.20)

    # ── Katman 1b: FootyStats xG override (%20, %40'dan düşürüldü) ──
    # Sezon ortalaması verisi — günlük form kadar hassas değil
    xg_h = _get_xg_data(home, league_code or "T1")
    xg_a = _get_xg_data(away, league_code or "T1")
    # fixture_statistics API -> xG override
    _api_xg = False
    _fid2   = kwargs.get("fixture_id")
    if _fid2:
        try:
            from data.api_football import APIFootball
            _fst = APIFootball().fixture_statistics(_fid2)
            _hxg = _fst.get("home",{}).get("xg",-1)
            _axg = _fst.get("away",{}).get("xg",-1)
            if isinstance(_hxg,(int,float)) and _hxg>=0 and _axg>=0 and _hxg+_axg>0:
                lam_h = lam_h*0.60 + float(_hxg)*0.40
                lam_a = lam_a*0.60 + float(_axg)*0.40
                _api_xg = True
        except Exception:
            pass
    if not _api_xg and xg_h and xg_a:
        lg_xg_avg = 1.35
        lam_h_fs  = (xg_h["xg"] / lg_xg_avg) * (xg_a["xga"] / lg_xg_avg) * lg_avg * ha
        lam_a_fs  = (xg_a["xg"] / lg_xg_avg) * (xg_h["xga"] / lg_xg_avg) * lg_avg
        lam_h = lam_h * 0.80 + lam_h_fs * 0.20
        lam_a = lam_a * 0.80 + lam_a_fs * 0.20

    # ── Katman 2: Rolling form (%15) ─────────────────────────
    # Form bilgisi zaten Kat.1'deki att/def faktörlerine kısmen yansıyor.
    # ff_h ∈ [0.85, 1.15] — lam_h ile bağımsız blendleniyor (öz-çarpım değil).
    def _form_factor(roll_gf, overall_att, lg_a):
        base = overall_att * lg_a
        if base < 0.1:
            return 1.0
        return max(0.85, min(1.15, 0.75 + 0.25 * roll_gf / base))

    ff_h = _form_factor(hs.get("roll5_gf",1.2), hs.get("att",1.0), lg_avg)
    ff_a = _form_factor(as_.get("roll5_gf",1.2), as_.get("att",1.0), lg_avg)

    # Düzeltme: lam_h*ff_h*0.15 yerine lg_avg tabanlı bağımsız blend
    # Eski: lam_h*(0.85 + 0.15*ff_h)  → gerçek etki sadece ±%2.2
    # Yeni: 0.85*lam_h + 0.15*(ff_h * lg_avg * ha)  → ±%10 tam etkili blend
    _form_h = ff_h * lg_avg * hs.get("att", 1.0) * _get(away, "away").get("def", 1.0) * \
              _dynamic_home_adv(home, stats, lg_avg)
    _form_a = ff_a * lg_avg * as_.get("att", 1.0) * _get(home, "home").get("def", 1.0)
    _form_h = max(0.20, _form_h)
    _form_a = max(0.20, _form_a)
    lam_h = lam_h * 0.85 + _form_h * 0.15
    lam_a = lam_a * 0.85 + _form_a * 0.15

    # ── Katman 3: ClubElo (±%8, bağımsız sinyal) ────────────
    if clubelo:
        elo_h = get_clubelo(home, clubelo)
        elo_a = get_clubelo(away, clubelo)
        if elo_h != 1500.0 or elo_a != 1500.0:
            elo_diff   = (elo_h - elo_a) / 400.0
            elo_factor = math.tanh(elo_diff) * 0.08   # %10 → %8
            lam_h *= (1.0 + elo_factor)
            lam_a *= (1.0 - elo_factor)

    # ── Katman 4: H2H son 5 maç (±%6) ──────────────────────
    if h2h and h2h.get("n", 0) >= 3:
        n      = h2h["n"]
        h_rate = h2h["h_wins"] / n
        a_rate = h2h["a_wins"] / n

        h_bias = (h_rate - 0.45) * 0.06   # %8 → %6
        a_bias = (a_rate - 0.28) * 0.06

        lam_h *= (1.0 + h_bias)
        lam_a *= (1.0 + a_bias)

        if h2h.get("h_goals_avg") and h2h.get("a_goals_avg"):
            h_g_factor = h2h["h_goals_avg"] / max(lg_avg, 0.5)
            a_g_factor = h2h["a_goals_avg"] / max(lg_avg, 0.5)
            lam_h = lam_h*0.92 + lam_h*h_g_factor*0.08
            lam_a = lam_a*0.92 + lam_a*a_g_factor*0.08

    # ── Katman 5: Luck regression (±%4) ─────────────────────
    if xg_h:
        lam_h *= (1.0 - xg_h["luck"] * 0.04)
    if xg_a:
        lam_a *= (1.0 - xg_a["luck"] * 0.04)

    # ── Katman 6: LPRM — Lig-bazlı koşullu aktivasyon ─────────
    # Backtest: 5/6 ligde LPRM Brier kötüleştiriyor.
    # Koşul: lig whitelist + skor eşiği + düzeltme sınırı
    # LPRM_WHITELIST: sadece nötr/pozitif çıkan ligler (SP1)
    LPRM_WHITELIST = {"SP1"}   # Ağustos sonrası A/B test ile genişletilecek
    LPRM_MIN_SCORE = 0.55      # Min güvenilir LPRM skoru
    LPRM_MAX_ADJ   = 0.08      # Maks ±%8 düzeltme sınırı

    lprm_result = kwargs.get("lprm_result")
    # kwargs'ta league_code varsa onu kullan, yoksa fonksiyon parametresini koru
    league_code = kwargs.get("league_code", league_code) or ""
    _lprm_active = (
        lprm_result is not None
        and lprm_result.get("lprm_score") is not None
        and lprm_result["lprm_score"] >= LPRM_MIN_SCORE
        and league_code in LPRM_WHITELIST
    )

    if _lprm_active:
        adj_h = lprm_result["lambda_adj_h"]
        adj_a = lprm_result["lambda_adj_a"]
        adj_h = max(1.0 - LPRM_MAX_ADJ, min(1.0 + LPRM_MAX_ADJ, adj_h))
        adj_a = max(1.0 - LPRM_MAX_ADJ, min(1.0 + LPRM_MAX_ADJ, adj_a))
        lam_h *= adj_h
        lam_a *= adj_a

    # ── Katman 7: Pozisyon Bias — config.POS_BIAS tabanlı ───────────────
    # Lambda: ev/dep directional bias → lam_h veya lam_a'ya uygula
    # X bias: suggest.py'de draw_thr üzerinden ayrıca çalışır (burada değil)
    # Katsayı kaynağı: 25 hafta, 294 lig maçı — SporToto-sonuclar.docx
    _pos = kwargs.get("position")
    if _pos is not None:
        try:
            # Önce position_bias.py modülünden, yoksa config.POS_BIAS'tan al
            _pb_dict = None
            try:
                from model.position_bias import POSITION_LAMBDA_BIAS
                _pb_dict = POSITION_LAMBDA_BIAS.get(_pos, {})
            except ImportError:
                pass

            if _pb_dict is None:
                # Fallback: config.py POS_BIAS
                _cfg_pb = CFG.get("POS_BIAS", {}) if isinstance(CFG, dict) else {}
                _pb_cfg = _cfg_pb.get(_pos, {})
                _pb_dict = {}
                if "lam_h" in _pb_cfg: _pb_dict["1"] = _pb_cfg["lam_h"]
                if "lam_a" in _pb_cfg: _pb_dict["2"] = _pb_cfg["lam_a"]

            if _pb_dict:
                _lam_h_bias = _pb_dict.get("1", 0.0)
                _lam_a_bias = _pb_dict.get("2", 0.0)
                # FIX #2: elif → if (iki bias bağımsız uygulanmalı)
                # FIX #3: > 0 → != 0.0 (negatif bias da uygulanmalı)
                # Max ±%8 sınırı ile uygula (her iki yön)
                if _lam_h_bias != 0.0:
                    lam_h *= max(0.92, min(1.08, 1.0 + _lam_h_bias))
                if _lam_a_bias != 0.0:
                    lam_a *= max(0.92, min(1.08, 1.0 + _lam_a_bias))
        except Exception:
            pass


    lam_h = min(max(lam_h, 0.20), 3.50)
    lam_a = min(max(lam_a, 0.20), 3.50)

    # ── Katman 8: ML Ensemble Harmanlama (±%15) ─────────────
    # LPRM lambda → P(1/X/2) → ML ile harmanla → tekrar lambda
    # ML hazır değilse (model yok) bu katman atlanır.
    try:
        from model.ml_engine import get_ml
        import math
        _ml = get_ml()
        if _ml.trained.get("gb") or _ml.trained.get("lr"):
            # LPRM lambdadan P(1/X/2) tahmin et
            _total = lam_h + lam_a
            # FIX #4: Eski formül P(X≥2) hesaplıyordu, P(ev kazanır) değil.
            # Doğru: poisson_analytical() ile gerçek 1/X/2 olasılıkları al.
            try:
                from model.monte_carlo import poisson_analytical as _pa
                _p1_lprm, _px_lprm, _p2_lprm = _pa(lam_h, lam_a, use_dc=False)
            except Exception:
                # Fallback: basit Poisson marginal (eski koddan daha iyi)
                _p1_lprm = max(0.05, min(0.92, 1 - math.exp(-lam_h)))
                _p2_lprm = max(0.05, min(0.92, 1 - math.exp(-lam_a)))
                _px_lprm = max(0.05, 1 - _p1_lprm - _p2_lprm)
            _p1_lprm = max(0.05, min(0.92, _p1_lprm))
            _p2_lprm = max(0.05, min(0.92, _p2_lprm))
            _px_lprm = max(0.05, min(0.90, _px_lprm))
            # ML feature vektörü
            from model.ml_engine import AugurML
            _pos_no = kwargs.get("position", 8)
            _feat = AugurML.build_features(
                {"P1": _p1_lprm*100, "PX": _px_lprm*100,
                 "P2": _p2_lprm*100},
                position=_pos_no,
                season_week=kwargs.get("season_week", 20),
                devret_flag=int(kwargs.get("devret", False)),
                league_draw_rate=kwargs.get("league_draw_rate", 0.26),
                elo_diff=kwargs.get("elo_diff", 0.0),
            )
            _ml_out = _ml.predict(_feat)
            if _ml_out:
                _p1_ml = _ml_out["p1"]
                _p2_ml = _ml_out["p2"]
                # ML güven skoru — düşük güvende harman azalır
                _ml_w  = 0.20 * _ml_out["confidence"]
                _lp_w  = 1.0 - _ml_w
                # Harmonlanmış P → Lambda'ya geri çevir
                _p1_h  = _lp_w * _p1_lprm + _ml_w * _p1_ml
                _p2_h  = _lp_w * _p2_lprm + _ml_w * _p2_ml
                _p1_h  = max(0.05, min(0.92, _p1_h))
                _p2_h  = max(0.05, min(0.92, _p2_h))
                # Lambda güncelle — toplam önce kaydedilmeli (circular update önlenir)
                _lam_total_k8 = lam_h + lam_a
                lam_h = max(0.15, -math.log(max(0.01,
                    1 - _p1_h)) * _lam_total_k8 / 2)
                lam_a = max(0.15, -math.log(max(0.01,
                    1 - _p2_h)) * _lam_total_k8 / 2)
    except Exception as _k8_err:
        logger.debug("K8 ML katmanı atlandı: %s", _k8_err)
        pass   # ML katmanı başarısız → LPRM sonucu koru

    # ── λ normalize ─────────────────────────────────────────
    total  = lam_h + lam_a
    target = CFG["lambda_target"]
    if total > 0 and abs(total - target) > 0.4:
        scale  = target / total
        lam_h *= scale
        lam_a *= scale

    # ── Katman 9: Sakatlık/Ceza Düzeltmesi ─────────────────────
    # fixture_id kwarg varsa API-Football /injuries çek
    # Önemli oyuncu yoksa gol beklentisi düşer (max ±%20)
    _fixture_id = kwargs.get("fixture_id")
    if _fixture_id:
        try:
            from data.api_football import APIFootball

            def _injury_impact(injuries: list, team_name: str) -> float:
                """
                Sakat/cezalı oyuncuların gol beklentisine etkisi.
                FW = 0.08, CAM/CF = 0.06, CM = 0.03, GK = 0.05
                Max etki: 0.20 (yani %-20 gol düşüşü)
                """
                POSITION_WEIGHT = {
                    "F": 0.08, "FW": 0.08,        # forvet
                    "A": 0.07, "CF": 0.07,          # hücum
                    "M": 0.04, "CAM": 0.06,         # orta saha
                    "D": 0.02, "CB": 0.02,          # defans
                    "G": 0.05, "GK": 0.05,          # kaleci
                }
                impact = 0.0
                team_up = team_name.upper()
                for inj in injuries:
                    t = str(inj.get("team_name", "")).upper()
                    if team_up[:4] not in t[:8] and t[:4] not in team_up[:8]:
                        continue
                    pos = str(inj.get("type", "")).upper()[:3]
                    w   = POSITION_WEIGHT.get(pos, 0.02)
                    impact += w
                return min(0.20, impact)

            _api     = APIFootball()
            _injuries = _api.injuries(_fixture_id)
            if _injuries:
                _h_impact = _injury_impact(_injuries, home)
                _a_impact = _injury_impact(_injuries, away)
                if _h_impact > 0.01:
                    lam_h *= (1.0 - _h_impact)
                if _a_impact > 0.01:
                    lam_a *= (1.0 - _a_impact)
        except Exception as _k9_err:
            logger.debug("K9 Sakatlık katmanı atlandı: %s", _k9_err)
            pass   # Injuries alınamazsa LPRM sonucu koru

    # ── Katman 10: Başlangıç 11 — Kilit Oyuncu Eksikliği ──────────
    # /fixtures/lineups + /players/topscorers ile:
    #   - Başlangıç 11'de olmayan golcülerin katkı payı tespit edilir
    #   - Her eksik golcü için saldırı λ'sı orantılı düşürülür (max -%20)
    #   - Yeni hoca (son 42 gün) tespiti → belirsizlik multiplier
    if _fixture_id:
        try:
            from data.api_football import APIFootball, LEAGUE_ID_MAP, SEASON_MAP
            _api10   = APIFootball()
            _lineups = _api10.lineups(_fixture_id)

            if _lineups:
                # Lig/sezon bilgisi
                _lid10 = LEAGUE_ID_MAP.get(league_code or "", 0)
                from config import CURRENT_SEASON as _cs10
                _sea10 = SEASON_MAP.get(_cs10, 2025)

                _top10 = _api10.topscorers(_lid10, _sea10, limit=10) if _lid10 else []

                def _attack_factor(side: str, team_nm: str) -> float:
                    """Başlangıç 11 eksik golcü → saldırı λ düzeltme katsayısı."""
                    lup = _lineups.get(side, {})
                    if not lup or not _top10:
                        return 1.0
                    starter_ids  = {p["id"] for p in lup.get("players", []) if p["id"]}
                    starter_norm = {p["name"].upper()[:6]
                                    for p in lup.get("players", [])}
                    tn4 = team_nm.upper()[:4]

                    # Bu takımın golcüleri
                    team_scorers = [s for s in _top10
                                    if s["team"].upper()[:4] == tn4
                                    and s["goals"] >= 2]
                    if not team_scorers:
                        return 1.0

                    total_g = sum(s["goals"] for s in team_scorers) or 1
                    missing = 0.0
                    for sc in team_scorers:
                        in_xi = (sc["player_id"] in starter_ids or
                                 sc["name"].upper()[:6] in starter_norm)
                        if not in_xi:
                            # Eksik golcü: katkısının %55'i kayıp
                            missing += (sc["goals"] / total_g) * 0.55
                    return max(0.78, 1.0 - min(0.20, missing))

                _fh10 = _attack_factor("home", home)
                _fa10 = _attack_factor("away", away)
                if _fh10 < 0.995:
                    lam_h *= _fh10
                if _fa10 < 0.995:
                    lam_a *= _fa10

                # Yeni hoca belirsizliği — standings üzerinden team_id al
                if _lid10:
                    for _side10, _tnm10 in (("home", home), ("away", away)):
                        try:
                            _tid10 = _api10.get_team_id(_tnm10, _lid10, _sea10)
                            if _tid10:
                                _cdata = _api10.coaches(_tid10)
                                if _cdata.get("is_new"):
                                    # Yeni hoca → ±%4 belirsizlik (her iki λ'yı ortaya çek)
                                    _avg10 = (lam_h + lam_a) / 2
                                    if _side10 == "home":
                                        lam_h = lam_h * 0.96 + _avg10 * 0.04
                                    else:
                                        lam_a = lam_a * 0.96 + _avg10 * 0.04
                        except Exception:
                            pass
        except Exception as _k10_err:
            logger.debug("K10 Lineup katmanı atlandı: %s", _k10_err)

    # ── Final: Rezidüel ML düzeltmesi (model varsa) ────────────
    # ResidualML → base_p'yi düzeltip tekrar lambda'ya çevirir
    # NOT: henüz yeterli veri yok → model yoksa geç
    try:
        import math
        from model.ml_engine import get_residual_ml
        _res = get_residual_ml()
        # R² < 0 ise model gürültü öğrenmiş → uygulama
        _min_r2 = min(_res.scores.values()) if _res.scores else -1.0
        if _res.trained and _min_r2 > 0.01:
            # Mevcut lambda → base probs
            # FIX #4b: Rezidüel ML'de de aynı hatalı formül vardı.
            # poisson_analytical ile gerçek 1/X/2 olasılıkları hesapla.
            try:
                from model.monte_carlo import poisson_analytical as _pa2
                _bp1, _bpx, _bp2 = _pa2(lam_h, lam_a, use_dc=False)
                _bp1 = max(0.03, _bp1); _bp2 = max(0.03, _bp2)
                _bpx = max(0.03, _bpx)
            except Exception:
                _bp1 = max(0.03, 1 - math.exp(-lam_h))
                _bp2 = max(0.03, 1 - math.exp(-lam_a))
                _bpx = max(0.03, 1 - _bp1 - _bp2)
            # Extra features (elden mevcut kwargs)
            _pd = kwargs.get("elo_diff", 0.0)
            _sw = kwargs.get("season_week", 20)
            _x_ex = [_pd, 0.0, _pd, 0.0, 0.0, 7.0, 7.0, 0.5, 0.0, _sw/38.0]
            # Rezidüel uygula
            _rp1, _rpx, _rp2 = _res.apply(_bp1, _bpx, _bp2, _x_ex)
            # Geri lambda'ya çevir — toplam önce kaydedilmeli (circular update önlenir)
            _lam_total_res = lam_h + lam_a
            lam_h = max(0.15, -math.log(max(0.01, 1-_rp1)) * _lam_total_res/2)
            lam_a = max(0.15, -math.log(max(0.01, 1-_rp2)) * _lam_total_res/2)
    except Exception as _res_err:
        logger.debug("Rezidüel ML katmanı atlandı: %s", _res_err)
        pass   # Rezidüel model yoksa koru

    return max(lam_h, 0.15), max(lam_a, 0.15)
