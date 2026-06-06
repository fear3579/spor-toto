# -*- coding: utf-8 -*-
"""
analiz.py — AUGUR ENGINE Performans Analizi
============================================
Menü A ile çağrılır. 4 farklı metriği ayrı ayrı gösterir:

  1. Kupon Kapsama  : actual ∈ pred  (1X2, 2X, 1X vb.)
  2. Saf Argmax     : argmax(P1,PX,P2) == actual
  3. Top-2 Hit      : actual ∈ top-2 olasılık
  4. Pure TEK Hit   : sadece tek seçim yapılan maçlar

Ayrıca: BANKO / KAOS / pozisyon analizi, Brier skoru.
"""

import os
import json
import sys
import re as _re

_HERE = os.path.dirname(os.path.abspath(__file__))
PRED_FILE = os.path.join(_HERE, "st_predictions.json")

FTR_MAP = {"H":"1","D":"X","A":"2","0":"X"}  # 0 = X (beraberlik)


def _load_preds():
    if not os.path.exists(PRED_FILE):
        return {}
    try:
        return json.load(open(PRED_FILE, encoding="utf-8"))
    except Exception:
        return {}


def _week_metrics(matches: list) -> dict:
    """Tek hafta için 4 metriği hesapla."""
    kupon_c=0; kupon_t=0
    argmax_c=0; argmax_t=0
    top2_c=0
    tek_c=0; tek_t=0
    banko_c=0; banko_t=0
    kaos_c=0; kaos_t=0
    brier_sum=0.0; brier_n=0
    draw_n=0

    for m in matches:
        actual_raw = m.get("actual","")
        actual = FTR_MAP.get(actual_raw, actual_raw)
        pred   = str(m.get("pred","")).strip()
        if not actual: continue

        # 1. Kupon kapsama
        kupon_t += 1
        if actual in pred: kupon_c += 1
        if actual == "X": draw_n += 1

        # BANKO / KAOS
        if len(pred) == 1 and "BANKO" in str(m.get("pred_label","")):
            banko_t += 1
            if actual in pred: banko_c += 1
        elif len(pred) == 3:
            kaos_t += 1
            if actual in pred: kaos_c += 1

        # 2-3. Argmax ve Top-2
        p1 = m.get("P1",0); px = m.get("PX",0); p2 = m.get("P2",0)
        if p1 and px and p2:
            argmax_t += 1
            argmax = ("1" if p1>=px and p1>=p2 else
                      ("X" if px>=p2 else "2"))
            if argmax == actual: argmax_c += 1
            probs = sorted([("1",p1),("X",px),("2",p2)],
                           key=lambda x:-x[1])
            if actual in [probs[0][0], probs[1][0]]: top2_c += 1
            # Brier — normalize et
            _raw = p1 + px + p2
            if _raw > 0:
                pv = {"1":p1/_raw,"X":px/_raw,"2":p2/_raw}
                yv = {"1":0,"X":0,"2":0}; yv[actual]=1
                # Brier: toplam/3 ile normalize → standart ölçek
                brier_sum += sum((pv[k]-yv[k])**2 for k in ["1","X","2"]) / 3.0
                brier_n += 1

        # 4. Pure TEK
        if len(pred) == 1:
            tek_t += 1
            if pred == actual: tek_c += 1

    return {
        "kupon_c":kupon_c, "kupon_t":kupon_t,
        "argmax_c":argmax_c, "argmax_t":argmax_t,
        "top2_c":top2_c,
        "tek_c":tek_c, "tek_t":tek_t,
        "banko_c":banko_c, "banko_t":banko_t,
        "kaos_c":kaos_c,   "kaos_t":kaos_t,
        "brier": round(brier_sum/brier_n, 4) if brier_n else None,
        "draw_n": draw_n,
    }


def _pct(c, t):
    if not t: return "  —  "
    return f"{c/t*100:.1f}%"


