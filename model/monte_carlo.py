# -*- coding: utf-8 -*-
from config import *
import sys, re, io, os, json, math, time, warnings
from datetime import datetime
from difflib import SequenceMatcher
import requests
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════
# BÖLÜM 7 — MONTE CARLO + DIXON-COLES
# ═══════════════════════════════════════════════════════════════

def poisson_analytical(lam_h: float, lam_a: float,
                        max_goals: int = 8,
                        use_dc: bool = True,
                        league_code: str = None) -> tuple:
    """
    Analitik Poisson + Dixon-Coles ile 1/X/2 olasılığı.
    Monte Carlo'ya göre deterministik ve ~50x daha hızlı.
    Döner: (p1, px, p2)
    """
    import math
    tau = _dixon_coles_tau(lam_h, lam_a, league_code=league_code) if use_dc else {}

    def pmf(lam: float, k: int) -> float:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    p1 = px = p2 = 0.0
    for h in range(max_goals + 1):
        ph = pmf(lam_h, h)
        if ph < 1e-10: continue
        for a in range(max_goals + 1):
            pa = pmf(lam_a, a)
            if pa < 1e-10: continue
            joint = ph * pa
            if use_dc and (h, a) in tau:
                joint *= tau[(h, a)]
            if   h > a: p1 += joint
            elif h == a: px += joint
            else:        p2 += joint

    total = p1 + px + p2
    if total < 1e-9: return (0.45, 0.27, 0.28)
    return p1/total, px/total, p2/total



def _dixon_coles_tau(lam_h: float, lam_a: float,
                     rho: float = -0.13,
                     league_code: str = None) -> dict:
    """
    Dixon-Coles düzeltme katsayıları (lig bazlı rho).
    Düşük skorlu maçlar (0-0, 1-0, 0-1, 1-1) gerçekte saf
    Poisson'dan daha sık → X olasılığı düzeltilir.

    rho = -0.13 literatür standardı (Dixon & Coles 1997).
    Lig bazlı: Bundesliga -0.11 (gollü), Serie A -0.14 (defansif).
    """
    if league_code is not None:
        try:
            from config import DIXON_COLES_RHO
            rho = DIXON_COLES_RHO.get(league_code, rho)
        except (ImportError, KeyError):
            pass
    return {
        (0, 0): max(0.0, 1 - lam_h * lam_a * rho),
        (1, 0): max(0.0, 1 + lam_a * rho),
        (0, 1): max(0.0, 1 + lam_h * rho),
        (1, 1): max(0.0, 1 - rho),
    }


def monte_carlo(lam_h: float, lam_a: float,
                use_dc: bool = True) -> tuple:
    """
    Tek maç olasılığı — Saf Analitik Poisson + Dixon-Coles.

    ARAŞTIRMA GÜNCELLEMESİ (Haziran 2026):
    MC blend (%40) kaldırıldı. Dixon-Coles skor olasılıkları kapalı
    formda analitik hesaplanır; MC yalnızca örnekleme gürültüsü ekler.
    Avantaj: deterministik, ~50x hızlı, Pydroid3 bellek tasarrufu.
    Kaynak: Štrumbelj (2014); stats and snakeoil (2018).

    Döner: (p1, px, p2)
    """
    return poisson_analytical(lam_h, lam_a, use_dc=use_dc)


def monte_carlo_with_ci(lam_h: float, lam_a: float,
                        n_bootstrap: int = 200) -> tuple:
    """
    Monte Carlo + %90 güven aralığı (bootstrap).
    Döner: (p1, px, p2, ci_width)
    ci_width: p1+p2 arasındaki standart sapma → "belirsizlik skoru"
    """
    p1, px, p2 = monte_carlo(lam_h, lam_a, use_dc=True)

    # Bootstrap ile güven aralığı tahmini
    rng     = np.random.default_rng()
    n       = min(CFG["simulations"], 10_000)  # CI için 10k yeterli
    samples = []
    for _ in range(n_bootstrap):
        hg = rng.poisson(lam_h, n)
        ag = rng.poisson(lam_a, n)
        samples.append(float(np.mean(hg == ag)))  # X olasılığı

    ci_width = float(np.std(samples))
    return p1, px, p2, ci_width


