# -*- coding: utf-8 -*-
"""
memory/model_health.py — Model Sağlık Paneli
=============================================
Sistemin tüm bileşenlerini tek ekranda değerlendirir.

Bölümler:
  1. Genel Sağlık Skoru   (A/B/C/D)
  2. ML Model Durumu      (doğruluk, ağırlık, kalibrasyon)
  3. Poisson/Lambda       (lig bazlı rho, lambda hedef)
  4. Hafıza Kalitesi      (Brier trend, hata desenleri)
  5. CLV & Edge           (kapanış çizgisi değeri)
  6. API & Cache          (günlük kullanım, cache yaşı)
  7. Aksiyon Listesi      (somut öneriler)
"""
from __future__ import annotations
import os, json, pickle, math, time, sys
from datetime import datetime

R  = "\033[0m";  B  = "\033[1m";  DM = "\033[2m"
G  = "\033[32m"; Y  = "\033[33m"; RE = "\033[31m"; C  = "\033[36m"

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

def _w(text=""):
    sys.stdout.write(str(text) + "\r\n")
    sys.stdout.flush()

def _bar(val, max_val=1.0, width=12, low_good=False):
    r = min(1.0, max(0.0, val / max_val)) if max_val else 0
    f = round(r * width)
    bar = chr(9608)*f + chr(9617)*(width-f)
    if low_good:
        col = G if r < 0.4 else (Y if r < 0.65 else RE)
    else:
        col = G if r >= 0.65 else (Y if r >= 0.45 else RE)
    return f"{col}{bar}{R}"

def _grade(score):
    if score >= 85: return f"{G}{B}A{R}"
    if score >= 70: return f"{G}B+{R}"
    if score >= 55: return f"{Y}B{R}"
    if score >= 40: return f"{Y}C{R}"
    return f"{RE}D{R}"

def _sep(w=56, c="-"):
    return f"  {DM}{c*w}{R}"


def _section_ml():
    lines = []
    score = 0
    model_file = os.path.join(_ROOT, "ml_model.pkl")
    lines.append(f"\n  {B}{C}[2] ML MODEL DURUMU{R}")
    lines.append(_sep())

    if not os.path.exists(model_file):
        lines.append(f"  {Y}ml_model.pkl bulunamadi{R}")
        return lines, 0

    try:
        with open(model_file, "rb") as f:
            data = pickle.load(f)
        acc     = data.get("accuracy", {})
        trained = data.get("trained", {})
        n_sam   = data.get("n_samples", 0)
        fi      = data.get("fi", {})
        mtime   = os.path.getmtime(model_file)
        age_d   = (time.time() - mtime) / 86400
        age_str = f"{age_d:.0f} gun once" if age_d > 1 else "bugun"

        lines.append(f"  Egitim verisi : {B}{n_sam:,}{R} mac")
        lines.append(f"  Son egitim    : {DM}{age_str}{R}")
        if age_d > 30:
            lines.append(f"  {Y}  Model {age_d:.0f} gun once egitildi — yenile{R}")

        lines.append(f"\n  {'Model':<6} {'Dogruluk':>9}  Agirlik(acc^4)   Durum")
        lines.append(f"  {DM}{'-'*48}{R}")
        model_scores = []
        for name in ["lr","gb","mlp","rf"]:
            if not trained.get(name): continue
            a = acc.get(name, 0)
            w = round(a**4, 5)
            bar = _bar(a, 0.60, 8)
            verdict = f"{G}OK{R}" if a >= 0.54 else (f"{Y}Orta{R}" if a >= 0.50 else f"{RE}Dusuk{R}")
            lines.append(f"  {name.upper():<6} %{a*100:>6.1f}    {w:>12.5f}  {bar} {verdict}")
            model_scores.append(a)

        if model_scores:
            avg_acc = sum(model_scores) / len(model_scores)
            score = max(0, min(100, (avg_acc - 0.50) * 1000))

        if fi:
            lines.append(f"\n  {DM}Top-5 Ozellik (GB):{R}")
            for k, v in list(fi.items())[:5]:
                bar = _bar(v, 0.25, 10)
                lines.append(f"  {DM}{k:<22} {v:.4f}  {bar}{R}")

        gb = data.get("gb")
        if gb and hasattr(gb, "calibrated_classifiers_"):
            lines.append(f"\n  {G}Platt Scaling  : Aktif (sigmoid){R}")
            score = min(100, score + 10)
        else:
            lines.append(f"\n  {Y}Platt Scaling  : Aktif degil{R}")

    except Exception as e:
        lines.append(f"  {RE}Model yuklenemedi: {e}{R}")
        return lines, 0

    return lines, round(score)


