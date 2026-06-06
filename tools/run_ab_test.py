# -*- coding: utf-8 -*-
"""
run_ab_test.py — A/B Test Çalıştırıcı
=======================================
Kullanım:
  1. tools/ klasörüne koy
  2. Hafta ID'si ver:
     python run_ab_test.py W23-2026
  3. Otomatik olarak:
     - st_memory.json'dan geçmiş tahminleri okur
     - Devret ON/OFF & Pozisyon ON/OFF karşılaştırır
     - Rapor üretir

W23-25 arasında çalıştır (5+ hafta canlı veri gerekli)
"""

import sys
import os
import json

# Path ayarla
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))

from ab_test import MatchInput, run_ab_test, print_ab_report


def load_matches_from_memory(mem_path: str,
                              from_week: str = None) -> list:
    """
    st_memory.json + st_predictions.json'dan
    geçmiş maçları MatchInput formatına çevir.
    """
    pred_path = mem_path.replace("st_memory.json", "st_predictions.json")

    if not os.path.exists(pred_path):
        print(f"  ✗ {pred_path} bulunamadı")
        return []

    with open(pred_path, encoding="utf-8") as f:
        preds = json.load(f)

    with open(mem_path, encoding="utf-8") as f:
        mem = json.load(f)

    # Devret haftaları
    devret_weeks = set()
    for h in mem.get("weekly_history", []):
        if h.get("prize_15_prev") == "Devretti":
            devret_weeks.add(h.get("week", ""))

    def _wk_num(wid):
        import re as _re
        m = _re.match(r'ST(\d+)-(\d+)', wid)
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    matches = []
    for week_id, week_data in preds.items():
        if from_week and _wk_num(week_id) < _wk_num(from_week):
            continue
        # Status yerine actual kontrolü yap
        has_results = any(m.get("actual") for m in week_data.get("matches",[]))
        if not has_results:
            continue

        is_devret = week_id in devret_weeks

        for m in week_data.get("matches", []):
            actual = m.get("actual")
            if not actual:
                continue

            # 1/X/2 → sayısal sonuç
            result = {"H":"1","D":"X","A":"2","0":"X"}.get(actual, actual)

            matches.append(MatchInput(
                match_id  = f"{week_id}-M{m.get('no',0)}",
                position  = m.get("no", 1),
                home_team = m.get("home", "?"),
                away_team = m.get("away", "?"),
                odds_home  = m.get("odds", {}).get("1") or 2.0,
                odds_draw  = m.get("odds", {}).get("X") or 3.3,
                odds_away  = m.get("odds", {}).get("2") or 3.8,
                stored_p1  = float(m.get("P1", 0) or 0) / 100.0,
                stored_px  = float(m.get("PX", 0) or 0) / 100.0,
                stored_p2  = float(m.get("P2", 0) or 0) / 100.0,
                league_code= str(m.get("league", "")),
                result    = result,
                week_id   = week_id,
                is_devret = is_devret,
            ))

    return matches


