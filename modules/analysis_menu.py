# -*- coding: utf-8 -*-
"""
Test & Analiz Merkezi (Menü 7) ve alt analiz fonksiyonları.
Backtest, LPRM raporu, A/B testi, senaryo analizi.
"""
import os
import sys
import json
import math

import numpy as np
import pandas as pd

from config import (LEAGUES, PAST_SEASONS, CURRENT_SEASON,
                    ST_SEASON_TAG, CFG)
from model.monte_carlo import monte_carlo
from memory.st_memory import get_memory


def _run_test_center(mem=None):
    """Menü 7 — Test & Analiz Merkezi."""
    R  = "\033[0m"; B = "\033[1m"
    C  = "\033[36m"; G = "\033[32m"; DM = "\033[2m"

    while True:
        print()
        print(f"\n  {C}{B}── TEST & ANALİZ MERKEZİ {'─'*18}{R}")
        print(f"  {G}{B}1{R}  Backtest        {DM}(geçmiş sezon){R}")
        print(f"  {G}{B}2{R}  Performans      {DM}(ST37+ KAOS/BANKO){R}")
        print(f"  {G}{B}3{R}  Senaryo         {DM}(What-If analizi){R}")
        print(f"  {C}{B}4{R}  Performans Röntgeni  {DM}(derinlemesine analiz){R}")
        print(f"  {C}{B}5{R}  CLV Tracker          {DM}(kapanış çizgisi değeri){R}")
        print(f"  {G}{B}6{R}  Model Sağlık Paneli  {DM}(genel sistem sağlığı){R}")
        print(f"  {C}{'─'*40}{R}")
        print(f"\n  {DM}Seçim (1-6, M=Geri):{R} ", end="", flush=True)
        try:
            ch = input().strip()[:1].upper()
        except (EOFError, KeyboardInterrupt):
            break

        if ch in ("M", ""):
            break
        if ch == "1":
            _run_backtest()
        elif ch == "2":
            import importlib.util as _ilu
            _ap = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "analiz.py")
            _ap = os.path.normpath(_ap)
            if not os.path.exists(_ap):
                print("  analiz.py bulunamadı.")
            else:
                _sp = _ilu.spec_from_file_location("analiz", _ap)
                _m  = _ilu.module_from_spec(_sp)
                _sp.loader.exec_module(_m)
                if hasattr(_m, "main"): _m.main()
        elif ch == "3":
            _run_scenario_analysis()
        elif ch == "4":
            try:
                from memory.performance_xray import run_xray
                _mem = mem if mem is not None else get_memory()
                run_xray(_mem)
            except Exception as _xe:
                print(f"  Röntgen hatası: {_xe}")
                import traceback; traceback.print_exc()
        elif ch == "5":
            try:
                from memory.clv_tracker import get_clv_tracker
                get_clv_tracker().print_summary()
            except Exception as _ce:
                print(f"  CLV Tracker hatası: {_ce}")
        elif ch == "6":
            try:
                from memory.model_health import run_health_check
                _mem = mem if mem is not None else get_memory()
                run_health_check(_mem)
            except Exception as _he:
                print(f"  Sağlık paneli hatası: {_he}")
                import traceback; traceback.print_exc()

        print(f"\n  {DM}{'─'*38}{R}")
        input("  Enter ile geri dön...")