def monte_carlo_batch(lambdas: list, use_dc: bool = True) -> list:
    """Tüm maçları simüle et. [(lam_h, lam_a), ...] → [(p1,px,p2), ...]"""
    return [monte_carlo(lh, la, use_dc) for lh, la in lambdas]


# ═══════════════════════════════════════════════════════════════
# BÖLÜM 8 — ORANLAR & BLEND
# ═══════════════════════════════════════════════════════════════

def shin_implied_probs(o1, ox, o2) -> tuple:
    """
    Shin (1992) metodu ile vig çıkarma.

    Basit normalizasyona göre fark:
    - Favoriler için daha düşük (ve doğru) olasılık atar
    - Uzun oranlar için biraz daha yüksek olasılık verir
    - Brier skoru optimizasyonuna göre ~1-2% iyileştirme (Štrumbelj 2014)

    Algoritma: qi = 1/oi (ham), Z = sum(qi) > 1
    Shin probs: pi(z) = [sqrt(z² + 4(1-z)·qi/Z) - z] / [2(1-z)]
    z biseksiyon ile bulunur: sum(pi) = 1
    """
    if None in (o1, ox, o2):
        return (None, None, None)
    try:
        q  = [1/float(o1), 1/float(ox), 1/float(o2)]
        Z  = sum(q)
        if Z <= 1.0 + 1e-6:
            return tuple(v / Z for v in q)

        def _shin_p(z: float) -> list:
            if abs(1.0 - z) < 1e-12:
                return [qi / Z for qi in q]
            return [
                max(1e-8, (math.sqrt(z*z + 4*(1-z)*qi/Z) - z) / (2*(1-z)))
                for qi in q
            ]

        lo, hi = 0.0, 0.9999
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if sum(_shin_p(mid)) > 1.0:
                lo = mid
            else:
                hi = mid

        p = _shin_p((lo + hi) / 2.0)
        total = sum(p)
        if total <= 0:
            return tuple(qi / Z for qi in q)   # fallback: basit normalize
        return tuple(pi / total for pi in p)
    except (ZeroDivisionError, TypeError, ValueError, OverflowError):
        # Shin başarısız → basit normalizasyon
        try:
            raw = [1/float(o1), 1/float(ox), 1/float(o2)]
            s   = sum(raw)
            return tuple(v/s for v in raw) if s > 0 else (None, None, None)
        except Exception:
            return (None, None, None)


def implied_probs(o1, ox, o2) -> tuple:
    """
    Bahis oranlarını overround-normalize edilmiş olasılığa çevir.
    Varsayılan olarak Shin metodunu kullanır (daha doğru).
    """
    if None in (o1, ox, o2):
        return (None, None, None)
    try:
        raw   = [1/float(o1), 1/float(ox), 1/float(o2)]
        total = sum(raw)
        if total <= 0:
            return (None, None, None)
        # Shin metodu → daha doğru vig çıkarma
        return shin_implied_probs(o1, ox, o2)
    except (ZeroDivisionError, TypeError, ValueError):
        return (None, None, None)


