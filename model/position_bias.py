"""
POZİSYON BAZLI SONUÇ DAĞILIMI & TAKIM POZİSYON ANALİZİ
=========================================================
Katsayılar iki kaynaktan yüklenir (öncelik sırası):
  1. position_bias_generated.py  ← update_stats.py her hafta otomatik günceller
  2. Bu dosyadaki hardcoded değerler  ← generated yoksa fallback

Entegrasyon:
  lambda_calc.py → Katman 7 olarak ekle (get_position_bias)
  suggest.py     → draw_thr pozisyon bazlı ayarla (get_draw_thr_adjust)
  config.py      → POSITION_STATS sabitini buradan import et

Güncelleme:
  python update_stats.py <docx_yolu>
  → position_bias_generated.py otomatik yazılır
  → Bir sonraki import'ta yeni katsayılar aktif olur
"""

from __future__ import annotations
from typing import TypedDict


# ─── Dinamik Yükleme — Generated Dosya ───────────────────────────────────────
#
# update_stats.py çalıştırılınca position_bias_generated.py oluşur.
# Bu blok onu yüklemeyi dener; başarısız olursa hardcoded fallback kullanılır.

_SOURCE = "hardcoded (fallback)"

try:
    from model.position_bias_generated import (    # type: ignore[import]
        POSITION_STATS        as _GEN_STATS,
        POSITION_LAMBDA_BIAS  as _GEN_LAMBDA,
        POSITION_DRAW_THR_ADJUST as _GEN_THR,
        BANKO_SAFE_POSITIONS  as _GEN_BANKO,
        HIGH_X_POSITIONS      as _GEN_HIGH_X,
        AWAY_STRONG_POSITIONS as _GEN_AWAY,
    )
    _SOURCE              = "generated (auto-updated)"
    _STATS_LOADED        = _GEN_STATS
    _LAMBDA_LOADED       = _GEN_LAMBDA
    _THR_LOADED          = _GEN_THR
    _BANKO_LOADED        = set(_GEN_BANKO)
    _HIGH_X_LOADED       = set(_GEN_HIGH_X)
    _AWAY_LOADED         = set(_GEN_AWAY)
except ImportError:
    _STATS_LOADED  = None
    _LAMBDA_LOADED = None
    _THR_LOADED    = None
    _BANKO_LOADED  = None
    _HIGH_X_LOADED = None
    _AWAY_LOADED   = None


# ─── Tip Tanımları ────────────────────────────────────────────────────────────

class PosStats(TypedDict):
    home: float
    draw: float
    away: float
    bias: str
    note: str


# ─── Hardcoded Fallback Değerleri ─────────────────────────────────────────────
# Kaynak: 25 hafta, 294 saf LİG maçı (milli+kupa filtrelenmiş) — 08.05.2026
# Bu değerler update_stats.py ilk kez çalıştırılana kadar kullanılır.

_FALLBACK_POSITION_STATS: dict[int, PosStats] = {
    1:  {"home": 36.8, "draw": 21.1, "away": 42.1, "bias": "2",  "note": "⚠ Dep güçlü — ÇİFT 2X"},
    2:  {"home": 47.4, "draw": 15.8, "away": 36.8, "bias": "1",  "note": "Ev favorisi, X az"},
    3:  {"home": 40.0, "draw": 50.0, "away": 10.0, "bias": "X",  "note": "🔴 EN FAZLA X (%50!) — KAOS/ÇİFT 1X"},
    4:  {"home": 27.8, "draw": 38.9, "away": 33.3, "bias": "X",  "note": "⚠ X yüksek, Dep güçlü — ÇİFT 2X"},
    5:  {"home": 47.4, "draw": 21.1, "away": 31.6, "bias": "1",  "note": "Ev güçlü"},
    6:  {"home": 25.0, "draw": 45.0, "away": 30.0, "bias": "X",  "note": "🔴 X oranı çok yüksek (%45!) — ÇİFT 1X"},
    7:  {"home": 31.6, "draw": 26.3, "away": 42.1, "bias": "2",  "note": "⚠ Dep güçlü — ÇİFT 2X"},
    8:  {"home": 63.2, "draw": 21.1, "away": 15.8, "bias": "1",  "note": "✓ Ev baskın — BANKO 1"},
    9:  {"home": 55.0, "draw": 20.0, "away": 25.0, "bias": "1",  "note": "✓ Ev güvenli — BANKO 1"},
    10: {"home": 40.0, "draw": 30.0, "away": 30.0, "bias": "1",  "note": "X orta — ÇİFT 1X"},
    11: {"home": 42.1, "draw": 10.5, "away": 47.4, "bias": "2",  "note": "⚠ Dep güçlü (%47) — ÇİFT 2X"},
    12: {"home": 57.1, "draw":  9.5, "away": 33.3, "bias": "1",  "note": "✓ En güvenli BANKO — X çok az (%9)"},
    13: {"home": 47.6, "draw": 19.0, "away": 33.3, "bias": "1",  "note": "Ev favorisi"},
    14: {"home": 65.0, "draw": 10.0, "away": 25.0, "bias": "1",  "note": "✅ EN GÜVENLİ BANKO — %65 ev, %10 X"},
    15: {"home": 45.0, "draw": 30.0, "away": 25.0, "bias": "1",  "note": "X orta — ÇİFT 1X"},
}