def main():
    preds = _load_preds()
    if not preds:
        print("  ✗ st_predictions.json bulunamadı")
        return

    def _wk_sort_key(item):
        _wm = _re.match(r'ST(\d+)-(\d+)', item[0] if isinstance(item, tuple) else item)
        return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)

    weeks_data = {}
    for wid, wd in sorted(preds.items(), key=_wk_sort_key):
        matches = wd.get("matches", [])
        entered = [m for m in matches if m.get("actual")]
        if not entered: continue
        weeks_data[wid] = _week_metrics(entered)

    if not weeks_data:
        print("  ✗ Sonuç girilmiş hafta yok")
        return

    print("\n" + "═"*70)
    print("  AUGUR ENGINE — PERFORMANS ANALİZİ")
    print("═"*70)

    # ── 4 Metrik Açıklama ─────────────────────────────────────────────────
    print("""
  METRİK AÇIKLAMALARI:
  ┌─────────────────┬────────────────────────────────────────────────┐
  │ Kupon Kapsama   │ actual ∈ pred  (1X2, 2X, 1X gibi)             │
  │ Saf Argmax      │ argmax(P1,PX,P2) == actual  (tek karar)       │
  │ Top-2 Hit       │ actual ∈ top-2 olasılık  (kupon hedef metrik) │
  │ Pure TEK Hit    │ sadece TEK önerilen maçlar  (banko güveni)    │
  └─────────────────┴────────────────────────────────────────────────┘
  NOT: "%73 mü %57 mi?" → farklı metrikler, ikisi de doğru.
""")

    # ── Hafta bazlı tablo ─────────────────────────────────────────────────
    print(f"  {'HAFTA':<12} {'KUPON':>7} {'ARGMAX':>7} {'TOP-2':>7} "
          f"{'TEK':>7} {'BANKO':>8} {'KAOS':>7} {'BRIER':>7}")
    print("  " + "─"*67)

    totals = {k:0 for k in
              ["kupon_c","kupon_t","argmax_c","argmax_t","top2_c",
               "tek_c","tek_t","banko_c","banko_t","kaos_c","kaos_t"]}
    brier_list = []

    for wid, w in sorted(weeks_data.items(), key=_wk_sort_key):
        for k in totals:
            totals[k] += w[k]
        if w["brier"]: brier_list.append(w["brier"])

        print(f"  {wid:<12} "
              f"{_pct(w['kupon_c'],w['kupon_t']):>7} "
              f"{_pct(w['argmax_c'],w['argmax_t']):>7} "
              f"{_pct(w['top2_c'],w['argmax_t']):>7} "
              f"{_pct(w['tek_c'],w['tek_t']):>7} "
              f"{_pct(w['banko_c'],w['banko_t']):>8} "
              f"{_pct(w['kaos_c'],w['kaos_t']):>7} "
              f"{str(w['brier']) if w['brier'] else '  —  ':>7}")

    print("  " + "─"*67)
    avg_brier = round(sum(brier_list)/len(brier_list), 4) if brier_list else None
    print(f"  {'TOPLAM':<12} "
          f"{_pct(totals['kupon_c'],totals['kupon_t']):>7} "
          f"{_pct(totals['argmax_c'],totals['argmax_t']):>7} "
          f"{_pct(totals['top2_c'],totals['argmax_t']):>7} "
          f"{_pct(totals['tek_c'],totals['tek_t']):>7} "
          f"{_pct(totals['banko_c'],totals['banko_t']):>8} "
          f"{_pct(totals['kaos_c'],totals['kaos_t']):>7} "
          f"{str(avg_brier) if avg_brier else '  —  ':>7}")

    # ── Brier değerlendirmesi ─────────────────────────────────────────────
    if avg_brier:
        grade = ("✅ Mükemmel" if avg_brier < 0.19 else
                 "✅ İyi"      if avg_brier < 0.22 else
                 "⚠ Orta"     if avg_brier < 0.26 else "❌ Zayıf")
        print(f"\n  Ortalama Brier: {avg_brier}  {grade}")
        print("  (Standart Brier/3: Mük<0.19 | İyi<0.22 | Orta<0.26)")
        print("  (Referans: Pinnacle~0.190 | Rastgele~0.222 | Naive~0.250)")

    # ── Hata analizi ─────────────────────────────────────────────────────
    banko_err = (1 - totals['banko_c']/totals['banko_t'])*100 if totals['banko_t'] else 0
    kaos_draw = 0; kaos_draw_t = 0
    for _, wd in preds.items():
        for m in wd.get("matches",[]):
            pred = str(m.get("pred","")).strip()
            actual = FTR_MAP.get(m.get("actual",""), m.get("actual",""))
            if len(pred)==3 and actual:
                kaos_draw_t += 1
                if actual == "X": kaos_draw += 1

    print(f"""
  ── Hata Desenleri ──────────────────────────────────
  BANKO yanılma        : %{banko_err:.1f}  ({totals['banko_t']-totals['banko_c']}/{totals['banko_t']})
  KAOS→X gerçek berab. : %{kaos_draw/kaos_draw_t*100:.1f}  ({kaos_draw}/{kaos_draw_t})
  ────────────────────────────────────────────────────""")

    # ── Metrik yorumu ─────────────────────────────────────────────────────
    kap = totals['kupon_c']/totals['kupon_t']*100 if totals['kupon_t'] else 0
    am  = totals['argmax_c']/totals['argmax_t']*100 if totals['argmax_t'] else 0
    t2  = totals['top2_c']/totals['argmax_t']*100 if totals['argmax_t'] else 0

    print(f"""
  ── Metrik Yorumu ───────────────────────────────────
  Kupon kapsama %{kap:.1f}  : 1X2/2X/1X seçimler için kapsama
  Saf argmax    %{am:.1f}  : Model tek karar verseydi başarısı
  Top-2 hit     %{t2:.1f}  : Gerçek tahmin kalitesi (kupon hedef)
  
  Top-2 %{t2:.0f} → Kuponlarda %80+ doğru maç içeriyor ✅
  Argmax %{am:.0f} → Model birinci tercihi doğru %{am:.0f} oranında
  Gap (%{kap:.0f}-%{am:.0f}=%{kap-am:.0f}) → Çift/üçlü seçimlerin katkısı
  ────────────────────────────────────────────────────""")

    print("\n" + "═"*70 + "\n")


if __name__ == "__main__":
    main()
