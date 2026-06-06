# AUTO-GENERATED — Elle düzenleme yapma
# Oluşturuldu  : 2026-05-31 12:02
# Kaynak        : 54 hafta, 722 saf lig maçı (milli+kupa filtrelenmiş)
# Komut         : python update_stats.py <docx_yolu>
#
# Baseline: Ev=%46.1  X=%24.5  Dep=%29.4
# Devret X oranı: %30.3  |  Normal: %18.2
from __future__ import annotations


POSITION_STATS: dict = {
    1: {"home": 54.2, "draw": 16.7, "away": 29.2, "bias": "1", "note": "✅ BANKO — ev %54, X %17"},
    2: {"home": 52.1, "draw": 20.8, "away": 27.1, "bias": "1", "note": "✅ BANKO — ev %52, X %21"},
    3: {"home": 22.4, "draw": 44.9, "away": 32.7, "bias": "X", "note": "⚠ X yüksek %45 — ÇİFT 1X"},
    4: {"home": 31.2, "draw": 22.9, "away": 45.8, "bias": "2", "note": "⚠ Dep güçlü %46 — ÇİFT 2X"},
    5: {"home": 56.2, "draw": 14.6, "away": 29.2, "bias": "1", "note": "✅ BANKO — ev %56, X %15"},
    6: {"home": 43.8, "draw": 31.2, "away": 25.0, "bias": "1", "note": "Normal dağılım"},
    7: {"home": 41.7, "draw": 27.1, "away": 31.2, "bias": "1", "note": "Normal dağılım"},
    8: {"home": 40.8, "draw": 36.7, "away": 22.4, "bias": "X", "note": "⚠ X yüksek %37 — ÇİFT 1X"},
    9: {"home": 52.1, "draw": 29.2, "away": 18.8, "bias": "1", "note": "Normal dağılım"},
    10: {"home": 42.6, "draw": 29.8, "away": 27.7, "bias": "1", "note": "Normal dağılım"},
    11: {"home": 53.2, "draw": 10.6, "away": 36.2, "bias": "1", "note": "✅ BANKO — ev %53, X %11"},
    12: {"home": 54.2, "draw": 14.6, "away": 31.2, "bias": "1", "note": "✅ BANKO — ev %54, X %15"},
    13: {"home": 53.1, "draw": 16.3, "away": 30.6, "bias": "1", "note": "✅ BANKO — ev %53, X %16"},
    14: {"home": 54.2, "draw": 10.4, "away": 35.4, "bias": "1", "note": "✅ BANKO — ev %54, X %10"},
    15: {"home": 40.8, "draw": 40.8, "away": 18.4, "bias": "X", "note": "⚠ X yüksek %41 — ÇİFT 1X"},
}

POSITION_LAMBDA_BIAS: dict[int, dict[str, float]] = {
    3: {"X": +0.102},
    4: {"2": +0.082},
    5: {"1": +0.050},
    8: {"X": +0.061},
    15: {"X": +0.081},
}

POSITION_DRAW_THR_ADJUST: dict[int, float] = {
    3: -0.031,
    5: +0.015,
    8: -0.018,
    11: +0.021,
    12: +0.015,
    14: +0.021,
    15: -0.024,
}

BANKO_SAFE_POSITIONS: set[int] = {1, 2, 5, 11, 12, 13, 14}

HIGH_X_POSITIONS: set[int] = {3, 8, 15}

AWAY_STRONG_POSITIONS: set[int] = {4}
