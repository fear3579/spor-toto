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


def suggest(p1: float, px: float, p2: float,
            value_info: dict = None,
            ci_width: float = None,
            banko_threshold: float = None,
            entropy: float = None,
            lprm_draw_signal: bool = False,
            position: int = None,
            lambda_diff: float = None) -> tuple:
    """
    Confidence-bazlı karar sistemi.
    banko_threshold   : dinamik eşik (hafıza tarafından güncellenir)
    lprm_draw_signal  : LPRM draw eğilimi tespit ettiyse True
    position          : Spor Toto liste pozisyonu (1-15)
    lambda_diff       : abs(lam_h - lam_a) — denge sinyali
    """
    from model.monte_carlo import compute_entropy

    thr_b  = banko_threshold if banko_threshold else CFG["banko_threshold"]
    thr_t  = CFG["tek_threshold"]
    thr_d  = CFG["double_threshold"]
    spread = CFG["kaos_spread"]

    H = entropy if entropy is not None else compute_entropy(p1, px, p2)

    # ── ADIM 1: Draw Boost — adaptif, seçici ────────────────
    # Sadece uygun senaryolarda px artır:
    # 1) Yüksek entropy (belirsiz maç)
    # 2) Lambda'lar birbirine yakın (dengeli güç)
    # 3) LPRM draw sinyali
    # → Rastgele değil, koşullu boost
    draw_boost = 1.0

    if H > 0.60:
        draw_boost *= 1.08   # belirsiz maç → draw daha olası

    if lambda_diff is not None and lambda_diff < 0.25:
        draw_boost *= 1.10   # dengeli güç → draw daha olası

    if lprm_draw_signal:
        draw_boost *= 1.08   # LPRM draw deseni tespit etti

    if draw_boost > 1.0:
        px_boosted = px * draw_boost
        total      = p1 + px_boosted + p2
        p1 /= total; px = px_boosted / total; p2 /= total

    # ── ADIM 2: Adaptif draw threshold ──────────────────────
    # Hard 0.28 değil — koşullara göre ayarlanır
    draw_thr = 0.29  # base (lig ortalamasının biraz üstü)

    if H > 0.60 and max(p1, px, p2) < 0.65:
        draw_thr = 0.27      # belirsiz + düşük güven → daha kolay X

    if lprm_draw_signal:
        draw_thr -= 0.02     # LPRM draw sinyali → threshold daha da düşür

    # Pozisyon bazlı draw threshold — position_bias.py'den (güncel veri)
    # _POS_X_DELTA kaldırıldı: position_bias modülü ile çakışıyor, çift etki yapıyordu.
    # Tek kaynak: position_bias.get_draw_thr_adjust() — toplam ±0.06 ile sınırlandırıldı.
    try:
        from model.position_bias import get_draw_thr_adjust, BANKO_SAFE_POSITIONS
        if position is not None:
            _pos_adj = get_draw_thr_adjust(position)
            if position in BANKO_SAFE_POSITIONS:
                _pos_adj += 0.04  # BANKO güvenli → X çok zorlaştır
            # Toplam pozisyon düzeltmesini ±0.06 ile sınırla (aşırı sapma önlenir)
            _pos_adj = max(-0.06, min(0.06, _pos_adj))
            draw_thr += _pos_adj
    except Exception:
        pass


    # ── ADIM 3: KAOS kalite filtresi ────────────────────────
    # Entropy eşiği yukarı → daha seçici KAOS
    # KAOS = gerçekten belirsiz, rastgele değil
    kaos_entropy_thr = 0.88  # eski 0.80 → 0.88
    kaos_conf_thr    = 0.60  # max_prob < 0.60 olmalı

    probs  = {"1": p1, "X": px, "2": p2}
    ranked = sorted(probs.items(), key=lambda x: -x[1])
    best_k, best_v = ranked[0]
    trd_v          = ranked[2][1]

    if ci_width is None:
        ci_norm = H / 1.099
    else:
        ci_norm = max(0.0, min(1.0, (ci_width - 0.002) / 0.008))

    uncertainty = H * 0.7 + ci_norm * 0.3

    if uncertainty < 0.70:
        confidence = "HIGH"
    elif uncertainty < 0.95:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    # ── Regime drift guard — recent draw rate'e göre threshold ayarla ─
    # Hafıza yoksa varsayılan.
    # Az draw dönemi  (< 0.22): draw nadir → X ZORLAŞTIR (eşik yükselt)
    # Çok draw dönemi (> 0.32): draw sık   → X KOLAYLAŞTIR (eşik düşür, devret bias)
    _recent_draw_rate = CFG.get("recent_draw_rate", 0.27)  # main.py'den geçilir
    if _recent_draw_rate < 0.22:
        draw_thr += 0.02   # az draw dönemi → X zorlaştır (düzeltildi, önceden -= 0.02 hataydı)
    elif _recent_draw_rate > 0.32:
        draw_thr -= 0.02   # çok draw rejimi → X kolaylaştır (devret bias)

    # ── SAF X ÜRETİMİ — argmax kilidini kır ────────────────
    # px hiçbir zaman argmax olamıyor çünkü ev avantajı p1 şişiriyor
    # Bu kural: sadece px gerçekten yakınsa TEK X üret
    draw_gap = abs(px - max(p1, p2))
    # Fix: px dominant ise KAOS→X hatasını önle
    if (
        px > p1 and px > p2         # px gerçekten en yüksek
        and px >= draw_thr + 0.01   # eşiği net geçiyor
        and px < 0.50               # aşırı dominant değil
    ):
        return "TEK   X", 1, False
    if (
        px >= draw_thr              # adaptif eşik geçildi
        and H > 0.60               # yeterli belirsizlik
        and max(p1, p2) < 0.55     # favori koruma
        and draw_gap < 0.08        # kritik eşik korundu
        and px > p1 and px > p2    # px en yüksek olmalı
    ):
        return "TEK   X", 1, False

    # ── Value forcing ────────────────────────────────────────
    val_outcome = None
    if value_info and value_info.get("has_value"):
        if value_info.get("edge", 0) >= 0.08:
            val_outcome = value_info["outcome"]

    if val_outcome and val_outcome != best_k:
        forced = sorted([best_k, val_outcome])
        sel = "".join(forced)
        return f"CIFT  {sel}", 2, False

    # ── ADIM 4: Px draw threshold kontrolü ──────────────────
    # Sadece uygun maçlarda X öner (boost sonrası)
    # Doğrudan X return değil — aşağıdaki ÇİFT mantığına entegre
    px_draw_eligible = (px >= draw_thr and H > 0.55)

    # ── KAOS: kaliteli filtre ────────────────────────────────
    if H > kaos_entropy_thr and best_v < kaos_conf_thr:
        return "KAOS  1X2", 3, True

    if uncertainty > 0.95 or H > 1.05:
        return "KAOS  1X2", 3, True

    if best_v - trd_v < spread:
        # Fix: dep belirsizse KAOS yerine ÇİFT 2X (dep BANKO %60 hata)
        if best_k == "2" and best_v >= thr_d:
            # Dep çok güçlü (≥BANKO eşiği) → TEK 2, zayıf → ÇİFT 2X
            if best_v >= thr_b:
                return "TEK   2", 1, False
            return "CIFT  2X", 2, False
        return "KAOS  1X2", 3, True

    # ── BANKO ────────────────────────────────────────────────
    if best_v >= thr_b and uncertainty < 0.65:
        if best_k == "2":  # Fix: dep BANKO eşik kontrolü
            # %65+ dep güçlü → TEK 2, belirsiz → ÇİFT 2X
            if best_v >= thr_t:   # thr_t=0.50 → yeterince güçlü
                return "TEK   2", 1, False
            return "CIFT  2X", 2, False
        return f"BANKO {best_k}", 1, False

    # ── Orta belirsizlik → ÇİFT + X dahil et ───────────────
    if uncertainty > 0.80 and best_v < thr_b:
        top2 = [ranked[0][0], ranked[1][0]]
        # X ekleme koşulu genişletildi (draw_thr ile)
        if "X" not in top2 and px_draw_eligible:
            non_x = [k for k in top2 if k != "X"]
            loser = min(non_x, key=lambda k: probs[k])
            top2  = [k for k in top2 if k != loser] + ["X"]
        sel = "".join(sorted(top2))
        return f"CIFT  {sel}", 2, False

    # ── Normal eşik bazlı ───────────────────────────────────
    if best_v >= thr_b:
        return f"BANKO {best_k}", 1, False

    if best_v >= thr_t:
        # ADIM 4: Yakın draw varsa TEK → ÇİFT yükselt
        if px_draw_eligible and (best_v - px) < 0.12:
            sel = "".join(sorted([best_k, "X"]))
            return f"CIFT  {sel}", 2, False
        return f"TEK   {best_k}", 1, False

    if best_v >= thr_d:
        top2 = [ranked[0][0], ranked[1][0]]
        if "X" not in top2 and px_draw_eligible:
            non_x = [k for k in top2 if k != "X"]
            loser = min(non_x, key=lambda k: probs[k])
            top2  = [k for k in top2 if k != loser] + ["X"]
        sel = "".join(sorted(top2))
        return f"CIFT  {sel}", 2, False

    return "KAOS  1X2", 3, True