def _section_poisson():
    lines = []
    lines.append(f"\n  {B}{C}[3] POISSON & LAMBDA{R}")
    lines.append(_sep())
    score = 70

    try:
        if _ROOT not in sys.path:
            sys.path.insert(0, _ROOT)
        from config import DIXON_COLES_RHO, CFG
        lt = CFG.get("lambda_target", 2.60)
        ha = CFG.get("home_advantage", 1.10)
        mw = CFG.get("model_weight", 0.65)
        ow = CFG.get("odds_weight", 0.35)

        lines.append(f"  Lambda hedef   : {B}{lt}{R}  (lig ort. toplam gol)")
        lines.append(f"  Ev avantaji    : {B}{ha:.2f}x{R}  (takim bazli dinamik)")
        lines.append(f"  Model/Oran mix : {B}{int(mw*100)}%{R} model + {int(ow*100)}% oran")
        lines.append(f"  Monte Carlo    : {G}Saf analitik (MC blend kaldirildi){R}")
        lines.append(f"\n  {DM}Dixon-Coles rho (lig bazli):{R}")
        rho_info = {
            "T1":"Super Lig", "E0":"Premier League",
            "D1":"Bundesliga", "I1":"Serie A", "SP1":"La Liga",
            "F1":"Ligue 1", "N1":"Eredivisie",
        }
        for lig, rho in list(DIXON_COLES_RHO.items())[:7]:
            comment = rho_info.get(lig, "")
            col = G if rho <= -0.12 else (Y if rho > -0.10 else DM)
            lines.append(f"  {lig:<6} {col}{rho:>7.3f}{R}  {DM}{comment}{R}")
        score = 75
    except Exception as e:
        lines.append(f"  {Y}config yuklenemedi: {e}{R}")

    return lines, score


def _section_memory(mem_data):
    lines = []
    lines.append(f"\n  {B}{C}[4] HAFIZA KALİTESİ{R}")
    lines.append(_sep())

    wh  = [h for h in mem_data.get("weekly_history",[]) if h.get("status")=="completed"]
    ep  = mem_data.get("error_patterns", {})

    if not wh:
        lines.append(f"  {DM}Hafta verisi yok{R}")
        return lines, 0

    total   = sum(h.get("total",0) for h in wh)
    correct = sum(h.get("correct",0) for h in wh)
    acc     = correct / total if total else 0
    score   = max(0, min(100, (acc - 0.55) * 500))

    lines.append(f"  Genel dogruluk : {B}%{acc*100:.1f}{R}  ({correct}/{total})  "
                 f"{_bar(acc,0.80,10)}  {_grade(score)}")

    briers = [h["brier"] for h in wh if h.get("brier")]
    if briers:
        avg_b = sum(briers)/len(briers)
        trend = briers[-1] - briers[0] if len(briers)>1 else 0
        if trend > 0.02:   ts = f"{RE}Kötülesıyor (+{trend:.3f}){R}"
        elif trend < -0.02:ts = f"{G}Iyilesıyor ({trend:+.3f}){R}"
        else:              ts = f"{Y}Stabil ({trend:+.3f}){R}"
        lines.append(f"  Brier skoru    : {B}{avg_b:.3f}{R}  {_bar(avg_b,0.33,10,True)}  {ts}")

    lines.append(f"\n  {DM}Hata Desenleri:{R}")
    patterns = {
        "kaos_actual_draw":    ("KAOS -> beraberlik",     True),
        "banko_fail_away_fav": ("Dep BANKO yanilma",      True),
        "banko_fail_home_fav": ("Ev BANKO yanilma",       False),
        "high_conf_draw_miss": ("Yuksek guven X kacirma", False),
    }
    for key, (label, critical) in patterns.items():
        d = ep.get(key, {})
        n, w = d.get("total",0), d.get("wrong",0)
        if n < 3: continue
        rate = w/n
        col  = RE if rate >= 0.55 else (Y if rate >= 0.40 else G)
        icon = "!!" if (critical and rate >= 0.55) else ("~" if rate >= 0.40 else "OK")
        lines.append(f"  {col}{icon}{R} {label:<30} %{rate*100:.0f} ({w}/{n})")
        if critical and rate >= 0.55:
            score = max(0, score - 10)

    return lines, round(score)


