# -*- coding: utf-8 -*-
"""
Not: main.py artık LPRM v3 kullanıyor (get_lprm_v3_result).
v2 sadece fallback olarak kalıyor.

analysis/lprm_report.py
========================
LPRM'in gerçekten katkı sağlayıp sağlamadığını
otomatik ve ölçülebilir biçimde test eder.

Mantık:
  A) LPRM kapalı → olasılıklar
  B) LPRM açık   → olasılıklar
  → Brier, LogLoss, Accuracy, CLV karşılaştırması
  → Bootstrap güven aralığı
  → "Güvenilir / Sınırlı / Zararlı / Nötr" verdict

Kullanım:
  from analysis.lprm_report import generate_lprm_report, print_lprm_report
  report = generate_lprm_report(matches, predict_fn)
  print_lprm_report(report)
"""

import numpy as np
from typing import List, Dict, Callable, Tuple

# ── Metrikler ────────────────────────────────────────────────

def brier_score(y_true: np.ndarray, probs: np.ndarray) -> float:
    """Multi-class Brier Score. y_true: (N,) 0/1/2, probs: (N,3)"""
    N = len(y_true)
    one_hot = np.zeros_like(probs)
    one_hot[np.arange(N), y_true] = 1
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1) / 3))


def log_loss(y_true: np.ndarray, probs: np.ndarray,
             eps: float = 1e-15) -> float:
    """Multi-class Log Loss."""
    probs = np.clip(probs, eps, 1 - eps)
    return float(-np.mean(np.log(probs[np.arange(len(y_true)), y_true])))


def accuracy(y_true: np.ndarray, probs: np.ndarray) -> float:
    """Sınıflandırma doğruluğu."""
    preds = np.argmax(probs, axis=1)
    return float(np.mean(preds == y_true))


def compute_clv(probs: np.ndarray,
                odds: np.ndarray) -> Tuple[float, float]:
    """
    Closing Line Value (CLV).
    Model olasılığı ile piyasa implied olasılığı farkı.
    Pozitif CLV → model piyasanın önünde.

    odds: (N,3) — [o1, ox, o2]
    Döner: (avg_clv, positive_rate)
    """
    implied = 1.0 / odds
    implied = implied / implied.sum(axis=1, keepdims=True)
    diff = probs - implied
    return float(np.mean(diff)), float(np.mean(diff > 0))


def rps_score(y_true: np.ndarray, probs: np.ndarray) -> float:
    """
    Ranked Probability Score — olasılık sıralaması kalitesi.
    Brier'den daha hassas futbol metriği.
    Düşük = iyi.
    """
    N = len(y_true)
    rps_vals = []
    for i in range(N):
        y = y_true[i]
        p = probs[i]
        cumP = np.cumsum(p)
        cumY = np.cumsum([1 if j == y else 0 for j in range(3)])
        rps_vals.append(np.mean((cumP - cumY) ** 2))
    return float(np.mean(rps_vals))


# ── Bootstrap ────────────────────────────────────────────────

def bootstrap_diff(metric_fn, y: np.ndarray,
                   pA: np.ndarray, pB: np.ndarray,
                   n_iter: int = 1000,
                   seed: int = 42) -> Tuple[float, Tuple[float, float]]:
    """
    A ve B arasındaki metrik farkı için bootstrap dağılımı.
    Döner: (mean_diff, (lower_95, upper_95))
    """
    rng = np.random.default_rng(seed)
    N = len(y)
    diffs = []
    for _ in range(n_iter):
        idx = rng.integers(0, N, N)
        mA  = metric_fn(y[idx], pA[idx])
        mB  = metric_fn(y[idx], pB[idx])
        diffs.append(mB - mA)
    diffs = np.array(diffs)
    return (float(np.mean(diffs)),
            (float(np.percentile(diffs, 2.5)),
             float(np.percentile(diffs, 97.5))))


# ── Yorum Motoru ─────────────────────────────────────────────

