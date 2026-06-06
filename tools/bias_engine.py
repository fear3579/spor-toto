"""
BİAS ENGINE — İstatistiklerden Katsayı Hesabı
===============================================
Ham pozisyon istatistiklerini (home%, draw%, away%) alıp
POSITION_LAMBDA_BIAS, POSITION_DRAW_THR_ADJUST ve kategori
setlerini otomatik olarak hesaplar.

Çağıran: update_stats.py (her hafta çalıştırılır)
Çıktı:   position_bias_generated.py (otomatik yazılır)

Mantık:
  1. 15 pozisyonun ağırlıklı ortalaması = baseline
  2. Her pozisyon için baseline'dan sapma hesaplanır
  3. Sapma eşiği aşıyorsa → bias katsayısı üretilir
  4. Bias = sapma × SCALE (0.5 — yumuşatma faktörü)
"""

from __future__ import annotations

# ─── Sabitler ─────────────────────────────────────────────────────────────────

SCALE_FACTOR    = 0.50   # Sapmanın kaçta kaçı bias'a çevrilir
MIN_DRAW_DELTA  = 0.07   # %7 sapma → X bias ekle
MIN_EV_DELTA    = 0.10   # %10 sapma → 1 (ev) bias ekle
MIN_DEP_DELTA   = 0.10   # %10 sapma → 2 (dep) bias ekle
MIN_THR_DELTA   = 0.015  # Küçük draw_thr ayarlarını atla

# Kategori eşikleri
BANKO_HOME_THR  = 52.0   # Ev > %52 AND X < %23 → BANKO
BANKO_DRAW_THR  = 23.0
HIGH_X_THR      = 35.0   # X > %35 → HIGH_X (KAOS/ÇİFT)
AWAY_DEP_THR    = 42.0   # Dep > %42 AND Ev < %42 → AWAY_STRONG
AWAY_HOME_CAP   = 42.0

MIN_SAMPLES     = 15     # Pozisyon başına minimum maç sayısı


# ─── Ağırlıklı Baseline ───────────────────────────────────────────────────────

def _compute_baseline(pos_stats: dict) -> tuple[float, float, float]:
    """
    Tüm pozisyonların ağırlıklı ortalamasını döner.
    Düşük örnekli pozisyonlar hariç tutulur.

    Returns:
        (base_home, base_draw, base_away) — [0,1] aralığında
    """
    total_w = 0
    w_home = w_draw = w_away = 0.0

    for stats in pos_stats.values():
        n = stats.get("total", 0)
        if n < MIN_SAMPLES:
            continue
        total_w += n
        w_home  += stats["home"] / 100.0 * n
        w_draw  += stats["draw"] / 100.0 * n
        w_away  += stats["away"] / 100.0 * n

    if total_w == 0:
        return 0.40, 0.28, 0.32   # genel futbol ortalaması fallback

    return w_home / total_w, w_draw / total_w, w_away / total_w


# ─── Lambda Bias ──────────────────────────────────────────────────────────────

def stats_to_lambda_bias(pos_stats: dict) -> dict[int, dict[str, float]]:
    """
    Pozisyon istatistiklerinden POSITION_LAMBDA_BIAS hesaplar.

    pos_stats formatı:
        {"1": {"home": 36.8, "draw": 21.1, "away": 42.1, "total": 19}, ...}

    Returns:
        {pos_int: {"1": delta, "X": delta, "2": delta}}
    """
    base_home, base_draw, base_away = _compute_baseline(pos_stats)
    bias: dict[int, dict[str, float]] = {}

    for p_str, stats in pos_stats.items():
        pos = int(p_str)
        n   = stats.get("total", 0)
        if n < MIN_SAMPLES:
            continue

        home = stats["home"] / 100.0
        draw = stats["draw"] / 100.0
        away = stats["away"] / 100.0

        d_home = home - base_home
        d_draw = draw - base_draw
        d_away = away - base_away

        pos_bias: dict[str, float] = {}

        if d_draw > MIN_DRAW_DELTA:
            pos_bias["X"] = round(d_draw * SCALE_FACTOR, 3)
        if d_home > MIN_EV_DELTA:
            pos_bias["1"] = round(d_home * SCALE_FACTOR, 3)
        if d_away > MIN_DEP_DELTA:
            pos_bias["2"] = round(d_away * SCALE_FACTOR, 3)

        if pos_bias:
            bias[pos] = pos_bias

    return bias


# ─── Draw Threshold Ayarı ─────────────────────────────────────────────────────