def _section_clv():
    lines = []
    lines.append(f"\n  {B}{C}[5] CLV & EDGE{R}")
    lines.append(_sep())
    score = 50

    clv_file = os.path.join(_ROOT, "clv_history.json")
    if not os.path.exists(clv_file):
        lines.append(f"  {DM}CLV verisi yok — Menu 1 analizi sonrasi olusur{R}")
        return lines, 50

    try:
        data = json.load(open(clv_file, encoding="utf-8"))
        recs = data.get("records", [])
        n    = len(recs)
        if n == 0:
            lines.append(f"  {DM}Kayit yok{R}")
            return lines, 50

        clv_vals = [r["clv"] for r in recs if r.get("clv") is not None]
        done     = [r for r in recs if r.get("outcome") in ("W","L")]

        lines.append(f"  Toplam kayit  : {B}{n}{R} tahmin")
        if clv_vals:
            avg_clv = sum(clv_vals)/len(clv_vals)
            pos_pct = sum(1 for v in clv_vals if v>0)/len(clv_vals)
            col = G if avg_clv > 0.02 else (Y if avg_clv > 0 else RE)
            lines.append(f"  Ort. CLV      : {col}{B}%{avg_clv*100:+.2f}{R}  "
                         f"(%{round(pos_pct*100)} pozitif)")
            if avg_clv > 0.02 and n >= 30:
                lines.append(f"  {G}GUCLU EDGE tespit edildi{R}")
                score = 90
            elif avg_clv > 0:
                lines.append(f"  {Y}Zayif edge — daha fazla veri gerekli{R}")
                score = 60
            else:
                lines.append(f"  {RE}Edge yok — strateji gozden gecir{R}")
                score = 20

        if done:
            wr = sum(1 for r in done if r["outcome"]=="W")/len(done)
            lines.append(f"  Kazanma orani : %{wr*100:.1f}  ({len(done)} sonuclanan)")

    except Exception as e:
        lines.append(f"  {Y}CLV yuklenemedi: {e}{R}")

    return lines, score


def _section_api_cache():
    lines = []
    lines.append(f"\n  {B}{C}[6] API & CACHE{R}")
    lines.append(_sep())
    score = 70

    try:
        if _ROOT not in sys.path:
            sys.path.insert(0, _ROOT)
        from data.api_football import APIFootball, DAILY_LIMIT
        api = APIFootball()
        u   = api._get_usage()
        n   = u.get("count", 0)
        pct = n / DAILY_LIMIT * 100
        col = G if pct < 60 else (Y if pct < 85 else RE)
        bar = _bar(n, DAILY_LIMIT, 12, low_good=True)
        lines.append(f"  API Kullenim  : {col}{B}{n}/{DAILY_LIMIT}{R} ({pct:.1f}%)  {bar}")
        ep = u.get("endpoints", {})
        if ep:
            top3 = sorted(ep.items(), key=lambda x: -x[1])[:3]
            lines.append(f"  {DM}Top endpoint: " +
                         ", ".join(f"{k}({v})" for k,v in top3) + R)
        if not api.key:
            lines.append(f"  {RE}API_KEY eksik!{R}")
            score = 30
        else:
            lines.append(f"  API Key       : {G}...{api.key[-4:]}{R}  Pro (7500/gun)")
    except Exception:
        lines.append(f"  {DM}API durumu alinamadi{R}")

    cache_dir = os.path.join(_ROOT, "fd_cache")
    if os.path.exists(cache_dir):
        pkl_files = [f for f in os.listdir(cache_dir) if f.endswith(".pkl")]
        total_mb  = sum(os.path.getsize(os.path.join(cache_dir,f))
                       for f in pkl_files)/1024/1024
        lines.append(f"  Cache dosyasi : {B}{len(pkl_files)}{R} pkl  ({total_mb:.1f} MB)")
        if pkl_files:
            ages = [(f,(time.time()-os.path.getmtime(os.path.join(cache_dir,f)))/3600)
                    for f in pkl_files]
            newest = min(ages, key=lambda x: x[1])
            lines.append(f"  {DM}En yeni: {newest[0][:25]} ({newest[1]:.0f}sa once){R}")

    return lines, score


