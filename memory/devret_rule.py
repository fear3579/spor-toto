# -*- coding: utf-8 -*-
"""
memory/devret_rule.py — Devret Hafta Kural Motoru
===================================================
Devret haftasını tespit eder ve sisteme bildirir.

Entegrasyon:
  main.py → Adım 5 (devret_adj hesabı)
  suggest.py → draw_thr boost
  lambda_calc.py → recent_draw_rate boost
"""

from __future__ import annotations


def get_devret_adjustment(mem_obj, week_id: str = "") -> dict:
    """
    Mevcut hafta devret haftasıysa boost değerlerini döner.

    Returns:
        {
          "devret_haftasi": bool,
          "x_bias_boost":   float,  # recent_draw_rate eklenecek
          "kaos_spread_mult": float, # kaos_spread çarpanı
          "banko_thr_add":  float,  # banko_threshold ekleme
          "beklenen_x":     float,  # kaç X bekleniyor
          "_tag":           str,    # log etiketi
        }
    """
    try:
        status = mem_obj.get_devret_status()
    except Exception:
        status = {"devret_haftasi": False}

    if not status.get("devret_haftasi", False):
        return {
            "devret_haftasi": False,
            "x_bias_boost":   0.0,
            "kaos_spread_mult": 1.0,
            "banko_thr_add":  0.0,
            "beklenen_x":     3.9,
            "_tag":           "",
        }

    return {
        "devret_haftasi":   True,
        "x_bias_boost":     0.05,   # recent_draw_rate += 0.05
        "kaos_spread_mult": 1.30,   # KAOS eşiği %30 genişler
        "banko_thr_add":    0.03,   # BANKO daha az (eşik yükselir)
        "beklenen_x":       status.get("beklenen_x", 15.8),
        "_tag":             "DEVRET HAFTASI",
    }


def get_devret_adjustments(mem_obj, week_id: str = "") -> dict:
    """
    Alias — main.py get_devret_adjustments (çoğul) çağırıyor.
    banko_thr_boost anahtarı da eklenir (main.py uyumu).
    """
    result = get_devret_adjustment(mem_obj, week_id)
    result["banko_thr_boost"] = result.get("banko_thr_add", 0.0)
    return result


# Sabit — analysis_menu.py ve ab_test.py DEVRET_ADJUSTMENTS import ediyor.
DEVRET_ADJUSTMENTS = {
    "x_bias_boost":     0.04,
    "kaos_spread_mult": 1.30,
    "banko_thr_boost":  0.03,
    "banko_thr_add":    0.03,
    "beklenen_x":       15.8,
}


def print_devret_status(mem_obj, week_id: str = "") -> None:
    """
    Devret durumu özeti.
    FIX: main.py 2 argüman geçiriyor — week_id parametresi eklendi.
    """
    try:
        status = mem_obj.get_devret_status()
        if status["devret_haftasi"]:
            print(f"  🔴 DEVRET HAFTASI — Beklenen X: ~{status['beklenen_x']:.0f}")
            print(f"     X bias artırıldı | KAOS eşiği genişledi | BANKO azaldı")
        else:
            print(f"  ✅ Normal hafta — Beklenen X: ~{status.get('beklenen_x',3.9):.0f}")
        prev = status.get("onceki_hafta", "")
        if prev:
            print(f"     Önceki hafta: {prev}")
    except Exception as e:
        print(f"  Devret durumu alınamadı: {e}")