_FALLBACK_LAMBDA_BIAS: dict[int, dict[str, float]] = {
    3:  {"X": +0.070},
    4:  {"X": +0.050, "2": +0.020},
    6:  {"X": +0.060},
    8:  {"1": +0.040},
    9:  {"1": +0.030},
    11: {"2": +0.040},
    12: {"1": +0.040},
    14: {"1": +0.060},
    1:  {"2": +0.030},
    7:  {"2": +0.030},
}

_FALLBACK_DRAW_THR: dict[int, float] = {
    3:  -0.037,
    6:  -0.030,
    4:  -0.021,
    10: -0.008,
    12: +0.023,
    14: +0.023,
    2:  +0.014,
    11: +0.021,
}

_FALLBACK_BANKO  = {8, 9, 12, 14}
_FALLBACK_HIGH_X = {3, 4, 6}
_FALLBACK_AWAY   = {1, 7, 11}


# ─── Aktif Değerler (Generated veya Fallback) ─────────────────────────────────

POSITION_STATS        = _STATS_LOADED  if _STATS_LOADED  is not None else _FALLBACK_POSITION_STATS
POSITION_LAMBDA_BIAS  = _LAMBDA_LOADED if _LAMBDA_LOADED is not None else _FALLBACK_LAMBDA_BIAS
POSITION_DRAW_THR_ADJUST = _THR_LOADED if _THR_LOADED   is not None else _FALLBACK_DRAW_THR
BANKO_SAFE_POSITIONS  = _BANKO_LOADED  if _BANKO_LOADED  is not None else _FALLBACK_BANKO
HIGH_X_POSITIONS      = _HIGH_X_LOADED if _HIGH_X_LOADED is not None else _FALLBACK_HIGH_X
AWAY_STRONG_POSITIONS = _AWAY_LOADED   if _AWAY_LOADED   is not None else _FALLBACK_AWAY


# ─── Takım Pozisyon Analizi (25 hafta verisi) ─────────────────────────────────

TEAM_POSITION_STATS: dict[str, dict[int, dict[str, float]]] = {
    "GALATASARAY": {
        5:  {"win": 89, "draw":  0, "loss": 11, "sample": 9,  "signal": "BANKO 1"},
        4:  {"win": 67, "draw": 17, "loss": 17, "sample": 6,  "signal": "BANKO 1"},
        1:  {"win":100, "draw":  0, "loss":  0, "sample": 4,  "signal": "BANKO 1"},
    },
    "FENERBAHCE": {
        8:  {"win": 67, "draw": 33, "loss":  0, "sample": 9,  "signal": "ÇİFT 1X"},
        6:  {"win": 60, "draw":  0, "loss": 40, "sample": 5,  "signal": "ÇİFT 1X"},
        7:  {"win": 75, "draw":  0, "loss": 25, "sample": 4,  "signal": "BANKO 1"},
    },
    "BESIKTAS": {
        8:  {"win": 50, "draw": 25, "loss": 25, "sample": 8,  "signal": "ÇİFT 1X"},
        4:  {"win":100, "draw":  0, "loss":  0, "sample": 6,  "signal": "BANKO 1"},
        7:  {"win": 50, "draw": 25, "loss": 25, "sample": 4,  "signal": "ÇİFT"},
    },
    "TRABZONSPOR": {
        9:  {"win": 38, "draw": 38, "loss": 25, "sample": 8,  "signal": "KAOS 1X2"},
        3:  {"win": 50, "draw": 50, "loss":  0, "sample": 6,  "signal": "ÇİFT 1X"},
        5:  {"win": 75, "draw":  0, "loss": 25, "sample": 4,  "signal": "BANKO 1"},
    },
}