def build_predict_fn():
    """
    Gerçek pipeline'dan predict_fn oluştur.
    devret_on/pos_on parametrelerine göre CFG ayarlar.
    """
    # CFG kopyası
    import copy
    try:
        from config import CFG as _CFG
        BASE_CFG = copy.deepcopy(_CFG)
    except Exception:
        BASE_CFG = {
            "banko_threshold": 0.65,
            "kaos_spread":     0.10,
            "recent_draw_rate":0.27,
        }

    def predict_fn(match: MatchInput,
                   devret_on: bool,
                   pos_on:    bool):
        from model.monte_carlo import monte_carlo, blend_probs, implied_probs
        from model.lambda_calc import calc_lambda
        from model.suggest     import suggest

        cfg = copy.deepcopy(BASE_CFG)

        # Devret ON ayarları
        if devret_on and match.is_devret:
            cfg["kaos_spread"]      *= 1.30
            cfg["recent_draw_rate"]  = cfg.get("recent_draw_rate",0.27) + 0.05
            cfg["banko_threshold"]  += 0.05

        # Pozisyon ON → position kwarg geçilir
        pos_kwarg = match.position if pos_on else None

        try:
            # Gercek stats yukle
            _stats, _avg = {}, 1.30
            try:
                import sys as _sys
                _proj = os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))
                if _proj not in _sys.path:
                    _sys.path.insert(0, _proj)
                from data.downloader import download_league
                from model.team_stats import build_team_stats
                _df = download_league(
                    match.league_code,
                    getattr(match, "season", "2526"))
                if _df is not None:
                    _st, _av, _ = build_team_stats(_df)
                    _stats, _avg = _st, _av
            except Exception:
                pass

            # ELO farki
            _elo_diff = 0.0
            try:
                from model.lambda_calc import load_clubelo, get_clubelo
                _celo = load_clubelo()
                if _celo:
                    _eh = get_clubelo(match.home_team, _celo)
                    _ea = get_clubelo(match.away_team, _celo)
                    if _eh != 1500.0 or _ea != 1500.0:
                        _elo_diff = (_eh - _ea) / 400.0
            except Exception:
                pass

            lam_h, lam_a = calc_lambda(
                match.home_team, match.away_team,
                _stats, _avg,
                None, None,
                league_code      = match.league_code,
                position         = pos_kwarg,
                season_week      = getattr(match, "week_no", 25),
                devret           = devret_on,
                league_draw_rate = cfg.get("recent_draw_rate", 0.265),
                elo_diff         = _elo_diff,
            )
        except Exception:
            lam_h, lam_a = 1.40, 1.10

        # Olasılık
        p1, px, p2 = monte_carlo(lam_h, lam_a)

        # stored_p1/px/p2 varsa kullan (daha güvenilir)
        if match.stored_p1 > 0.05 and match.stored_px > 0.05:
            p1 = match.stored_p1
            px = match.stored_px
            p2 = match.stored_p2
        else:
            # Oran blend fallback
            try:
                imp = implied_probs(match.odds_home, match.odds_draw, match.odds_away)
                p1, px, p2 = blend_probs((p1,px,p2), imp)
            except Exception:
                pass

        # Karar - CFG gecici override
        try:
            import config as _cfgmod
            _old_cfg = {k: _cfgmod.CFG.get(k) for k in cfg
                        if k in _cfgmod.CFG}
            try:
                _cfgmod.CFG.update(cfg)
                label, _, _ = suggest(p1, px, p2,
                                      position=pos_kwarg,
                                      entropy=None)
            finally:
                _cfgmod.CFG.update(_old_cfg)
        except Exception:
            label = ("TEK 1" if p1 == max(p1, px, p2) else
                     ("TEK X" if px == max(p1, px, p2) else "TEK 2"))

        from ab_test import Prediction
        return Prediction(p1=p1, px=px, p2=p2, suggestion=label)

    return predict_fn



def run_ab_test(matches: list, predict_fn) -> dict:
    """
    4 senaryo karşılaştır:
      A: devret=OFF, pos=OFF  (baseline)
      B: devret=OFF, pos=ON
      C: devret=ON,  pos=OFF
      D: devret=ON,  pos=ON   (tam sistem)
    """
    import math

    FTR = {"H": "1", "D": "X", "A": "2", "0": "X",
           "1": "1", "X": "X", "2": "2"}
    scenarios = {
        "A_baseline":   {"devret": False, "pos": False},
        "B_pos_on":     {"devret": False, "pos": True},
        "C_devret_on":  {"devret": True,  "pos": False},
        "D_full":       {"devret": True,  "pos": True},
    }

    results = {k: {"brier": 0.0, "acc": 0, "n": 0, "kupon": 0}
               for k in scenarios}

    for match in matches:
        actual_raw = getattr(match, "result", None)  # MatchInput.result, not .actual
        if not actual_raw:
            continue
        actual = FTR.get(actual_raw, actual_raw)

        for sc_name, sc_cfg in scenarios.items():
            try:
                pred = predict_fn(match,
                                  devret_on=sc_cfg["devret"],
                                  pos_on=sc_cfg["pos"])
            except Exception:
                continue

            p1, px, p2 = pred.p1, pred.px, pred.p2
            sug = pred.suggestion or ""
            n = results[sc_name]

            n["n"] += 1

            # Brier/3
            raw = p1 + px + p2
            if raw > 0 and actual in ("1","X","2"):
                pv = {"1": p1/raw, "X": px/raw, "2": p2/raw}
                yv = {"1": 0, "X": 0, "2": 0}
                yv[actual] = 1
                brier = sum((pv[k]-yv[k])**2 for k in ["1","X","2"]) / 3.0
                n["brier"] += brier

            # Argmax doğruluk
            argmax = ("1" if p1>=px and p1>=p2 else
                      ("X" if px>=p2 else "2"))
            if argmax == actual:
                n["acc"] += 1

            # Kupon kapsama — KAOS tüm sonuçları kapsar
            _sug_clean = sug.replace("KAOS","").replace("TEK","").replace("CIFT","").replace("BANKO","").strip()
            if actual in _sug_clean:
                n["kupon"] += 1

    # Ortalamaları hesapla
    for sc_name in results:
        r = results[sc_name]
        n = r["n"]
        if n > 0:
            r["brier_avg"] = round(r["brier"] / n, 4)
            r["acc_pct"]   = round(r["acc"] / n * 100, 1)
            r["kupon_pct"] = round(r["kupon"] / n * 100, 1)
        else:
            r["brier_avg"] = 0.0
            r["acc_pct"]   = 0.0
            r["kupon_pct"] = 0.0

    return results