def run_health_check(mem_obj) -> None:
    mem_data = mem_obj.mem if hasattr(mem_obj, "mem") else {}

    _w()
    _w(f"  {B}{C}{'='*58}{R}")
    _w(f"  {B}{C}  MODEL SAGLIK PANELİ  --  AUGUR ENGINE{R}")
    _w(f"  {DM}  {datetime.now().strftime('%d.%m.%Y  %H:%M')}{R}")
    _w(f"  {B}{C}{'='*58}{R}")

    ml_lines,  ml_score  = _section_ml()
    poi_lines, poi_score = _section_poisson()
    mem_lines, mem_score = _section_memory(mem_data)
    clv_lines, clv_score = _section_clv()
    api_lines, api_score = _section_api_cache()

    weights = [(ml_score,0.35),(mem_score,0.35),(clv_score,0.15),
               (poi_score,0.10),(api_score,0.05)]
    genel   = round(sum(s*w for s,w in weights))

    _w()
    _w(f"  {B}{C}[1] GENEL SAGLIK SKORU{R}")
    _w(_sep())
    _w(f"  Genel Skor     : {B}{genel}/100{R}  {_bar(genel,100,14)}  {_grade(genel)}")
    _w(f"  {DM}  ML:{ml_score}  Hafiza:{mem_score}  CLV:{clv_score}  "
       f"Poisson:{poi_score}  API:{api_score}{R}")
    if genel >= 85:   _w(f"  {G}{B}Sistem HARIKA calisiyor{R}")
    elif genel >= 70: _w(f"  {G}Sistem IYI durumda{R}")
    elif genel >= 50: _w(f"  {Y}Sistem ORTA -- iyilestirme onerisi var{R}")
    else:             _w(f"  {RE}Sistem mudahale gerektiriyor{R}")

    for sec in [ml_lines, poi_lines, mem_lines, clv_lines, api_lines]:
        for line in sec:
            for subline in line.split('\n'):
                _w(subline)
        _w()

    # Aksiyon listesi
    _w(f"  {B}{C}[7] AKSIYON LİSTESİ{R}")
    _w(_sep())
    actions = []
    ep = mem_data.get("error_patterns", {})
    wh = [h for h in mem_data.get("weekly_history",[]) if h.get("status")=="completed"]

    model_file = os.path.join(_ROOT, "ml_model.pkl")
    if os.path.exists(model_file):
        age_d = (time.time()-os.path.getmtime(model_file))/86400
        if age_d > 30:
            actions.append((Y, f"ML modeli {age_d:.0f} gun once egitildi",
                            "Menu 5 ile yeniden egit"))

    kaos_ep = ep.get("kaos_actual_draw",{})
    if kaos_ep.get("total",0)>=5 and kaos_ep.get("wrong",0)/kaos_ep["total"]>=0.55:
        actions.append((RE, "KAOS beraberligi cok kaciriyor",
                        "kaos_entropy_thr degerini 0.92'ye yukselt"))

    dep_ep = ep.get("banko_fail_away_fav",{})
    if dep_ep.get("total",0)>=5 and dep_ep.get("wrong",0)/dep_ep["total"]>=0.50:
        actions.append((RE, "Dep favorisi BANKO %60 yaniliyor",
                        "banko_threshold 0.70'e cek"))

    briers = [h["brier"] for h in wh if h.get("brier")]
    if len(briers)>=3 and briers[-1]-briers[0]>0.02:
        actions.append((Y, f"Brier {briers[0]:.3f} -> {briers[-1]:.3f} kötülesıyor",
                        "Kalibrasyon alpha degerini artir"))

    if clv_score < 30:
        actions.append((RE, "CLV negatif -- model kapanıs cizgisinin gerisinde",
                        "odds_weight 0.40'a cek"))

    if not actions:
        actions.append((G, "Sistem iyi durumda", "Parametreleri koru"))

    for i, (col, action, detail) in enumerate(actions, 1):
        _w(f"  {col}{B}{i}.{R} {action}")
        _w(f"     -- {detail}")
        _w()

    _w(_sep(58, "="))
    _w(f"  {DM}Saglik skoru: {genel}/100  |  {datetime.now().strftime('%H:%M')}{R}")
    _w(_sep(58, "="))