def stats_to_draw_thr(pos_stats: dict) -> dict[int, float]:
    """
    Pozisyon istatistiklerinden POSITION_DRAW_THR_ADJUST hesaplar.

    Yüksek X pozisyonlarda eşik düşer (X üretimi kolaylaşır).
    Düşük X pozisyonlarda eşik yükselir (X üretimi zorlaşır).

    Formül: adj = -(draw_rate - mean_draw) × 0.15
      Örn: #3 draw=%50, mean=%25 → adj = -(0.50-0.25)×0.15 = -0.037

    Returns:
        {pos_int: float}  (pozitif = eşik yükselir, negatif = düşer)
    """
    _, mean_draw, _ = _compute_baseline(pos_stats)
    adj: dict[int, float] = {}

    for p_str, stats in pos_stats.items():
        pos = int(p_str)
        n   = stats.get("total", 0)
        if n < MIN_SAMPLES:
            continue

        draw_rate = stats["draw"] / 100.0
        delta = -(draw_rate - mean_draw) * 0.15
        delta = round(delta, 3)

        if abs(delta) >= MIN_THR_DELTA:
            adj[pos] = delta

    return adj


# ─── Kategori Setleri ─────────────────────────────────────────────────────────

def stats_to_categories(pos_stats: dict) -> dict[str, list[int]]:
    """
    İstatistiklerden BANKO_SAFE, HIGH_X, AWAY_STRONG setlerini üretir.

    Returns:
        {"banko_safe": [...], "high_x": [...], "away_strong": [...]}
    """
    banko_safe: list[int]  = []
    high_x:     list[int]  = []
    away_strong: list[int] = []

    for p_str, stats in pos_stats.items():
        pos  = int(p_str)
        n    = stats.get("total", 0)
        if n < MIN_SAMPLES:
            continue

        home = stats["home"]
        draw = stats["draw"]
        away = stats["away"]

        if home >= BANKO_HOME_THR and draw <= BANKO_DRAW_THR:
            banko_safe.append(pos)

        if draw >= HIGH_X_THR:
            high_x.append(pos)

        if away >= AWAY_DEP_THR and home < AWAY_HOME_CAP:
            away_strong.append(pos)

    return {
        "banko_safe":   sorted(banko_safe),
        "high_x":       sorted(high_x),
        "away_strong":  sorted(away_strong),
    }


# ─── Bias Notu Üretici ────────────────────────────────────────────────────────

def generate_pos_note(pos: int, stats: dict, cats: dict) -> str:
    """Her pozisyon için insan-okunabilir not üretir."""
    home = stats["home"]
    draw = stats["draw"]
    away = stats["away"]

    if pos in cats["banko_safe"]:
        return f"✅ BANKO — ev %{home:.0f}, X %{draw:.0f}"
    if pos in cats["high_x"]:
        if draw >= 45:
            return f"🔴 X %{draw:.0f} — KAOS/ÇİFT 1X"
        return f"⚠ X yüksek %{draw:.0f} — ÇİFT 1X"
    if pos in cats["away_strong"]:
        return f"⚠ Dep güçlü %{away:.0f} — ÇİFT 2X"
    return "Normal dağılım"


# ─── Diff Hesabı ──────────────────────────────────────────────────────────────

def compute_diff(
    old_stats: dict | None,
    new_stats: dict,
    threshold: float = 3.0,
) -> list[dict]:
    """
    Eski ve yeni istatistikler arasındaki anlamlı değişiklikleri döner.

    Returns:
        [{"pos": int, "field": str, "old": float, "new": float, "delta": float}]
    """
    if old_stats is None:
        return []

    diffs = []
    old_pos = old_stats.get("position_distribution", {})
    new_pos = new_stats.get("position_distribution", {})

    for p_str in new_pos:
        if p_str not in old_pos:
            continue
        for field in ("home", "draw", "away"):
            old_v = old_pos[p_str].get(field, 0.0)
            new_v = new_pos[p_str].get(field, 0.0)
            delta = new_v - old_v
            if abs(delta) >= threshold:
                diffs.append({
                    "pos":   int(p_str),
                    "field": field,
                    "old":   old_v,
                    "new":   new_v,
                    "delta": round(delta, 1),
                })

    return sorted(diffs, key=lambda d: abs(d["delta"]), reverse=True)


# ─── Tam Pipeline ─────────────────────────────────────────────────────────────

def derive_all(pos_stats: dict) -> dict:
    """
    Tek çağrıda tüm bias değerlerini hesaplar.

    Returns:
        {
            "lambda_bias":   {pos: {outcome: delta}},
            "draw_thr":      {pos: float},
            "categories":    {"banko_safe": [...], "high_x": [...], "away_strong": [...]},
            "baseline":      {"home": float, "draw": float, "away": float},
        }
    """
    base = _compute_baseline(pos_stats)
    cats = stats_to_categories(pos_stats)
    return {
        "lambda_bias": stats_to_lambda_bias(pos_stats),
        "draw_thr":    stats_to_draw_thr(pos_stats),
        "categories":  cats,
        "baseline":    {
            "home": round(base[0] * 100, 1),
            "draw": round(base[1] * 100, 1),
            "away": round(base[2] * 100, 1),
        },
    }