def print_ab_report(results: dict) -> None:
    """A/B test sonuçlarını terminale yaz."""
    labels = {
        "A_baseline":  "A  baseline    (devret=OFF, pos=OFF)",
        "B_pos_on":    "B  pos=ON      (devret=OFF, pos=ON) ",
        "C_devret_on": "C  devret=ON   (devret=ON,  pos=OFF)",
        "D_full":      "D  tam sistem  (devret=ON,  pos=ON) ",
    }

    print()
    print("  ── A/B Test Sonuçları ───────────────────────────────────────")
    print(f"  {'Senaryo':<40} {'N':>5} {'Brier/3':>8} {'Argmax%':>8} {'Kupon%':>8}")
    print(f"  {'─'*40} {'─'*5} {'─'*8} {'─'*8} {'─'*8}")

    base_brier = results.get("A_baseline", {}).get("brier_avg", 0)

    for sc, label in labels.items():
        r = results.get(sc, {})
        n = r.get("n", 0)
        b = r.get("brier_avg", 0)
        a = r.get("acc_pct", 0)
        k = r.get("kupon_pct", 0)

        delta = ""
        if sc != "A_baseline" and base_brier > 0:
            diff = b - base_brier
            sign = "+" if diff >= 0 else ""
            delta = f"  ({sign}{diff:.4f})"

        kaos_n  = r.get("kaos_n", 0)
        banko_n = r.get("banko_n", 0)
        print(f"  {label}  {n:>5}  {b:.4f}{delta:>12}  {k:>6.1f}%  {kaos_n:>6}  {banko_n:>6}")

    print(f"  {'─'*80}")

    # En iyi senaryo
    best = min(results.items(), key=lambda x: x[1].get("brier_avg", 99))
    best_label = labels.get(best[0], best[0])
    print(f"\n  🏆 En iyi Brier: {best_label.strip()}")
    print(f"     Brier/3 = {best[1]['brier_avg']:.4f}")

    # Pozisyon katkısı
    a_brier = results.get("A_baseline", {}).get("brier_avg", 0)
    b_brier = results.get("B_pos_on",   {}).get("brier_avg", 0)
    if a_brier and b_brier:
        pos_delta = b_brier - a_brier
        pos_verdict = ("✅ YARАРLI" if pos_delta < -0.002 else
                       ("⚠ Nötr"   if pos_delta < +0.002 else
                        "❌ ZARARLI"))
        print(f"\n  Pozisyon katsayısı etkisi: {pos_delta:+.4f}  {pos_verdict}")

    # Devret katkısı
    c_brier = results.get("C_devret_on", {}).get("brier_avg", 0)
    if a_brier and c_brier:
        dev_delta = c_brier - a_brier
        dev_verdict = ("✅ YARАРLI" if dev_delta < -0.002 else
                       ("⚠ Nötr"   if dev_delta < +0.002 else
                        "❌ ZARARLI"))
        print(f"  Devret bias etkisi:         {dev_delta:+.4f}  {dev_verdict}")

    print()


def main():
    from_week = sys.argv[1] if len(sys.argv) > 1 else None

    # Paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    proj_dir   = os.path.dirname(script_dir)
    mem_path   = os.path.join(proj_dir, "st_memory.json")

    print(f"\n{'='*55}")
    print(f"  A/B TEST — Devret & Pozisyon ON/OFF")
    print(f"{'='*55}")
    print(f"  Veri: {mem_path}")
    if from_week:
        print(f"  Başlangıç: {from_week}")

    # Maçları yükle
    print("\n[1] Maçlar yükleniyor...")
    matches = load_matches_from_memory(mem_path, from_week)

    if len(matches) < 30:
        print(f"  ⚠ Yeterli maç yok: {len(matches)} (min 30 gerekli)")
        print(f"  ST58-ST60 arasında tekrar çalıştır")
        return

    print(f"  ✓ {len(matches)} maç yüklendi")
    devret_n = sum(1 for m in matches if m.is_devret)
    print(f"  Devret maçları: {devret_n}")

    # Predict fonksiyonu
    predict_fn = build_predict_fn()

    # Test çalıştır
    print("\n[2] Test çalışıyor (4 senaryo)...")
    results = run_ab_test(matches, predict_fn)

    # Rapor
    print_ab_report(results)


if __name__ == "__main__":
    main()