def kelly_fraction(model_p: float, odds: float,
                   bank: float = 1.0,
                   kelly_frac: float = None) -> float:
    """
    Kelly kriteri bahis boyutu hesabı (çeyrek Kelly — güvenli).

    model_p: modelimizin kazanma olasılığı
    odds:    bahisçinin oranı (decimal, örn. 2.50)
    bank:    toplam bütçe (normalize edilmiş, varsayılan 1.0)
    kelly_frac: Kelly çarpanı (0.25 = çeyrek Kelly)

    Döner: bahis miktarı (banka yüzdesi, 0.0-1.0 arası)
           Negatif edge durumunda 0 döner (bahis yok).
    """
    if kelly_frac is None:
        kelly_frac = CFG.get("kelly_fraction", 0.25)
    if not model_p or not odds or odds <= 1.0:
        return 0.0
    b = float(odds) - 1.0      # net kazanç oranı
    p = float(model_p)
    q = 1.0 - p                # kaybetme olasılığı
    # Full Kelly: f = (b*p - q) / b
    full_kelly = (b * p - q) / b
    if full_kelly <= 0:
        return 0.0             # negatif edge → bahis yok
    # Çeyrek Kelly (maksimum güvenlik)
    frac = full_kelly * kelly_frac
    # Banka oranının %8'i ile sınırla (ruin riskini azaltır)
    return round(min(frac, 0.08) * bank, 4)


def overround(o1, ox, o2) -> float:
    """
    Bahisçi marjı (overround) hesapla.
    Örn: 1.10 = %10 vig, piyasa %10 pahalı.
    """
    if None in (o1, ox, o2):
        return 0.0
    try:
        return sum(1/float(o) for o in [o1, ox, o2]) - 1.0
    except (ZeroDivisionError, TypeError, ValueError):
        return 0.0


def compute_entropy(p1: float, px: float, p2: float) -> float:
    """
    Shannon entropy: belirsizlik ölçüsü.
    H = -Σ p_i * log(p_i)

    H > 1.05 → Yüksek belirsizlik (KAOS adayı)
    H < 0.85 → Düşük belirsizlik (BANKO adayı)
    Maks: log(3) ≈ 1.099 (üç eşit olasılık)
    """
    H = 0.0
    for p in [p1, px, p2]:
        if p > 1e-9:
            H -= p * math.log(p)
    return round(H, 4)


def blend_probs(model: tuple, implied: tuple,
                odds_quality: float = 1.0,
                odds_delta: float = 1.0) -> tuple:
    """
    Model + Oran harmonik blend.
    odds_quality: 0.0–1.0, oran güvenilirliğine göre ağırlık ayarlar.
      1.0 = tam güvenilir (Pinnacle oranı)
      0.5 = orta güvenilir (başka kaynak)
      0.0 = oran yok, saf model

    odds_delta: açılış/kapanış oranı hareketi sinyali.
      < 0.90 = ev tarafına güçlü para aktı → oran ağırlığı artar
      > 1.10 = ev aleyhine para aktı → oran ağırlığı artar
      = 1.00 = hareket yok
    """
    if None in implied:
        return model
    mw = CFG["model_weight"]
    ow = CFG["odds_weight"] * odds_quality

    # Delta sinyali: büyük hareket → piyasaya daha fazla güven
    # |delta - 1| ne kadar büyükse oran ağırlığı o kadar artar (max +%15)
    delta_boost = min(0.15, abs(odds_delta - 1.0) * 0.75)
    ow = min(ow + delta_boost, 0.50)  # max %50

    # Normalize
    total_w = mw + ow
    mw /= total_w
    ow /= total_w
    return tuple(model[i]*mw + implied[i]*ow for i in range(3))


def calibrate_probs(p1: float, px: float, p2: float,
                    history: list = None) -> tuple:
    """
    Platt/isotonic benzeri basit kalibrasyon.

    Mevcut Brier skoru geçmişinden öğrenerek overconfidence'ı düzeltir.
    sklearn gerektirmez — saf Python ile çalışır (Pydroid3 uyumlu).

    history: [(pred_p, actual_binary), ...] geçmiş tahminler
             Yoksa sabit shrinkage kullanılır.

    Döner: (p1_cal, px_cal, p2_cal) — kalibre edilmiş olasılıklar
    """
    # Shrinkage kalibrasyonu (Laplace smoothing benzeri)
    # Overconfidence'ı azaltır: uç değerleri ortaya çeker
    # alpha: ne kadar çekileceği — Brier skoru ile ayarlanır
    # Brier < 0.18 → az düzelt, Brier > 0.22 → çok düzelt

    # Sabit alpha (geçmiş yoksa):
    # Literatür önerisi: alpha = 0.15 iyi bir başlangıç
    alpha = CFG.get("calibration_alpha", 0.15)

    PRIOR = (0.45, 0.27, 0.28)  # genel lig ortalaması

    p1_cal = (1 - alpha) * p1 + alpha * PRIOR[0]
    px_cal = (1 - alpha) * px + alpha * PRIOR[1]
    p2_cal = (1 - alpha) * p2 + alpha * PRIOR[2]

    # Normalize
    total = p1_cal + px_cal + p2_cal
    return p1_cal/total, px_cal/total, p2_cal/total


