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

# BÖLÜM 10 — ÇIKTI
# ═══════════════════════════════════════════════════════════════


def print_results(results: list, week_info: str = ""):
    """
    Sonuç tablosunu yazdır.
    Yeni göstergeler:
      💎 Value  — model olasılığı oranın ima ettiğinden yüksek
      ⚠ Düşük güven — CI geniş (belirsiz maç)
      H2H      — son 5 H2H özeti
    """
    W = 72
    print("\n" + "═" * W)
    print(f"  SPOR TOTO — MONTE CARLO SONUÇLARI  {week_info}")
    print(f"  {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  "
          f"Sim: {CFG['simulations']:,}  |  "
          f"DC: ✓  |  Model/Oran: {CFG['model_weight']:.0%}/{CFG['odds_weight']:.0%}")
    print("═" * W)

    hdr = (f"{'#':>2}  {'MAÇ':<30} {'λH':>4} {'λA':>4}"
           f"  {'1%':>5} {'X%':>5} {'2%':>5}  {'ÖNERİ':<12} {'x':>1}")
    print(f"\n{hdr}")
    print("─" * len(hdr))

    total_cols  = 1
    banko = tek = chift = kaos = 0
    value_count = 0

    for r in results:
        ctx    = r.get("ctx","")
        streak = r.get("streak","")

        # Value göstergesi
        value  = r.get("value",{})
        val_tag = ""
        if value.get("has_value"):
            val_tag = f"💎{value['outcome']}+{value['edge']*100:.0f}%"
            value_count += 1

        # Entropy + CI göstergesi
        H   = r.get("entropy", 0)
        ci  = r.get("ci_width", 0)
        ent_tag = ""
        if ci > 0.050 or H > 1.05:
            ent_tag = f"⚡H={H:.2f}"    # Yüksek belirsizlik
        elif ci < 0.025 and H < 0.80:
            ent_tag = f"🎯H={H:.2f}"   # Düşük belirsizlik (güvenilir)

        # H2H özeti
        h2h    = r.get("h2h")
        h2h_tag = ""
        if h2h and h2h.get("n",0) >= 3:
            h2h_tag = f"H2H:{h2h['h_wins']}W{h2h['draws']}D{h2h['a_wins']}L"

        # LPRM sinyali
        lprm = r.get("lprm")
        lprm_tag = ""
        if lprm and lprm.get("signal") not in (None, "nötr", "normal"):
            sig = lprm["signal"]
            score = lprm.get("score", 0)
            icons = {
                "güçlü_ev":   "🟢EV",
                "hafif_ev":   "🟡ev",
                "hafif_dep":  "🟡dep",
                "güçlü_dep":  "🔴DEP",
            }
            lprm_tag = icons.get(sig, "")

        tags = " ".join(filter(None, [ctx, streak, val_tag, ent_tag,
                                      h2h_tag, lprm_tag]))

        print(
            f"{r['no']:>2}. {r['mac']:<30} "
            f"{r['lH']:>4.2f} {r['lA']:>4.2f}  "
            f"{r['P1']:>5.1f} {r['PX']:>5.1f} {r['P2']:>5.1f}  "
            f"{r['oneri']:<12} {r['mul']:>1}"
            + (f"  {tags}" if tags else "")
        )
        # Human-Like açıklama
        _expl = r.get("explain", "")
        if _expl and _expl != "—":
            print(f"     └─ {_expl[:72]}")

        # Profil satırı
        prf = r.get("profile")
        if prf and prf.get("n",0) >= 5:
            p1p = prf["p1"]*100
            pxp = prf["px"]*100
            p2p = prf["p2"]*100
            n   = prf["n"]
            arrow = lambda d: ("↑" if d > 3 else "↓" if d < -3 else "≈")
            note = "  ← dikkat: X gerçekte yüksek" if pxp > r["PX"]+8 else ""
            print(
                f"     📊 Profil ({n} maç): "
                f"1={p1p:.0f}%{arrow(p1p-r['P1'])} "
                f"X={pxp:.0f}%{arrow(pxp-r['PX'])} "
                f"2={p2p:.0f}%{arrow(p2p-r['P2'])}"
                + note
            )

        total_cols *= r["mul"]
        lbl = r["oneri"].split()[0]
        if lbl == "BANKO":  banko += 1
        elif lbl == "TEK":  tek   += 1
        elif lbl == "CIFT": chift += 1
        else:               kaos  += 1

    print("─" * len(hdr))
    cost    = total_cols * CFG["unit_price"]
    tek_str = f"  Tek:{tek}" if tek else ""
    val_str = f"  💎 Value:{value_count}" if value_count else ""
    print(f"\n  Banko:{banko}{tek_str}  Cift:{chift}  Kaos:{kaos}{val_str}")
    print(f"  Toplam: {total_cols:,} kolon = {cost:,} TL")
    return total_cols, cost




def print_coupons(coupons: list):
    """Bolunmus kuponlari yazdir."""
    if not coupons:
        return
    W = 70
    total_cost = sum(c["cost"] for c in coupons)
    print(f"\n{'═'*W}")
    print(f"  KUPON BOLME ({len(coupons)} kupon)  |  "
          f"Toplam: {total_cost:,} TL")
    print(f"  (Her kupon maks. {CFG['max_cols_per_coupon']:,} kolon)")
    print(f"{'═'*W}")

    for c in coupons:
        print(f"\n  ── KUPON {c['id']}  |  {c['cols']:,} kolon  |  {c['cost']:,} TL ──")
        for r in c["matches"]:
            print(f"    {r['no']:>2}. {r['mac']:<28}  {r['oneri']:<12}  x{r['mul']}")

    print(f"\n  Toplam kupon adedi : {len(coupons)}")
    print(f"  Toplam tutar       : {total_cost:,} TL")

# ═══════════════════════════════════════════════════════════════
# BÖLÜM 11 — ANA PIPELINE