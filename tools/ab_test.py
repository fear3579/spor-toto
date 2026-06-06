"""
A/B TEST ÇERÇEVESI — Devret ON/OFF & Pozisyon ON/OFF
=====================================================
Bölüm 8 ve 9'dan plan:

  A) Devret OFF → Normal tahmin
  B) Devret ON  → X bias artırılmış (kaos_spread *1.30, x_bias +0.05)

  A) Pozisyon OFF → Normal lambda
  B) Pozisyon ON  → POSITION_LAMBDA_BIAS Katman 7 uygulanmış

Kullanım:
  lprm_report.py içinde:
      results = run_ab_test(matches, predict_fn)
      print_ab_report(results)

  Veya tek başına test etmek için:
      python ab_test.py
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable


# ─── Veri Yapıları ────────────────────────────────────────────────────────────

@dataclass
class MatchInput:
    """Tek bir maçın giriş verisi."""
    match_id:   str
    position:   int           # 1-15
    home_team:  str
    away_team:  str
    odds_home:  float
    odds_draw:  float
    odds_away:  float
    result:     str | None    # "1", "X", "2" — test için gerçek sonuç
    week_id:    str           # "ST40-2526" (Spor Toto resmi hafta)
    is_devret:  bool = False  # Hafta devret haftası mı?
    stored_p1:  float = 0.0  # Kayıtlı P1 (Menü 1 tahmini)
    stored_px:  float = 0.0  # Kayıtlı PX
    stored_p2:  float = 0.0  # Kayıtlı P2
    league_code: str = ""    # "T1", "E0" vb.


@dataclass
class Prediction:
    """Tek tahmin çıktısı."""
    p1: float   # ev olasılığı
    px: float   # beraberlik olasılığı
    p2: float   # deplasman olasılığı
    suggestion: str  # "BANKO 1", "ÇİFT 1X", "KAOS", "TEK", ...


@dataclass
class ABMetrics:
    """Bir senaryo (ON veya OFF) için metrik özeti."""
    label:          str
    n:              int   = 0
    correct:        int   = 0   # kupon kapsama
    argmax_correct: int   = 0   # saf argmax
    brier:          float = 0.0
    log_loss:       float = 0.0
    x_suggested:    int   = 0   # X üretilen tahmin sayısı
    banko_count:    int   = 0
    kaos_count:     int   = 0
    double_count:   int   = 0

    def accuracy(self) -> float:
        return round(self.correct / self.n * 100, 1) if self.n else 0.0

    def avg_brier(self) -> float:
        return round(self.brier / self.n, 4) if self.n else 0.0

    def avg_log_loss(self) -> float:
        return round(self.log_loss / self.n, 4) if self.n else 0.0


# ─── Metrik Hesabı ────────────────────────────────────────────────────────────

import math

def _norm_result(r: str) -> str:
    """H/D/A ve 0 → 1/X/2 normalize."""
    return {"H":"1","D":"X","A":"2","0":"X"}.get(r, r)

def _brier(p1: float, px: float, p2: float, result: str) -> float:
    r = _norm_result(result)
    actual = {"1": (1, 0, 0), "X": (0, 1, 0), "2": (0, 0, 1)}.get(r, (0, 0, 0))
    # /3 ile normalize — lprm_report.py ve main.py backtest ile tutarlı
    return ((p1 - actual[0])**2 + (px - actual[1])**2 + (p2 - actual[2])**2) / 3

def _log_loss(p1: float, px: float, p2: float, result: str) -> float:
    eps = 1e-9
    r = _norm_result(result)
    p = {"1": p1, "X": px, "2": p2}.get(r, eps)
    return -math.log(max(p, eps))

def _correct(suggestion: str, result: str) -> bool:
    """Kupon kapsama: tahmin setinde actual var mı?"""
    r = _norm_result(result)
    s = suggestion.upper()
    parts = s.split()
    outcome = parts[-1] if parts else ""
    if r == "1":
        return "1" in outcome or "BANKO" in s
    if r == "X":
        return "X" in outcome or "KAOS" in s
    if r == "2":
        return "2" in outcome or "KAOS" in s
    return False


def _argmax_correct(p1: float, px: float, p2: float, result: str) -> bool:
    """Saf argmax doğruluk: en yüksek olasılık sonuçla eşleşiyor mu?"""
    argmax = ("1" if p1 >= px and p1 >= p2 else
              ("X" if px >= p2 else "2"))
    return argmax == _norm_result(result)


# ─── Ana Test Fonksiyonu ──────────────────────────────────────────────────────

PredictFn = Callable[[MatchInput, bool, bool], Prediction]
"""
predict_fn(match, devret_on, position_on) → Prediction

