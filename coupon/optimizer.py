# -*- coding: utf-8 -*-
"""Kupon Seviyesi Optimizer — v4"""
from config import *

COST_PER_COLUMN   = CFG.get("unit_price", 10)
MAX_COLS_PER      = CFG.get("max_cols_per_coupon", 2500)
MIN_BANKO_PROB    = 0.50
STRONG_BANKO_PROB = 0.65
KAOS_SPREAD_LIMIT = 0.10
MAX_BANKOS        = 3
MAX_KAOS          = 3
MAX_CIFT          = 5
MIN_COLS          = CFG.get("min_columns", 32)
UNIT              = COST_PER_COLUMN

def _spread(r):
    p = sorted([r["P1"],r["PX"],r["P2"]],reverse=True)
    return (p[0]-p[1])/100.0

def _max_prob(r):
    return max(r["P1"],r["PX"],r["P2"])/100.0

def _column_count(nc,nk):
    return (2**nc)*(3**nk)

def _score_distribution(nc,nk,budget,base):
    cols = _column_count(nc,nk)
    cost = cols*UNIT
    bp   = abs(cost-budget)/max(1,budget)
    sp   = max(0,(nk-MAX_KAOS)*0.5)+max(0,(nc-MAX_CIFT)*0.3)
    wc   = base.get("CIFT",0)+base.get("TEK",0)
    wk   = base.get("KAOS",0)
    dr   = abs(nc-wc)*0.05+abs(nk-wk)*0.10
    return bp+sp+dr, cols, cost

def _pick_best_distribution(budget,base,n=15):
    best=None
    for nk in range(0,min(MAX_KAOS+1,n+1)):
        for nc in range(0,min(MAX_CIFT+1,n-nk+1)):
            nb=n-nc-nk
            if nb<0: continue
            score,cols,cost=_score_distribution(nc,nk,budget,base)
            if cost>budget*1.30: continue
            if best is None or score<best["score"]:
                best={"n_banko":nb,"n_cift":nc,"n_kaos":nk,
                      "cols":cols,"cost":cost,"score":score}
    return best

def _best_outcome(r):
    p={"1":r["P1"],"X":r["PX"],"2":r["P2"]}
    return max(p,key=p.get)

def _top2_outcomes(r):
    pr=sorted([("1",r["P1"]),("X",r["PX"]),("2",r["P2"])],key=lambda x:-x[1])
    t=[pr[0][0],pr[1][0]]
    if "X" not in t and r["PX"]>=26 and (pr[0][1]-r["PX"])<14:
        non_x=[k for k in t if k!="X"]
        loser=min(non_x,key=lambda k:{"1":r["P1"],"X":r["PX"],"2":r["P2"]}[k])
        t=[k for k in t if k!=loser]+["X"]
    return "CIFT  "+"".join(sorted(t))

def _sel_score(r):
    p={"1":r["P1"]/100,"X":r["PX"]/100,"2":r["P2"]/100}
    sel=r.get("oneri","").split()[-1].strip()
    sp=max(sum(p.get(c,0) for c in sel),1e-9)
    return sp/(1.0+r.get("entropy",1.0))

def classify_match(r):
    mp=_max_prob(r); sp=_spread(r); H=r.get("entropy",1.0)
    if r.get("is_kaos") or H>=1.05 or sp<KAOS_SPREAD_LIMIT: return "CHAOTIC"
    if mp>=STRONG_BANKO_PROB: return "SURE"
    if mp>=0.50: return "LIKELY"
    return "UNCERTAIN"

def classify_matches_budget(results,budget):
    n=len(results)
    base={}
    for r in results:
        lbl="KAOS" if r.get("is_kaos") else ("CIFT" if r["mul"]==2 else "TEK")
        base[lbl]=base.get(lbl,0)+1
    dist=_pick_best_distribution(budget,base,n)
    if not dist:
        dist={"n_banko":n,"n_cift":0,"n_kaos":0,"cols":1,"cost":UNIT,"score":999}

    for r in results:
        r["_spread"]=_spread(r); r["_max_prob"]=_max_prob(r)

    kaos_cands=sorted([r for r in results if r.get("is_kaos") or r.get("entropy",1)>=1.05],
                      key=lambda r:r["_spread"])
    kaos_sel={r["no"] for r in kaos_cands[:dist["n_kaos"]]}

    banko_cands=sorted([r for r in results
                        if r["no"] not in kaos_sel
                        and r["_max_prob"]>=MIN_BANKO_PROB
                        and r["_spread"]>=KAOS_SPREAD_LIMIT],
                       key=lambda r:(r["_max_prob"],r["_spread"]),reverse=True)
    banko_sel={r["no"] for r in banko_cands[:min(dist["n_banko"],MAX_BANKOS)]}

    remaining=[r for r in results if r["no"] not in kaos_sel and r["no"] not in banko_sel]
    cift_sel={r["no"] for r in sorted(remaining,key=lambda r:r["_max_prob"])[:dist["n_cift"]]}

    working=[]
    for r in results:
        rc=dict(r); no=rc["no"]
        if no in kaos_sel:
            rc["mul"]=3; rc["oneri"]="KAOS  1X2"; rc["is_kaos"]=True; rc["_risk"]="CHAOTIC"
        elif no in banko_sel:
            rc["mul"]=1; rc["oneri"]="BANKO "+_best_outcome(rc); rc["is_kaos"]=False
            rc["_risk"]="SURE" if rc["_max_prob"]>=STRONG_BANKO_PROB else "LIKELY"
        elif no in cift_sel:
            rc["mul"]=2; rc["oneri"]=_top2_outcomes(rc); rc["is_kaos"]=False; rc["_risk"]="LIKELY"
        else:
            rc["mul"]=1; rc["oneri"]="TEK   "+_best_outcome(rc); rc["is_kaos"]=False; rc["_risk"]="UNCERTAIN"
        working.append(rc)
    return working, dist