def _run_backtest():
    """Menü 7→1 — Geçmiş sezon verisiyle backtest + LPRM analizi."""
    print("\n" + "═"*62)
    print("  BACKTEST — GEÇMİŞ SEZON ANALİZİ")
    print("═"*62)

    print("\n  Analiz modu seçin:")
    print("    1. Tek Lig/Sezon Backtest")
    print("    2. Toplu Analiz  (tüm ligler, tüm sezonlar)")
    print("    3. LPRM Raporu   (LPRM on/off karşılaştırma)")
    print("    4. A/B Test      (Devret & Pozisyon ON/OFF)")
    print("  Seçim (1-4, Enter=1): ", end="", flush=True)
    try:
        mode = input().strip()[:1]
        if mode not in ("1","2","3","4"): mode = "1"
    except Exception:
        mode = "1"

    if mode == "2":
        _run_backtest_toplu()
        return
    if mode == "3":
        _run_lprm_report()
        return
    if mode == "4":
        _run_ab_test()
        return

    LIG_MAP = {"1":("T1","Süper Lig"),"2":("E0","Premier League"),
               "3":("D1","Bundesliga"),"4":("SP1","La Liga"),
               "5":("I1","Serie A"),"6":("F1","Ligue 1")}
    print("\n  Lig seçin:")
    for k,(code,name) in LIG_MAP.items():
        print(f"    {k}. {name} ({code})")
    print("  Seçim (1-6, Enter=1): ", end="", flush=True)
    try:
        lig_sel = input().strip()[:1]
        if lig_sel not in LIG_MAP: lig_sel = "1"
    except Exception:
        lig_sel = "1"
    lig_code, lig_name = LIG_MAP[lig_sel]

    def _lbl(code): return f"20{code[:2]}-{code[2:]}"
    SEASONS = {"1": PAST_SEASONS[1], "2": PAST_SEASONS[0], "3": CURRENT_SEASON}
    print(f"\n  Sezon seçin:")
    print(f"    1. {_lbl(PAST_SEASONS[1])}    2. {_lbl(PAST_SEASONS[0])}    3. {_lbl(CURRENT_SEASON)}")
    print("  Seçim (1-3, Enter=2): ", end="", flush=True)
    try:
        s_sel = input().strip()[:1]
        if s_sel not in SEASONS: s_sel = "2"
    except Exception:
        s_sel = "2"
    season = SEASONS[s_sel]

    base     = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "fd_cache")
    csv_path = os.path.join(base, f"{lig_code}_{season}.csv")
    if not os.path.exists(csv_path):
        print(f"\n  ⚠ Dosya yok: {csv_path}")
        print(f"  Menü 6 ile indirin.")
        return

    try:
        df = pd.read_csv(csv_path, on_bad_lines='skip')
    except Exception as e:
        print(f"\n  ⚠ CSV okunamadı: {e}"); return

    if "FTR" not in df.columns:
        print("  ⚠ FTR sütunu yok."); return

    df    = df.dropna(subset=["FTR"])
    df    = df[df["FTR"].isin(["H","D","A"])]
    total = len(df)
    if total < 50:
        print(f"  ⚠ Yeterli maç yok ({total})."); return

    N_SIM = 1000
    print(f"\n  {lig_name} {season[:2]}/{season[2:]} — {total} maç analiz ediliyor...")
    print(f"  Simülasyon: {N_SIM:,}/maç  (hızlı mod)\n")

    odd_cols = {"1":None,"X":None,"2":None}
    for c in ["B365H","PSH","BbAvH","AvgH"]:
        if c in df.columns: odd_cols["1"]=c; break
    for c in ["B365D","PSD","BbAvD","AvgD"]:
        if c in df.columns: odd_cols["X"]=c; break
    for c in ["B365A","PSA","BbAvA","AvgA"]:
        if c in df.columns: odd_cols["2"]=c; break

    correct=0; n=0; brier_sum=0.0
    cm={"H":{"H":0,"D":0,"A":0},"D":{"H":0,"D":0,"A":0},"A":{"H":0,"D":0,"A":0}}
    team_gf={}; team_ga={}; alpha=0.2; lg_avg=1.30
    bar_step = max(1, total//20)

    for idx, row in df.iterrows():
        actual = row["FTR"]
        home = str(row.get("HomeTeam","?"))
        away = str(row.get("AwayTeam","?"))
        gf_h=team_gf.get(home+"_h",1.4); ga_h=team_ga.get(home+"_h",1.1)
        gf_a=team_gf.get(away+"_a",1.1); ga_a=team_ga.get(away+"_a",1.4)
        lam_h=max(0.25,min(3.0,(gf_h*ga_a/lg_avg)*1.10))
        lam_a=max(0.25,min(3.0,(gf_a*ga_h/lg_avg)*0.95))

        _orig=CFG.get("simulations",50000); CFG["simulations"]=N_SIM
        try: p1,px,p2=monte_carlo(lam_h,lam_a)
        except Exception: p1,px,p2=0.45,0.27,0.28
        finally: CFG["simulations"]=_orig

        if odd_cols["1"]:
            try:
                o1=float(row[odd_cols["1"]]); ox=float(row[odd_cols["X"]]); o2=float(row[odd_cols["2"]])
                tot=1/o1+1/ox+1/o2
                p1=p1*0.65+(1/o1/tot)*0.35; px=px*0.65+(1/ox/tot)*0.35; p2=p2*0.65+(1/o2/tot)*0.35
            except Exception: pass

        pred_ftr="H" if p1==max(p1,px,p2) else ("D" if px>p2 else "A")
        if pred_ftr==actual: correct+=1
        if pred_ftr in cm.get(actual,{}): cm[actual][pred_ftr]+=1

        o_h=1.0 if actual=="H" else 0.0; o_d=1.0 if actual=="D" else 0.0; o_a=1.0 if actual=="A" else 0.0
        brier_sum+=((p1-o_h)**2+(px-o_d)**2+(p2-o_a)**2)/3
        try:
            fthg=float(row.get("FTHG",0)); ftag=float(row.get("FTAG",0))
            team_gf[home+"_h"]=gf_h*(1-alpha)+fthg*alpha; team_ga[home+"_h"]=ga_h*(1-alpha)+ftag*alpha
            team_gf[away+"_a"]=gf_a*(1-alpha)+ftag*alpha; team_ga[away+"_a"]=ga_a*(1-alpha)+fthg*alpha
        except Exception: pass
        n+=1
        done=idx-df.index[0]+1
        if done%bar_step==0 or done==total:
            pct=done/total
            bar="█"*int(pct*30)+"░"*(30-int(pct*30))
            print(f"\r  [{bar}] %{pct*100:.0f}  ({done}/{total})", end="", flush=True)
    print()

    acc=correct/n if n else 0; brier=brier_sum/n if n else 0
    classes={"H":"Ev(1)","D":"Bera(X)","A":"Dep(2)"}
    f1s={}
    for cls in ["H","D","A"]:
        tp=cm[cls][cls]; fp=sum(cm[a][cls] for a in cm if a!=cls); fn=sum(cm[cls][p] for p in cm[cls] if p!=cls)
        prec=tp/(tp+fp) if tp+fp else 0; rec=tp/(tp+fn) if tp+fn else 0
        f1s[cls]=round(2*prec*rec/(prec+rec) if prec+rec else 0,3)
    macro_f1=sum(f1s.values())/3

    mem2=get_memory(); tot_m=mem2.mem.get("total_preds",0); cor_m=mem2.mem.get("correct",0)
    acc_m=cor_m/tot_m if tot_m else 0

    print(f"\n{'═'*62}")
    print(f"  BACKTEST — {lig_name} {season[:2]}/{season[2:]}")
    print(f"{'═'*62}")
    print(f"  Analiz edilen : {n} maç")
    print(f"  Doğruluk      : %{acc*100:.1f} ({correct}/{n})")
    print(f"  Brier Skoru   : {brier:.4f}  {'✅' if brier<0.22 else '⚠'}")
    print(f"  Macro F1      : {macro_f1:.3f}")
    print(f"\n  Sınıf Bazlı F1:")
    for cls,name in classes.items():
        bar="█"*int(f1s[cls]*20)+"░"*(20-int(f1s[cls]*20))
        print(f"    {name:<8} [{bar}]  {f1s[cls]:.3f}")
    print(f"\n  Karşılaştırma:")
    print(f"    Backtest ({lig_name}): %{acc*100:.1f}  Brier={brier:.3f}")
    if tot_m:
        wh=mem2.mem.get("weekly_history",[])
        b_vals=[h["brier"] for h in wh if h.get("brier")]
        b_mem=sum(b_vals)/len(b_vals) if b_vals else None
        print(f"    Hafıza ({tot_m} maç): %{acc_m*100:.1f}"+(f"  Brier={b_mem:.3f}" if b_mem else ""))
    print(f"{'═'*62}")


def _run_backtest_toplu():
    """Menü 7→1→2: Tüm ligler ve sezonlar toplu backtest."""
    LIG_MAP = {"T1":"Süper Lig","E0":"Premier League","D1":"Bundesliga",
               "SP1":"La Liga","I1":"Serie A","F1":"Ligue 1"}
    SEASONS  = [PAST_SEASONS[1], PAST_SEASONS[0], CURRENT_SEASON]

    print("\n" + "═"*62)
    print("  TOPLU BACKTEST — Tüm Ligler & Sezonlar")
    print("═"*62)

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "fd_cache")

    grand_total = grand_correct = 0
    grand_brier = 0.0
    rows_out = []

    for lig_code, lig_name in LIG_MAP.items():
        for season in SEASONS:
            csv_path = os.path.join(base, f"{lig_code}_{season}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                df = pd.read_csv(csv_path, on_bad_lines='skip')
            except Exception:
                continue
            if "FTR" not in df.columns:
                continue

            df = df.dropna(subset=["FTR"])
            df = df[df["FTR"].isin(["H","D","A"])]
            if len(df) < 20:
                continue

            correct = 0; brier_sum = 0.0; n = 0
            team_gf = {}; team_ga = {}
            alpha = 0.20; lg_avg = 1.30

            odd_col1 = next((c for c in ["B365H","PSH","AvgH"] if c in df.columns), None)
            odd_colX = next((c for c in ["B365D","PSD","AvgD"] if c in df.columns), None)
            odd_col2 = next((c for c in ["B365A","PSA","AvgA"] if c in df.columns), None)

            for _, row in df.iterrows():
                actual = row["FTR"]
                home   = str(row.get("HomeTeam","?"))
                away   = str(row.get("AwayTeam","?"))

                gf_h = team_gf.get(home+"_h", 1.4)
                ga_h = team_ga.get(home+"_h", 1.1)
                gf_a = team_gf.get(away+"_a", 1.1)
                ga_a = team_ga.get(away+"_a", 1.4)

                lam_h = max(0.25, min(3.0, gf_h * ga_a / lg_avg * 1.10))
                lam_a = max(0.25, min(3.0, gf_a * ga_h / lg_avg * 0.95))

                p1, px, p2 = monte_carlo(lam_h, lam_a)

                if odd_col1:
                    try:
                        o1 = float(row[odd_col1])
                        ox = float(row[odd_colX])
                        o2 = float(row[odd_col2])
                        tot = 1/o1 + 1/ox + 1/o2
                        p1 = p1*0.65 + (1/o1/tot)*0.35
                        px = px*0.65 + (1/ox/tot)*0.35
                        p2 = p2*0.65 + (1/o2/tot)*0.35
                    except Exception:
                        pass

                pred = "H" if p1==max(p1,px,p2) else ("D" if px>p2 else "A")
                if pred == actual: correct += 1

                o_h=1.0 if actual=="H" else 0.0
                o_d=1.0 if actual=="D" else 0.0
                o_a=1.0 if actual=="A" else 0.0
                brier_sum += ((p1-o_h)**2+(px-o_d)**2+(p2-o_a)**2)/3

                try:
                    fthg = float(row.get("FTHG",0)); ftag = float(row.get("FTAG",0))
                    team_gf[home+"_h"] = gf_h*(1-alpha)+fthg*alpha
                    team_ga[home+"_h"] = ga_h*(1-alpha)+ftag*alpha
                    team_gf[away+"_a"] = gf_a*(1-alpha)+ftag*alpha
                    team_ga[away+"_a"] = ga_a*(1-alpha)+fthg*alpha
                except Exception:
                    pass
                n += 1

            if n:
                acc   = correct/n
                brier = brier_sum/n
                grand_total   += n
                grand_correct += correct
                grand_brier   += brier_sum
                lbl = f"20{season[:2]}-{season[2:]}"
                rows_out.append((lig_name, lbl, n, acc, brier))

    print(f"\n  {'Lig':<18} {'Sezon':<9} {'Maç':>4}  {'Doğ%':>6}  {'Brier':>7}")
    print(f"  {'─'*55}")
    for lig, lbl, n, acc, brier in rows_out:
        ok = "✅" if brier < 0.22 else "⚠"
        print(f"  {lig:<18} {lbl:<9} {n:>4}  %{acc*100:>5.1f}  {brier:.4f} {ok}")

    if grand_total:
        g_acc   = grand_correct / grand_total
        g_brier = grand_brier / grand_total
        print(f"  {'─'*55}")
        print(f"  {'GENEL':<28} {grand_total:>4}  %{g_acc*100:>5.1f}  {g_brier:.4f}")
    print(f"  {'═'*62}")


def _run_lprm_report():
    """Menü 7→1→3: LPRM on/off karşılaştırma raporu."""
    print("\n" + "═"*62)
    print("  LPRM RAPORU — ON vs OFF Karşılaştırma")
    print("═"*62)

    print("\n  Analiz türü seçin:")
    print("    1. Tek Lig  (belirli bir lig seç)")
    print("    2. Toplu    (tüm ligler birlikte)")
    print("  Seçim (1/2, Enter=1): ", end="", flush=True)
    try:
        lrmode = input().strip()[:1]
        if lrmode not in ("1","2"): lrmode = "1"
    except Exception:
        lrmode = "1"

    if lrmode == "2":
        _run_lprm_report_toplu()
        return

    try:
        from analysis.lprm_report import generate_lprm_report, print_lprm_report
    except ImportError:
        print("  ⚠ analysis/lprm_report.py bulunamadı.")
        return

    try:
        from model.lprm import LPRMEngine
    except ImportError:
        print("  ⚠ model/lprm.py bulunamadı.")
        return

    LIG_MAP = {"1":("T1","Süper Lig"),"2":("E0","Premier League"),
               "3":("D1","Bundesliga"),"4":("SP1","La Liga"),
               "5":("I1","Serie A"),"6":("F1","Ligue 1")}
    print("\n  Lig seçin (LPRM için T1 önerilir):")
    for k,(c,n) in LIG_MAP.items(): print(f"    {k}. {n}")
    print("  Seçim (1-6, Enter=1): ", end="", flush=True)
    try:
        sel = input().strip()[:1]
        if sel not in LIG_MAP: sel = "1"
    except Exception:
        sel = "1"
    lig_code, lig_name = LIG_MAP[sel]

    base    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "fd_cache")
    seasons = [PAST_SEASONS[0], CURRENT_SEASON]
    dfs = []
    for s in seasons:
        fp = os.path.join(base, f"{lig_code}_{s}.csv")
        if os.path.exists(fp):
            try:
                dfs.append(pd.read_csv(fp, on_bad_lines='skip'))
            except Exception:
                pass

    if not dfs:
        print(f"  ⚠ {lig_code} verisi yok — Menü 6 ile indir")
        return

    df_all  = pd.concat(dfs, ignore_index=True)
    df_test = df_all[df_all["FTR"].isin(["H","D","A"])].dropna(
        subset=["FTR","B365H","B365D","B365A"]).copy()
    df_test = df_test.tail(150)
    if len(df_test) < 30:
        print(f"  ⚠ Test verisi yetersiz: {len(df_test)} maç")
        return

    print(f"\n  {lig_name}: {len(df_test)} maç test verisinde")

    engine = LPRMEngine(df_all, min_n=3)
    FTR_MAP = {"H":0, "D":1, "A":2}
    alpha   = 0.20; lg_avg = 1.30
    team_gf = {}; team_ga = {}
    matches = []

    for i, (_, row) in enumerate(df_test.iterrows()):
        home = str(row.get("HomeTeam","?")); away = str(row.get("AwayTeam","?"))
        y    = FTR_MAP.get(row["FTR"], 0)
        gf_h = team_gf.get(home+"_h",1.4); ga_h = team_ga.get(home+"_h",1.1)
        gf_a = team_gf.get(away+"_a",1.1); ga_a = team_ga.get(away+"_a",1.4)
        lam_h = max(0.25, min(3.0, gf_h*ga_a/lg_avg*1.10))
        lam_a = max(0.25, min(3.0, gf_a*ga_h/lg_avg*0.95))
        try:
            o1=float(row["B365H"]); ox=float(row["B365D"]); o2=float(row["B365A"])
        except Exception:
            o1=ox=o2=None

        matches.append({
            "features": {"home":home,"away":away,"lam_h":lam_h,"lam_a":lam_a,
                         "o1":o1,"ox":ox,"o2":o2,"week":20+i//10},
            "y": y,
            "odds": [o1 or 2.0, ox or 3.3, o2 or 3.8],
        })
        try:
            fthg=float(row.get("FTHG",0)); ftag=float(row.get("FTAG",0))
            team_gf[home+"_h"]=gf_h*(1-alpha)+fthg*alpha
            team_ga[home+"_h"]=ga_h*(1-alpha)+ftag*alpha
            team_gf[away+"_a"]=gf_a*(1-alpha)+ftag*alpha
            team_ga[away+"_a"]=ga_a*(1-alpha)+fthg*alpha
        except Exception:
            pass

    def predict_fn(features, use_lprm=False):
        lam_h = features["lam_h"]; lam_a = features["lam_a"]
        p1, px, p2 = monte_carlo(lam_h, lam_a)
        try:
            o1=features["o1"]; ox=features["ox"]; o2=features["o2"]
            tot=1/o1+1/ox+1/o2
            p1=p1*0.65+(1/o1/tot)*0.35
            px=px*0.65+(1/ox/tot)*0.35
            p2=p2*0.65+(1/o2/tot)*0.35
        except Exception:
            pass
        if use_lprm:
            try:
                r = engine.analyze(home=features["home"], away=features["away"],
                                   odds_h=features.get("o1"),
                                   week=features.get("week",20))
                lh2=lam_h*r["lambda_adj_h"]; la2=lam_a*r["lambda_adj_a"]
                p1b,pxb,p2b = monte_carlo(lh2, la2)
                p1=p1*0.70+p1b*0.30; px=px*0.70+pxb*0.30; p2=p2*0.70+p2b*0.30
                total=p1+px+p2; p1/=total; px/=total; p2/=total
            except Exception:
                pass
        return np.array([p1, px, p2])

    print(f"  {len(matches)} maç hazır, rapor üretiliyor...")
    report = generate_lprm_report(matches, predict_fn, n_bootstrap=500)
    print_lprm_report(report)


def _run_lprm_report_toplu():
    """Menü 7→1→3→2: Tüm ligler LPRM raporu."""
    print("\n" + "═"*62)
    print("  LPRM TOPLU RAPORU — Tüm Ligler")
    print("═"*62)

    try:
        from analysis.lprm_report import generate_lprm_report, print_lprm_report
        from model.lprm          import LPRMEngine
    except ImportError as e:
        print(f"  ✗ Modül hatası: {e}")
        return

    LIGS    = [("T1","Süper Lig"),("E0","Premier League"),
               ("D1","Bundesliga"),("SP1","La Liga"),
               ("I1","Serie A"),("F1","Ligue 1")]
    SEASONS = [PAST_SEASONS[0], CURRENT_SEASON]
    base    = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "fd_cache")
    FTR_MAP = {"H":0,"D":1,"A":2}
    all_results = {}

    for lig_code, lig_name in LIGS:
        dfs = []
        for s in SEASONS:
            fp = os.path.join(base, f"{lig_code}_{s}.csv")
            if os.path.exists(fp):
                try: dfs.append(pd.read_csv(fp, on_bad_lines='skip'))
                except Exception: pass
        if not dfs:
            continue

        df_all  = pd.concat(dfs, ignore_index=True)
        df_test = df_all[df_all["FTR"].isin(["H","D","A"])].dropna(
            subset=["FTR","B365H","B365D","B365A"]).copy()
        df_test = df_test.tail(100)
        if len(df_test) < 20:
            continue

        engine  = LPRMEngine(df_all, min_n=3)
        alpha   = 0.20; lg_avg = 1.30
        team_gf = {}; team_ga = {}
        matches = []

        for i, (_, row) in enumerate(df_test.iterrows()):
            home=str(row.get("HomeTeam","?")); away=str(row.get("AwayTeam","?"))
            y=FTR_MAP.get(row["FTR"],0)
            gf_h=team_gf.get(home+"_h",1.4); ga_h=team_ga.get(home+"_h",1.1)
            gf_a=team_gf.get(away+"_a",1.1); ga_a=team_ga.get(away+"_a",1.4)
            lam_h=max(0.25,min(3.0,gf_h*ga_a/lg_avg*1.10))
            lam_a=max(0.25,min(3.0,gf_a*ga_h/lg_avg*0.95))
            try:
                o1=float(row["B365H"]); ox=float(row["B365D"]); o2=float(row["B365A"])
            except Exception:
                o1=ox=o2=None
            matches.append({"features":{"home":home,"away":away,
                                        "lam_h":lam_h,"lam_a":lam_a,
                                        "o1":o1,"ox":ox,"o2":o2,"week":20+i//10},
                            "y":y,"odds":[o1 or 2.0, ox or 3.3, o2 or 3.8]})
            try:
                fthg=float(row.get("FTHG",0)); ftag=float(row.get("FTAG",0))
                team_gf[home+"_h"]=gf_h*(1-alpha)+fthg*alpha
                team_ga[home+"_h"]=ga_h*(1-alpha)+ftag*alpha
                team_gf[away+"_a"]=gf_a*(1-alpha)+ftag*alpha
                team_ga[away+"_a"]=ga_a*(1-alpha)+fthg*alpha
            except Exception: pass

        def predict_fn(features, use_lprm=False):
            lh=features["lam_h"]; la=features["lam_a"]
            p1,px,p2=monte_carlo(lh,la)
            try:
                o1=features["o1"]; ox=features["ox"]; o2=features["o2"]
                tot=1/o1+1/ox+1/o2
                p1=p1*0.65+(1/o1/tot)*0.35; px=px*0.65+(1/ox/tot)*0.35
                p2=p2*0.65+(1/o2/tot)*0.35
                total=p1+px+p2; p1/=total; px/=total; p2/=total
            except Exception: pass
            if use_lprm:
                try:
                    r=engine.analyze(home=features["home"],away=features["away"],
                                     odds_h=features.get("o1"),week=features.get("week",20))
                    lh2=lh*r["lambda_adj_h"]; la2=la*r["lambda_adj_a"]
                    p1b,pxb,p2b=monte_carlo(lh2,la2)
                    p1=p1*0.70+p1b*0.30; px=px*0.70+pxb*0.30; p2=p2*0.70+p2b*0.30
                    total=p1+px+p2; p1/=total; px/=total; p2/=total
                except Exception: pass
            return np.array([p1,px,p2])

        print(f"\n  {lig_name} ({len(matches)} maç)...", end="", flush=True)
        report = generate_lprm_report(matches, predict_fn, n_bootstrap=200)
        all_results[lig_name] = report
        b_delta = report["brier"]["delta"]
        verdict = ("✅ Güvenilir" if report["bootstrap"]["significant"] else
                   "🟡 Faydalı"  if b_delta < 0 else
                   "❌ Zararlı"  if b_delta > 0.002 else "⚪ Nötr")
        print(f" Brier Δ={b_delta:+.4f}  {verdict}")

    print(f"\n{'='*62}")
    print(f"  TOPLU LPRM RAPORU ÖZET")
    print(f"{'='*62}")
    print(f"  {'Lig':<18} {'Brier OFF':>10} {'Brier ON':>10} {'Δ':>7}  Verdict")
    print(f"  {'─'*55}")
    for lig, r in all_results.items():
        b=r["brier"]; bs=r["bootstrap"]
        v=("✅" if bs["significant"] else
           "🟡" if b["delta"]<0 else
           "⚪" if b["delta"]<=0.002 else "❌")
        print(f"  {lig:<18} {b['off']:>10.4f} {b['on']:>10.4f} {b['delta']:>+7.4f}  {v}")
    print(f"  {'═'*62}")


def _run_ab_test():
    """Menü 7→1→4: A/B Test — Devret & Pozisyon ON/OFF."""
    import re as _re

    print("\n" + "═"*62)
    print("  A/B TEST — Devret & Pozisyon ON/OFF Karşılaştırma")
    print("═"*62)

    try:
        from tools.ab_test import MatchInput, run_ab_test, print_ab_report, Prediction
    except ImportError:
        try:
            _tools = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "tools")
            sys.path.insert(0, _tools)
            from ab_test import MatchInput, run_ab_test, print_ab_report, Prediction
        except ImportError:
            print("  ✗ ab_test.py bulunamadı → tools/ klasörüne koy")
            return

    print("\n  Hangi haftadan itibaren? (örn: ST41-2526, boş=tümü): ",
          end="", flush=True)
    try:
        from_week = input().strip() or None
    except Exception:
        from_week = None

    base_dir  = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".."))
    pred_path = os.path.join(base_dir, "st_predictions.json")
    mem_path  = os.path.join(base_dir, "st_memory.json")

    if not os.path.exists(pred_path):
        print(f"  ✗ {pred_path} bulunamadı")
        return

    print("\n[1] Maçlar yükleniyor...")
    with open(pred_path, encoding="utf-8") as f:
        preds = json.load(f)
    mem_data = {}
    if os.path.exists(mem_path):
        with open(mem_path, encoding="utf-8") as f:
            mem_data = json.load(f)

    devret_weeks = set()
    for h in mem_data.get("weekly_history", []):
        if h.get("prize_15_prev") == "Devretti":
            devret_weeks.add(h.get("week",""))

    def _wk_num(wid):
        m = _re.match(r'ST(\d+)-(\d+)', wid)
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    matches = []
    for week_id, wdata in preds.items():
        if from_week and _wk_num(week_id) < _wk_num(from_week):
            continue
        week_matches = wdata.get("matches", [])
        if not any(m.get("actual") for m in week_matches):
            continue
        is_devret = week_id in devret_weeks
        for m in week_matches:
            actual = m.get("actual")
            if not actual:
                continue
            result = {"H":"1","D":"X","A":"2","0":"X"}.get(actual, actual)
            matches.append(MatchInput(
                match_id  = f"{week_id}-M{m.get('no',0)}",
                position  = m.get("no", 1),
                home_team = m.get("home","?"),
                away_team = m.get("away","?"),
                odds_home = float(m.get("odds",{}).get("1") or 2.0),
                odds_draw = float(m.get("odds",{}).get("X") or 3.3),
                odds_away = float(m.get("odds",{}).get("2") or 3.8),
                result    = result,
                week_id   = week_id,
                is_devret = is_devret,
            ))

    n = len(matches)
    if n < 30:
        print(f"  ⚠ Yeterli maç yok: {n} (min 30 gerekli)")
        return

    n_devret = sum(1 for m in matches if m.is_devret)
    print(f"  ✓ {n} maç | Devret: {n_devret}")
    if n_devret == 0:
        print("  ⚠ UYARI: Hiç devret haftası yok.")
    if n < 100:
        print(f"  ⚠ UYARI: {n} maç istatistiksel güvenilirlik için yetersiz.")

    def predict_fn(match: MatchInput, devret_on: bool, pos_on: bool):
        try:
            from model.monte_carlo import implied_probs
            from model.suggest     import suggest as _suggest

            eps = 1e-6
            o1=max(match.odds_home,eps); ox=max(match.odds_draw,eps); o2=max(match.odds_away,eps)
            raw_1,raw_x,raw_2 = 1/o1,1/ox,1/o2
            tot=raw_1+raw_x+raw_2
            p1,px,p2 = raw_1/tot,raw_x/tot,raw_2/tot

            if pos_on and match.position:
                try:
                    from model.position_bias import get_position_bias
                    pb=get_position_bias(match.position)
                    if pb:
                        p1+=pb.get("1",0.0); px+=pb.get("X",0.0); p2+=pb.get("2",0.0)
                        t=p1+px+p2
                        if t>0: p1,px,p2=p1/t,px/t,p2/t
                except Exception: pass

            if devret_on and match.is_devret:
                try:
                    from memory.devret_rule import DEVRET_ADJUSTMENTS
                    px+=DEVRET_ADJUSTMENTS.get("x_bias_boost",0.04)
                except Exception:
                    px+=0.04
                t=p1+px+p2
                if t>0: p1,px,p2=p1/t,px/t,p2/t

            _pos_kw = match.position if pos_on else None
            try:
                label,_,_ = _suggest(p1,px,p2,position=_pos_kw,
                                     lprm_draw_signal=(devret_on and match.is_devret))
            except Exception:
                best=max(p1,px,p2)
                label = "TEK   1" if best==p1 else ("TEK   X" if best==px else "TEK   2")

            return Prediction(p1=p1,px=px,p2=p2,suggestion=label)
        except Exception:
            return Prediction(p1=0.45,px=0.27,p2=0.28,suggestion="TEK   1")

    print("\n[2] 4 senaryo test ediliyor...")
    results = run_ab_test(matches, predict_fn)
    print_ab_report(results)