# Takım ismi eşleştirme (fuzzy match için alias)
TEAM_ALIASES: dict[str, str] = {
    "GS":           "GALATASARAY",
    "GALATA":       "GALATASARAY",
    "FB":           "FENERBAHCE",
    "FENER":        "FENERBAHCE",
    "FENERBAHÇE":   "FENERBAHCE",
    "BJK":          "BESIKTAS",
    "BEŞİKTAŞ":     "BESIKTAS",
    "BEŞIKTAŞ":     "BESIKTAS",
    "TS":           "TRABZONSPOR",
    "TRABZON":      "TRABZONSPOR",
}


# ─── Fonksiyonlar ─────────────────────────────────────────────────────────────

def get_position_bias(position: int) -> dict[str, float]:
    """
    Verilen pozisyon için lambda bias değerlerini döner.
    Değerler: {"1": delta, "X": delta, "2": delta}

    Kullanım (lambda_calc.py — Katman 8):
        bias = get_position_bias(match.position)
        p1 += bias.get("1", 0)
        px += bias.get("X", 0)
        p2 += bias.get("2", 0)
        total = p1 + px + p2
        p1, px, p2 = p1/total, px/total, p2/total
    """
    return POSITION_LAMBDA_BIAS.get(position, {})


def get_draw_thr_adjust(position: int) -> float:
    """
    Pozisyona göre draw threshold düzeltmesi (suggest.py için).
    Pozitif → eşik yükselir (daha zor X üret)
    Negatif → eşik düşer (daha kolay X üret)
    """
    return POSITION_DRAW_THR_ADJUST.get(position, 0.0)


def get_team_position_signal(team_name: str, position: int) -> dict | None:
    """
    Takım + pozisyon kombinasyonu için tarihsel sinyal döner.

    Returns:
        {"win": %, "draw": %, "loss": %, "sample": n, "signal": str}
        veya None (veri yoksa)
    """
    canonical = TEAM_ALIASES.get(team_name.upper(), team_name.upper())
    team_data = TEAM_POSITION_STATS.get(canonical)
    if team_data is None:
        return None
    return team_data.get(position)


def suggest_from_position(position: int, team_name: str | None = None) -> str:
    """
    Pozisyon (+ isteğe bağlı takım) bazlı öneri üretir.

    Returns:
        "BANKO 1", "ÇİFT 1X", "KAOS", "ÇİFT 2X" gibi öneri metni
    """
    # Önce takım-pozisyon kontrolü (daha spesifik)
    if team_name:
        tp = get_team_position_signal(team_name, position)
        if tp and tp["sample"] >= 5:
            return tp["signal"]

    # Genel pozisyon istatistiğine dön
    stats = POSITION_STATS.get(position)
    if stats is None:
        return "TEK"

    if position in BANKO_SAFE_POSITIONS:
        return "BANKO 1"
    if position in HIGH_X_POSITIONS:
        return "ÇİFT 1X" if position != 15 else "KAOS"
    if position in AWAY_STRONG_POSITIONS:
        return "ÇİFT 2X"
    return "TEK"


def print_position_hud(position: int, team_name: str | None = None) -> None:
    """HUD: Pozisyon istatistiklerini terminale yazar."""
    stats = POSITION_STATS.get(position)
    if stats is None:
        return

    print(f"\n📍 POZİSYON #{position}: {stats['note']}")
    print(f"   Tarihsel → 1:%{stats['home']:.1f}  X:%{stats['draw']:.1f}  2:%{stats['away']:.1f}")
    print(f"   Öneri    → {suggest_from_position(position, team_name)}")

    if team_name:
        tp = get_team_position_signal(team_name, position)
        if tp:
            conf = "✅" if tp["sample"] >= 8 else ("⚠" if tp["sample"] >= 5 else "🔵")
            print(f"   {team_name} #{position}: W%{tp['win']} D%{tp['draw']} L%{tp['loss']} "
                  f"({tp['sample']} maç) {conf} → {tp['signal']}")