def calibrate_from_history(p1: float, px: float, p2: float,
                           brier_score: float = None,
                           league_code: str = None) -> tuple:
    """
    Brier skoru bazlı dinamik kalibrasyon.
    Brier iyi (<0.19) → az düzelt
    Brier kötü (>0.22) → çok düzelt
    """
    if brier_score is None:
        brier_score = 0.20  # varsayılan

    # Alpha: Brier'den dinamik
    # 0.185 → alpha=0.10, 0.22 → alpha=0.20
    # Fix 4: Lig bazli kalibrasyon carpani
    try:
        from config import LEAGUE_CALIB
        lg_mult = LEAGUE_CALIB.get(league_code or "E0", 1.0)
    except Exception:
        lg_mult = 1.0
    # Alpha: Brier'den dinamik x lig carpani (T1=0.80 az duzelt, D1=1.40 cok duzelt)
    alpha = max(0.06, min(0.35, (brier_score - 0.15) * 2.0 * lg_mult))

    PRIOR = (0.45, 0.27, 0.28)
    p1_cal = (1 - alpha) * p1 + alpha * PRIOR[0]
    px_cal = (1 - alpha) * px + alpha * PRIOR[1]
    p2_cal = (1 - alpha) * p2 + alpha * PRIOR[2]

    total = p1_cal + px_cal + p2_cal
    return p1_cal/total, px_cal/total, p2_cal/total


def simulate_coupon(probs: list, selections: list, n_sim: int = 20000) -> dict:
    """
    15 maçlık kuponu TEK SİSTEM olarak simüle et.

    probs      : [(p1,px,p2), ...] — her maçın olasılıkları
    selections : ["1X2", "1X", "1", ...] — her maçın seçimi
    n_sim      : simülasyon sayısı

    Döner:
      hit_prob   : kuponu tam bilme olasılığı
      dist       : {15:f, 14:f, 13:f, 12:f, ...} — doğru sayısı dağılımı
      ev_proxy   : beklenen doğru sayısı
    """
    import numpy as np

    n_matches = len(probs)
    # FIX #6: Sabit seed=42 kaldırıldı — her çağrıda farklı rastgele sayılar.
    # Sabit seed tüm simülasyonları özdeş yapıyordu, istatistiksel anlam yitiyordu.
    rng       = np.random.default_rng()

    # Her maç için kümülatif olasılık matrisi
    prob_matrix = np.array(probs, dtype=float)       # (n_matches, 3)
    cumulative  = np.cumsum(prob_matrix, axis=1)      # (n_matches, 3)

    # n_sim × n_matches rastgele çekiş
    rand = rng.random((n_sim, n_matches))             # (n_sim, n_matches)

    # Her maç için çıktı: 0=1, 1=X, 2=2
    outcomes = (rand[..., None] > cumulative[None, :, :]).sum(axis=2)  # (n_sim, n_matches)

    # Seçim matrisi: her maçta hangi çıktılar geçerli?
    outcome_map = {"1": 0, "X": 1, "2": 2}
    hits_matrix = np.zeros((n_sim, n_matches), dtype=bool)

    for i, sel in enumerate(selections):
        allowed = set()
        for ch in sel:
            if ch in outcome_map:
                allowed.add(outcome_map[ch])
        if allowed:
            hits_matrix[:, i] = np.isin(outcomes[:, i], list(allowed))
        else:
            hits_matrix[:, i] = True  # seçim yoksa her şey geçer

    # Her simülasyonda kaç maç doğru?
    correct_counts = hits_matrix.sum(axis=1)   # (n_sim,)

    # Dağılım
    dist = {}
    for k in range(n_matches + 1):
        dist[k] = float((correct_counts == k).sum() / n_sim)

    hit_prob = dist.get(n_matches, 0.0)
    ev_proxy = float(correct_counts.mean())

    return {
        "hit_prob":  round(hit_prob, 6),
        "ev_proxy":  round(ev_proxy, 2),
        "dist":      {k: round(v, 4) for k, v in dist.items() if v > 0.0001},
        "n_sim":     n_sim,
    }