Gerçek sistemde bu = suggest() wrapper'ı.
Test için basit mock veya gerçek lambda_calc çıktısı.
"""


def run_ab_test(
    matches: list[MatchInput],
    predict_fn: PredictFn,
) -> dict[str, ABMetrics]:
    """
    4 senaryo için A/B testi çalıştırır:
      "devret_off_pos_off" — Baseline
      "devret_on_pos_off"  — Sadece devret
      "devret_off_pos_on"  — Sadece pozisyon
      "devret_on_pos_on"   — Her ikisi de açık

    Returns:
        {senaryo_adı: ABMetrics}
    """
    scenarios: dict[str, tuple[bool, bool]] = {
        "devret_off__pos_off": (False, False),
        "devret_on___pos_off": (True,  False),
        "devret_off__pos_on":  (False, True),
        "devret_on___pos_on":  (True,  True),
    }

    results: dict[str, ABMetrics] = {
        k: ABMetrics(label=k) for k in scenarios
    }

    for match in matches:
        if match.result is None:
            continue

        for key, (devret_on, pos_on) in scenarios.items():
            pred = predict_fn(match, devret_on, pos_on)
            m = results[key]
            m.n += 1
            m.brier    += _brier(pred.p1, pred.px, pred.p2, match.result)
            m.log_loss += _log_loss(pred.p1, pred.px, pred.p2, match.result)
            if _correct(pred.suggestion, match.result):
                m.correct += 1
            if _argmax_correct(pred.p1, pred.px, pred.p2, match.result):
                m.argmax_correct += 1
            if "X" in pred.suggestion.upper() or "KAOS" in pred.suggestion.upper():
                m.x_suggested += 1
            if "BANKO" in pred.suggestion.upper():
                m.banko_count += 1
            if "KAOS" in pred.suggestion.upper():
                m.kaos_count += 1
            if "ÇİFT" in pred.suggestion or "CIFT" in pred.suggestion.upper():
                m.double_count += 1

    return results


def print_ab_report(results: dict[str, ABMetrics]) -> None:
    """A/B test sonuçlarını terminale yazar."""
    print(f"\n{'='*70}")
    print("  A/B TEST RAPORU — Devret ON/OFF × Pozisyon ON/OFF")
    print(f"{'='*70}")
    print(f"  {'Senaryo':<25} {'Acc%':>6} {'Brier':>8} {'LogL':>8}"
          f"  {'X-öner':>6}  {'BANKO':>5}  {'KAOS':>5}")
    print(f"  {'-'*65}")

    baseline = None
    for key, m in results.items():
        tag = ""
        if "off__pos_off" in key:
            tag = " ← BASELINE"
            baseline = m
        elif baseline:
            acc_delta = m.accuracy() - baseline.accuracy()
            brier_delta = m.avg_brier() - baseline.avg_brier()
            tag = f"  Δacc={acc_delta:+.1f}% Δbrier={brier_delta:+.4f}"

        label = key.replace("devret_", "D").replace("_pos_", "/P").replace("__", "")
        print(f"  {label:<25} {m.accuracy():>6.1f} {m.avg_brier():>8.4f} "
              f"{m.avg_log_loss():>8.4f}  {m.x_suggested:>6}  {m.banko_count:>5}"
              f"  {m.kaos_count:>5}{tag}")

    print(f"\n  Toplam maç: {next(iter(results.values())).n}")
    print(f"\n  Sonuç yorumu:")
    _interpret(results)
    print(f"{'='*70}\n")


def _interpret(results: dict[str, ABMetrics]) -> None:
    """Hangi modun daha iyi olduğunu yorumlar."""
    b = results.get("devret_off__pos_off")
    d = results.get("devret_on___pos_off")
    p = results.get("devret_off__pos_on")
    dp = results.get("devret_on___pos_on")

    if not all([b, d, p, dp]):
        return

    def verdict(delta_acc: float, delta_brier: float) -> str:
        if delta_acc > 1.0 and delta_brier < 0:
            return "✅ Güvenilir"
        elif delta_acc > 0 and delta_brier < 0:
            return "🟡 Sınırlı fayda"
        elif delta_acc < 0 or delta_brier > 0:
            return "❌ Zararlı"
        else:
            return "⚪ Nötr"

    devret_v = verdict(d.accuracy()-b.accuracy(), d.avg_brier()-b.avg_brier())
    pos_v    = verdict(p.accuracy()-b.accuracy(), p.avg_brier()-b.avg_brier())
    both_v   = verdict(dp.accuracy()-b.accuracy(), dp.avg_brier()-b.avg_brier())

    print(f"  • Devret ON (Pozisyon OFF) : {devret_v}")
    print(f"  • Pozisyon ON (Devret OFF) : {pos_v}")
    print(f"  • Her ikisi ON             : {both_v}")


# ─── Devret Hafta Filtresi ───────────────────────────────────────────────────

def filter_devret_weeks(matches: list[MatchInput]) -> dict[str, list[MatchInput]]:
    """
    Maçları devret/normal/devret-sonrası haftalarına göre ayırır.
    Devret ON/OFF karşılaştırması için alt küme analizi.
    """
    groups: dict[str, list[MatchInput]] = {
        "devret":         [],
        "post_devret":    [],
        "normal":         [],
    }
    for m in matches:
        if m.is_devret:
            groups["devret"].append(m)
        else:
            groups["normal"].append(m)

    return groups


def print_devret_subgroup_report(
    matches: list[MatchInput],
    predict_fn: PredictFn,
) -> None:
    """
    Devret/Normal haftalarda ON/OFF farkını gösterir.
    Bölüm 8 — 'ST58-ST60 test zamanı' için.
    """
    groups = filter_devret_weeks(matches)
    print(f"\n📊 DEVRET ALT-GRUP ANALİZİ")
    for group_name, group_matches in groups.items():
        if not group_matches:
            continue
        print(f"\n  [{group_name.upper()}] — {len(group_matches)} maç")
        res = run_ab_test(group_matches, predict_fn)
        print_ab_report(res)


# ─── Kullanım Örneği ─────────────────────────────────────────────────────────

def _mock_predict_fn(match: MatchInput, devret_on: bool, pos_on: bool) -> Prediction:
    """
    Gerçek lambda_calc.py yokken test için mock.
    Gerçek sistemde bunu suggest() ile değiştir.
    """
    from model.position_bias import get_position_bias, BANKO_SAFE_POSITIONS, HIGH_X_POSITIONS
    from memory.devret_rule import DEVRET_ADJUSTMENTS

    p1 = 1.0 / max(match.odds_home, 0.01)
    px = 1.0 / max(match.odds_draw, 0.01)
    p2 = 1.0 / max(match.odds_away, 0.01)
    total = p1 + px + p2
    p1, px, p2 = p1/total, px/total, p2/total

    if pos_on:
        bias = get_position_bias(match.position)
        p1 += bias.get("1", 0.0)
        px += bias.get("X", 0.0)
        p2 += bias.get("2", 0.0)
        t = p1 + px + p2
        p1, px, p2 = p1/t, px/t, p2/t

    if devret_on and match.is_devret:
        px += DEVRET_ADJUSTMENTS["x_bias_boost"]
        t = p1 + px + p2
        p1, px, p2 = p1/t, px/t, p2/t

    if match.position in BANKO_SAFE_POSITIONS and p1 > 0.55:
        suggestion = "BANKO 1"
    elif match.position in HIGH_X_POSITIONS:
        suggestion = "ÇİFT 1X"
    elif px > 0.35:
        suggestion = "KAOS"
    elif p1 > 0.50:
        suggestion = "TEK 1"
    elif p2 > 0.45:
        suggestion = "ÇİFT 2X"
    else:
        suggestion = "ÇİFT 1X"

    return Prediction(p1=p1, px=px, p2=p2, suggestion=suggestion)


if __name__ == "__main__":
    print("A/B Test Çerçevesi yüklendi.")
    print("Kullanım: from tools.ab_test import run_ab_test, print_ab_report")
    print("Gerçek predict_fn'i lambda_calc.py'den bağla.")