def _verdict(brier_delta: float, ci: Tuple[float, float],
             logloss_delta: float, acc_delta: float) -> str:
    """
    Metriklere göre LPRM katkı yorumu üret.
    brier_delta < 0 → LPRM iyileştiriyor (düşük = iyi)
    """
    ci_l, ci_u = ci

    if brier_delta < 0 and ci_u < 0:
        return ("✅ LPRM GÜVENİLİR — "
                "İstatistiksel olarak anlamlı iyileşme "
                f"(Brier Δ={brier_delta:+.4f}, CI tamamen negatif)")
    elif brier_delta < 0 and logloss_delta < 0:
        return ("🟡 LPRM FAYDALI — "
                "Brier ve LogLoss iyileşti fakat "
                f"güven aralığı belirsiz (CI: {ci_l:.4f}..{ci_u:.4f})")
    elif brier_delta < 0:
        return ("🟡 LPRM SINIRLI — "
                "Brier hafif iyileşti ama diğer metrikler karışık")
    elif brier_delta > 0.002:
        return ("❌ LPRM ZARARLI — "
                f"Modeli bozuyor (Brier Δ={brier_delta:+.4f})")
    else:
        return ("⚪ LPRM NÖTR — "
                "Anlamlı katkı yok, lambda düzeltmesi sıfıra yakın")


# ── Ana Rapor ────────────────────────────────────────────────

def generate_lprm_report(matches: List[Dict],
                         predict_fn: Callable,
                         use_odds: bool = True,
                         n_bootstrap: int = 1000) -> Dict:
    """
    LPRM ON vs OFF karşılaştırma raporu.

    matches: list of dict, her biri:
      {
        "features": ...,   # predict_fn'e geçilecek veri
        "y": 0/1/2,        # 0=H, 1=D, 2=A
        "odds": [o1,ox,o2] # bahis oranları (CLV için)
      }

    predict_fn(features, use_lprm: bool) -> np.array([p1, px, p2])

    Döner: dict (brier, logloss, accuracy, rps, clv, bootstrap, verdict)
    """
    if not matches:
        return {"error": "Maç listesi boş"}

    y_true    = []
    probs_off = []
    probs_on  = []
    odds_list = []

    for m in matches:
        y_true.append(m["y"])
        p_off = np.array(predict_fn(m["features"], use_lprm=False))
        p_on  = np.array(predict_fn(m["features"], use_lprm=True))
        probs_off.append(p_off)
        probs_on.append(p_on)
        if use_odds and "odds" in m:
            odds_list.append(m["odds"])

    y_true    = np.array(y_true,    dtype=int)
    probs_off = np.array(probs_off, dtype=float)
    probs_on  = np.array(probs_on,  dtype=float)

    # Normalize (toplamı 1 garantile)
    probs_off = probs_off / probs_off.sum(axis=1, keepdims=True)
    probs_on  = probs_on  / probs_on.sum(axis=1, keepdims=True)

    # ── Metrikler ───────────────────────────────────────────
    brier_off = brier_score(y_true, probs_off)
    brier_on  = brier_score(y_true, probs_on)

    log_off   = log_loss(y_true, probs_off)
    log_on    = log_loss(y_true, probs_on)

    acc_off   = accuracy(y_true, probs_off)
    acc_on    = accuracy(y_true, probs_on)

    rps_off   = rps_score(y_true, probs_off)
    rps_on    = rps_score(y_true, probs_on)

    result = {
        "n_matches": len(matches),
        "brier":   {"off": brier_off,  "on": brier_on,
                    "delta": brier_on - brier_off},
        "logloss": {"off": log_off,    "on": log_on,
                    "delta": log_on - log_off},
        "accuracy":{"off": acc_off,    "on": acc_on,
                    "delta": acc_on - acc_off},
        "rps":     {"off": rps_off,    "on": rps_on,
                    "delta": rps_on - rps_off},
    }

    # ── CLV ─────────────────────────────────────────────────
    if use_odds and odds_list:
        odds_arr = np.array(odds_list, dtype=float)
        clv_off  = compute_clv(probs_off, odds_arr)
        clv_on   = compute_clv(probs_on,  odds_arr)
        result["clv"] = {
            "off_avg":      round(clv_off[0], 5),
            "on_avg":       round(clv_on[0],  5),
            "off_pos_rate": round(clv_off[1], 3),
            "on_pos_rate":  round(clv_on[1],  3),
            "delta_avg":    round(clv_on[0] - clv_off[0], 5),
        }

    # ── Bootstrap ───────────────────────────────────────────
    b_mean, b_ci = bootstrap_diff(
        brier_score, y_true, probs_off, probs_on, n_bootstrap)
    result["bootstrap"] = {
        "brier_mean_diff": round(b_mean, 5),
        "ci_95":           (round(b_ci[0], 5), round(b_ci[1], 5)),
        "significant":     b_ci[1] < 0,  # CI tamamen negatif = anlamlı
    }

    # ── Pozisyon bazlı analiz ────────────────────────────────
    # KAOS maçlar ayrı (y hem 0 hem 2 yakın problu)
    entropy_vals = [-sum(p * np.log(p + 1e-9) for p in probs_on[i])
                    for i in range(len(y_true))]
    high_ent_idx = [i for i, e in enumerate(entropy_vals) if e > 1.0]
    low_ent_idx  = [i for i, e in enumerate(entropy_vals) if e <= 1.0]

    if high_ent_idx:
        he = np.array(high_ent_idx)
        result["kaos_matches"] = {
            "n": len(he),
            "brier_off": round(brier_score(y_true[he], probs_off[he]), 4),
            "brier_on":  round(brier_score(y_true[he], probs_on[he]),  4),
        }
    if low_ent_idx:
        le = np.array(low_ent_idx)
        result["normal_matches"] = {
            "n": len(le),
            "brier_off": round(brier_score(y_true[le], probs_off[le]), 4),
            "brier_on":  round(brier_score(y_true[le], probs_on[le]),  4),
        }

    # ── Verdict ─────────────────────────────────────────────
    result["verdict"] = _verdict(
        result["brier"]["delta"],
        b_ci,
        result["logloss"]["delta"],
        result["accuracy"]["delta"],
    )

    return result