def coupon_level_optimize(results,budget):
    working,dist=classify_matches_budget(results,budget)
    cols=1
    for r in working: cols*=r["mul"]
    steps=[(None,None,f"Dağılım: {dist['n_banko']}B+{dist['n_cift']}C+{dist['n_kaos']}K={dist['cols']}kolon",dist["cost"])]
    if cols<MIN_COLS:
        print(f"  [!] Min kolon ({MIN_COLS}) altına düştü.")
    return working, steps

def budget_optimize(results,budget):
    return coupon_level_optimize(results,budget)

def evaluate_coupon(results):
    from model.monte_carlo import simulate_coupon
    probs=[(r["P1"]/100,r["PX"]/100,r["P2"]/100) for r in results]
    sels=[r.get("oneri","1X2").split()[-1].strip() for r in results]
    res=simulate_coupon(probs,sels,n_sim=10000)
    res["p_12plus"]=round(sum(v for k,v in res["dist"].items() if k>=12),4)
    return res

def generate_scenario_coupons(results, n_coupons=3, max_cols_each=32,
                               pivot_no=None):
    """
    Akıllı döngüsel senaryo kuponları.

    - Çok favori KAOS (%55+ ve spread>20) → sabit (heavy)
    - Belirsiz KAOS → döngüsel 1/X/2 dağılım (flex)
    - X ağırlıklı: beraberlik olasılığı %30+ ise X öne alınır
    - Kapsama garantisi: her flex maçta 1/X/2 en az 1 kuponda görünür
    """
    kaos = [r for r in results if r.get("is_kaos") or r["mul"] == 3]
    if not kaos:
        cols = 1
        for r in results: cols *= r["mul"]
        return [{"id":"A","matches":[dict(r) for r in results],
                 "cols":cols,"cost":cols*UNIT,"scenario":{}}]

    def _priority_order(r):
        """Olasılık + X tercihi bazlı öncelik: [en iyi, ikinci, üçüncü]"""
        probs = [("1",r["P1"]),("X",r["PX"]),("2",r["P2"])]
        ranked = sorted(probs, key=lambda x:-x[1])
        # X %30+ ve ilk 2'deyse → öne al
        if r["PX"] >= 30 and ranked[0][0] != "X":
            non_x = [o for o in ranked if o[0] != "X"]
            return ["X", non_x[0][0], non_x[1][0]]
        return [o[0] for o in ranked]

    def _is_heavy(r):
        best   = max(r["P1"],r["PX"],r["P2"])
        second = sorted([r["P1"],r["PX"],r["P2"]],reverse=True)[1]
        # 65%: orta güçlü KAOS flex kalır → farklı senaryo üretilir
        return best >= 65 and (best - second) >= 25

    heavy = [r for r in kaos if _is_heavy(r)]
    flex  = [r for r in kaos if not _is_heavy(r)]
    heavy_defaults = {r["no"]: _priority_order(r)[0] for r in heavy}
    orders = {r["no"]: _priority_order(r) for r in flex}

    # Pivot modu
    if pivot_no:
        pivot = next((r for r in kaos if r["no"] == pivot_no), None)
        if pivot:
            scenarios = []
            for out in ["1","X","2"]:
                scen = dict(heavy_defaults)
                scen[pivot["no"]] = out
                for k in flex:
                    if k["no"] != pivot["no"]:
                        scen[k["no"]] = orders[k["no"]][0]
                scenarios.append(scen)
            if n_coupons >= 4:
                s4 = dict(heavy_defaults)
                for k in kaos:
                    order = _priority_order(k)
                    s4[k["no"]] = order[1] if len(order) > 1 else order[0]
                scenarios.append(s4)
            scenarios = scenarios[:n_coupons]

    else:
        # Döngüsel dağılım
        scenarios = []
        # flex yoksa heavy maçları da döngüsel işle
        flex_work  = flex if flex else heavy
        orders_all = {**orders, **{r["no"]: _priority_order(r) for r in heavy}}
        for i in range(n_coupons):
            scen = dict(heavy_defaults) if flex else {}
            for r in flex_work:
                order  = orders_all[r["no"]]
                offset = i % len(order)
                scen[r["no"]] = order[offset]
            scenarios.append(scen)

        # Kapsama: her maçta 1/X/2 en az 1 kuponda görünsün
        if n_coupons >= 3:
            for r in flex_work:
                order   = orders_all[r["no"]]
                covered = {scen[r["no"]] for scen in scenarios}
                missing = [o for o in order[:2] if o not in covered]
                if missing:
                    scenarios[-1][r["no"]] = missing[0]

    # Kuponları oluştur
    coupons = []
    for i, scen in enumerate(scenarios[:n_coupons]):
        label = chr(ord("A") + i)
        cm = []
        for r in results:
            if r["no"] in scen:
                cm.append({**dict(r),"mul":1,
                            "oneri":f"TEK   {scen[r['no']]}"})
            else:
                cm.append(dict(r))
        cols = 1
        for r in cm: cols *= r["mul"]
        if cols > max_cols_each:
            cl = sorted([r for r in cm if r["mul"]==2], key=_sel_score)
            for c in cl:
                if cols <= max_cols_each: break
                for r in cm:
                    if r["no"] == c["no"]:
                        r["mul"]=1; r["oneri"]="TEK   "+_best_outcome(r); break
                cols = 1
                for r in cm: cols *= r["mul"]
        coupons.append({"id":label,"matches":cm,
                        "cols":cols,"cost":cols*UNIT,
                        "scenario":scen,
                        "heavy":list(heavy_defaults.keys())})
    return coupons