def _run_scenario_analysis():
    """Menü 7→3: What-If Senaryo Analizi."""
    try:
        from model.monte_carlo import poisson_analytical
    except ImportError:
        print("  Hata: monte_carlo yuklenemedi"); return

    print("\n" + "="*60)
    print("  SENARYO ANALIZI - What-If")
    print("="*60)
    print("  Ev takim (fd adi): ", end="", flush=True)
    home = input().strip()
    print("  Dep takim: ", end="", flush=True)
    away = input().strip()
    if not home or not away: return
    print("  Lig kodu (Enter=T1): ", end="", flush=True)
    lg = input().strip() or "T1"

    try:
        from model.team_stats  import build_team_stats
        from data.downloader   import download_league
        from model.lambda_calc import calc_lambda
        df = download_league(lg, ST_SEASON_TAG)
        if isinstance(df, tuple): df = df[0]
        st, avg, _ = build_team_stats(df)
        lam_h, lam_a = calc_lambda(home, away, st, avg, None, None, league_code=lg)
    except Exception:
        print("  Manuel giris:")
        lam_h = float(input("  lam_h (1.5): ").strip() or "1.5")
        lam_a = float(input("  lam_a (1.2): ").strip() or "1.2")

    def _s(lh, la, tag):
        p1,px,p2=poisson_analytical(lh,la,league_code=lg)
        print(f"  {tag:<30}  1={p1*100:.1f}%  X={px*100:.1f}%  2={p2*100:.1f}%  lH={lh:.2f} lA={la:.2f}")

    print("\n  Senaryolar:")
    _s(lam_h, lam_a, "BAZ (mevcut)")
    _s(lam_h*0.88, lam_a, "Ev yildiz eksik (-%12)")
    _s(lam_h, lam_a*0.88, "Dep yildiz eksik (-%12)")
    _s(lam_h/1.08, lam_a, "Tarafsiz saha")
    p1b,pxb,p2b=poisson_analytical(lam_h,lam_a,league_code=lg)
    pxd=min(0.55,pxb*1.30); norm=p1b+pxd+p2b
    print(f"  {'Devret (X +%30)':<30}  1={p1b/norm*100:.1f}%  X={pxd/norm*100:.1f}%  2={p2b/norm*100:.1f}%")

    print("\n  En Olasilikh Skorlar:")
    def pmf_fn(lam, k): return (lam**k * math.exp(-lam)) / math.factorial(k)
    sc_list=sorted([(pmf_fn(lam_h,h)*pmf_fn(lam_a,a)*100,h,a)
                    for h in range(6) for a in range(6)],reverse=True)
    for prob,h,a in sc_list[:8]:
        res="1" if h>a else ("X" if h==a else "2")
        bar=chr(9608)*int(prob/2)
        print(f"    {h}-{a} ({res})  %{prob:4.1f}  {bar}")
    print()
    input("  Enter ile devam...")