# ── Yazdırma ────────────────────────────────────────────────

def print_lprm_report(report: Dict):
    """LPRM rapor çıktısını formatla ve yazdır."""
    if "error" in report:
        print(f"  Hata: {report['error']}")
        return

    n = report.get("n_matches", "?")
    print(f"\n{'='*55}")
    print(f"  LPRM RAPORU  ({n} maç)")
    print(f"{'='*55}")

    # Metrikler
    metrics = [
        ("Brier",    "brier",    True,   4),  # düşük iyi
        ("LogLoss",  "logloss",  True,   4),  # düşük iyi
        ("Accuracy", "accuracy", False,  3),  # yüksek iyi
        ("RPS",      "rps",      True,   4),  # düşük iyi
    ]
    print(f"\n  {'Metrik':<12} {'LPRM-OFF':>10} {'LPRM-ON':>10} {'Δ':>8}  Yorum")
    print(f"  {'─'*52}")
    for label, key, lower_better, dec in metrics:
        d = report[key]
        off = round(d["off"], dec)
        on  = round(d["on"], dec)
        dlt = round(d["delta"], dec)
        if lower_better:
            # _verdict() ile aynı eşik: 0.002 → tutarlı
            good = "✅" if dlt < 0 else ("❌" if dlt > 0.002 else "⚪")
        else:
            good = "✅" if dlt > 0 else ("❌" if dlt < -0.002 else "⚪")
        print(f"  {label:<12} {off:>10} {on:>10} {dlt:>+8}  {good}")

    # CLV
    if "clv" in report:
        c = report["clv"]
        print(f"\n  CLV (Closing Line Value):")
        print(f"    OFF: {c['off_avg']:+.5f}  (pozitif oran: %{c['off_pos_rate']*100:.0f})")
        print(f"    ON : {c['on_avg']:+.5f}  (pozitif oran: %{c['on_pos_rate']*100:.0f})")
        delta_icon = "✅" if c["delta_avg"] > 0 else "❌"
        print(f"    Δ  : {c['delta_avg']:+.5f}  {delta_icon}")

    # Bootstrap
    bs = report["bootstrap"]
    ci = bs["ci_95"]
    sig = "✅ Anlamlı" if bs["significant"] else "⚠ Belirsiz"
    print(f"\n  Bootstrap (1000 iter):")
    print(f"    Ortalama Brier Δ : {bs['brier_mean_diff']:+.5f}")
    print(f"    %95 CI           : [{ci[0]:+.5f}, {ci[1]:+.5f}]")
    print(f"    İstatistiksel    : {sig}")

    # KAOS vs Normal
    if "kaos_matches" in report:
        k = report["kaos_matches"]
        kdlt = round(k["brier_on"] - k["brier_off"], 4)
        print(f"\n  KAOS maçlar ({k['n']} adet)  Brier Δ: {kdlt:+.4f} "
              f"{'✅' if kdlt < 0 else '❌'}")
    if "normal_matches" in report:
        nm = report["normal_matches"]
        ndlt = round(nm["brier_on"] - nm["brier_off"], 4)
        print(f"  Normal maçlar ({nm['n']} adet)  Brier Δ: {ndlt:+.4f} "
              f"{'✅' if ndlt < 0 else '❌'}")

    # Verdict
    print(f"\n  SONUÇ:")
    print(f"  {report['verdict']}")
    print(f"{'='*55}\n")