def get_api_prediction(fixture_id: int) -> dict:
    """
    API-Football /predictions meta-tahmini çek.
    Cache-first, TTL=4h.
    """
    try:
        from data.api_football import APIFootball
        api = APIFootball()
        if not api.key or not fixture_id:
            return {}
        pred = api.predictions(fixture_id)
        return pred or {}
    except Exception:
        return {}


def disagreement_check(our_p1: float, our_px: float, our_p2: float,
                        fixture_id: int = None) -> str:
    """
    Kendi modelimiz ile API tahmini arasındaki uyuşmazlığı ölç.

    Kullanım:
      signal = disagreement_check(p1=0.65, px=0.20, p2=0.15,
                                   fixture_id=12345)
      # → "OK" | "KAOS_API" | "UNKNOWN"

    Eşikler:
      > 0.20 fark → KAOS_API (piyasa belirsiz veya özel bilgi var)
      0.10-0.20   → WARN
      < 0.10      → OK
    """
    if not fixture_id:
        return "UNKNOWN"

    api_pred = get_api_prediction(fixture_id)
    if not api_pred:
        return "UNKNOWN"

    try:
        api_p1 = api_pred.get("p1", 0) / 100.0
        api_px = api_pred.get("px", 0) / 100.0
        api_p2 = api_pred.get("p2", 0) / 100.0

        diff_1 = abs(our_p1 - api_p1)
        diff_x = abs(our_px - api_px)
        diff_2 = abs(our_p2 - api_p2)
        max_diff = max(diff_1, diff_x, diff_2)

        if max_diff > 0.20:
            return "KAOS_API"
        if max_diff > 0.10:
            return "WARN"
        return "OK"
    except Exception:
        return "UNKNOWN"