def print_scenario_coupons(coupons,results):
    print(f"\n{'═'*70}")
    print(f"  SENARYO KUPONLARI ({len(coupons)} kupon)")
    print(f"{'═'*70}")
    kaos_nos=set()
    for c in coupons: kaos_nos.update(c.get("scenario",{}).keys())
    total=sum(c["cost"] for c in coupons)
    print(f"  Toplam: {total:,} TL  ({sum(c['cols'] for c in coupons)} kolon)")
    print(f"{'─'*70}")
    for coupon in coupons:
        scen=coupon.get("scenario",{})
        ss=" ".join(f"#{k}={v}" for k,v in sorted(scen.items()))
        print(f"\n  ┌── KUPON {coupon['id']}  ({coupon['cols']} kolon = {coupon['cost']:,} TL)  [🌀 {ss}]")
        for r in coupon["matches"]:
            lbl=r.get("oneri","")
            m="★" if "BANKO" in lbl else "◈" if "CIFT" in lbl else "○" if "KAOS" in lbl else "▸"
            kf=" 🌀" if r["no"] in kaos_nos else ""
            ctx=r.get("ctx","")
            print(f"  │ {r['no']:>2}. {r['mac']:<28} {m} {lbl:<12}{kf}{' '+ctx if ctx else ''}")
        print(f"  └─ {coupon['cols']} kolon = {coupon['cost']:,} TL")
    print(f"\n{'═'*70}")
    print(f"  Toplam: {len(coupons)} kupon = {total:,} TL")

def split_coupons(results):
    def _total(rl):
        t=1
        for r in rl: t*=r["mul"]
        return t
    def _split(rl,counter,depth=0):
        total=_total(rl)
        if total<=MAX_COLS_PER or depth>10:
            lb=chr(ord("A")+counter[0]%26); counter[0]+=1
            return [{"id":lb,"matches":[dict(r) for r in rl],"cols":total,"cost":total*UNIT}]
        multi=[r for r in rl if r["mul"]>1]
        if not multi:
            lb=chr(ord("A")+counter[0]%26); counter[0]+=1
            return [{"id":lb,"matches":[dict(r) for r in rl],"cols":total,"cost":total*UNIT}]
        target=max(multi,key=lambda r:r.get("entropy",0))
        outs=sorted([("1",target["P1"]),("X",target["PX"]),("2",target["P2"])],key=lambda x:-x[1])[:target["mul"]]
        ac=[]
        for out,_ in outs:
            new=[{**r,"mul":1,"oneri":f"BANKO {out}"} if r["no"]==target["no"] else dict(r) for r in rl]
            ac.extend(_split(new,counter,depth+1))
        return ac
    if _total(results)<=MAX_COLS_PER: return []
    return _split(results,[0])