def value_check(model: tuple, implied: tuple,
                min_edge: float = 0.05) -> dict:
    """
    Value bet tespiti.
    Edge = model_prob - implied_prob (pozitif = model daha iyimser)

    Döner:
      has_value   : bool
      outcome     : "1/X/2" (en yüksek pozitif edge)
      edge        : float
      neg_outcome : "1/X/2" (en kötü negatif edge — piyasa çok güçlü)
      neg_edge    : float (mutlak değer)
      overround   : float (bahisçi marjı)
    """
    if None in implied or None in model:
        return {"has_value": False, "outcome": None, "edge": 0.0,
                "neg_outcome": None, "neg_edge": 0.0, "overround": 0.0}

    labels  = ["1", "X", "2"]
    edges   = {lbl: model[i] - implied[i] for i, lbl in enumerate(labels)}

    # En iyi pozitif edge (value bet)
    best_lbl  = max(edges, key=edges.get)
    best_edge = edges[best_lbl]

    # En kötü negatif edge (piyasa çok güçlü)
    worst_lbl  = min(edges, key=edges.get)
    worst_edge = edges[worst_lbl]

    return {
        "has_value":   best_edge >= min_edge,
        "outcome":     best_lbl if best_edge >= min_edge else None,
        "edge":        round(best_edge, 3),
        "neg_outcome": worst_lbl if worst_edge < -min_edge else None,
        "neg_edge":    round(abs(worst_edge), 3),
        "overround":   round(sum(1/p for p in implied if p and p > 0) - 1, 3),
    }


def context_adjust(p1: float, px: float, p2: float,
                   home: str, away: str,
                   standings: dict,
                   total_teams: int = 18) -> tuple:
    """
    Lig konumuna göre X olasılığını kalibre et.
    Dixon-Coles temel düzeltmeyi yapar, bu fonksiyon bağlam eklentisi.
    """
    if not standings:
        return p1, px, p2

    h_info = standings.get(home)
    a_info = standings.get(away)
    if not h_info or not a_info:
        return p1, px, p2

    h_pct = h_info["rank"] / total_teams
    a_pct = a_info["rank"] / total_teams

    x_boost = 0.0

    if h_pct <= 0.25 and a_pct <= 0.25:
        x_boost += 0.03
    if h_pct >= 0.75 or a_pct >= 0.75:
        x_boost += 0.03
    if h_pct >= 0.75 and a_pct >= 0.75:
        x_boost += 0.02
    if abs(h_pct - a_pct) <= 0.20:
        x_boost += 0.015
    if abs(h_pct - a_pct) >= 0.60:
        x_boost -= 0.015

    # FIX #9: Float eşitlik karşılaştırması güvenilmez — abs() ile kontrol et.
    if abs(x_boost) < 1e-9:
        return p1, px, p2

    new_px    = min(0.45, px + x_boost)
    diff      = new_px - px
    total_win = p1 + p2

    if total_win > 0.01:
        new_p1 = p1 - diff * (p1 / total_win)
        new_p2 = p2 - diff * (p2 / total_win)
    else:
        new_p1, new_p2 = p1, p2
        new_px = px

    total = new_p1 + new_px + new_p2
    if total < 1e-9:
        return p1, px, p2
    return new_p1/total, new_px/total, new_p2/total
