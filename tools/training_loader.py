# -*- coding: utf-8 -*-
"""
tools/training_loader.py — AUGUR ENGINE ML Eğitim Veri Yükleyicisi (v2)
Güçlendirilmiş: 30 gerçek özellik, rolling form, line movement
"""
from __future__ import annotations
import os, logging
from typing import Tuple, List, Optional
logger = logging.getLogger(__name__)

_HERE        = os.path.dirname(os.path.abspath(__file__))
_ROOT        = os.path.dirname(_HERE)
TRAINING_DIR = os.path.join(_ROOT, "training")
FD_CACHE_DIR = os.path.join(_ROOT, "fd_cache")

LEAGUES = ["T1","E0","SP1","I1","D1","F1","N1","B1","P1","G1","SC0"]
# SEASON_WEIGHTS: Eğitimde ağırlıklar
# 2627 başladığında otomatik güncellenir (config.CURRENT_SEASON bazlı)
# Ağustos öncesi: 2526 güncel, 2425 ve 2324 geçmiş
# Ağustos sonrası: 2627 güncel, 2526 ve 2425 geçmiş
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from config import CURRENT_SEASON as _CUR
    _y2 = int(_CUR[:2])
    _s1 = _CUR                                        # Güncel sezon × 1.00
    _s2 = f"{str(_y2-1).zfill(2)}{str(_y2).zfill(2)}"  # S-1 × 0.70
    _s3 = f"{str(_y2-2).zfill(2)}{str(_y2-1).zfill(2)}" # S-2 × 0.40
    SEASON_WEIGHTS = {_s1: 1.00, _s2: 0.70, _s3: 0.40}
except Exception:
    SEASON_WEIGHTS = {"2526": 1.00, "2425": 0.70, "2324": 0.40}
SEASON_START   = {"2526":"2025-08-01","2425":"2024-08-01","2324":"2023-08-01"}
FTR_MAP = {"H":0,"D":1,"A":2}
LEAGUE_DRAW_RATES = {
    "T1":0.267,"E0":0.241,"SP1":0.263,"I1":0.284,"D1":0.236,
    "F1":0.272,"N1":0.268,"B1":0.263,"P1":0.271,"G1":0.283,"SC0":0.252,
}
# ARAŞTIRMA GÜNCELLEMESİ (Haziran 2026): 28 → 15 özellik
# Korelasyon analizi: p1_b365 ≈ p1_pin ≈ p1_avg (%95+) → sadece Pinnacle/B365
# under25 = 1 - over25 → tek yeterli; form_diff form satırlarının özeti
# Kaynak: Groll et al. (2018); Large et al. (2019) küçük-veri feature önerisi
FEATURE_NAMES = [
    # Oran sinyali — en güçlü prediktif grup (Štrumbelj 2014)
    "p1_pin","px_pin","p2_pin",    # Pinnacle/B365 Shin-kalibre
    "odds_spread",                  # Favori belirginliği
    # Poisson lambda sinyali
    "lam_h","lam_a","lam_diff",
    # O/U (under25 = 1-over25, bilgi yok)
    "over25_prob",
    # Form — özet diff yeterli (gf/ga ayrıştırması noise)
    "form_diff",
    # Line movement — kapanış/açılış hareketi (CLV proxy)
    "lm_h","lm_d",
    # Bağlam
    "season_week","is_home_fav","draw_rate_lig",
    # Pozisyon/ELO proxy
    "pos_diff_norm",
]
N_FEATURES = len(FEATURE_NAMES)  # 15


class TrainingLoader:
    def __init__(self, verbose=True):
        self.verbose = verbose
        self.stats: dict = {}

    def load(self) -> Tuple[List,List,List]:
        try:
            import pandas as pd
        except ImportError:
            logger.error("pandas yok")
            return [],[],[]

        X,y,w = [],[],[]

        for season, sw in sorted(SEASON_WEIGHTS.items(), reverse=True):
            sdir = os.path.join(TRAINING_DIR, season)
            if not os.path.exists(sdir):
                if self.verbose: print(f"  ⚠ training/{season}/ yok")
                continue
            ss = {}
            for league in LEAGUES:
                csv = os.path.join(sdir, f"{league}.csv")
                if not os.path.exists(csv):
                    if not self._copy_from_cache(league, season, csv): continue
                try:
                    df = pd.read_csv(csv, low_memory=False)
                except Exception as e:
                    logger.warning("%s/%s.csv: %s", season, league, e); continue
                if "FTR" not in df.columns or "B365H" not in df.columns: continue
                df = df[df["FTR"].isin(["H","D","A"])].dropna(
                    subset=["B365H","B365D","B365A","FTR"]).reset_index(drop=True)
                df = self._add_rolling_form(df)
                df = self._add_standings(df)
                ss_start = SEASON_START.get(season,"2024-08-01")
                # ELO: history yuklendi mi? (singleton ile optimize)
                if not hasattr(self, "_elo_hist"):
                    self._elo_hist = self._load_elo_history()
                df = self._add_elo_col(df, self._elo_hist, ss_start)
                n0 = len(X)
                for _,row in df.iterrows():
                    feat = self._row_to_features(row, league, ss_start)
                    if feat is None: continue
                    X.append(feat); y.append(FTR_MAP[row["FTR"]]); w.append(sw)
                n_added = len(X)-n0; ss[league] = n_added
                if self.verbose and n_added:
                    print(f"  ✓ {season}/{league}.csv → {n_added} maç (×{sw})")
            self.stats[season] = ss

        if self.verbose: self._print_summary(X,y,w)
        return X,y,w

    @staticmethod
    def _load_elo_history():
        """elo_history.json yukle — {tarih: {takim: elo}} """
        import json
        # Modul seviyesindeki sabitleri kullan (__file__ statik metodda calismaz)
        # Agresif yol arama — TRAINING_DIR bazlı
        _td   = TRAINING_DIR  # training/ klasoru
        _tpar = os.path.dirname(_td)  # SPOR TOTO/
        candidates = [
            os.path.join(_HERE,  "elo_history.json"),
            os.path.join(_ROOT,  "tools", "elo_history.json"),
            os.path.join(_tpar,  "tools", "elo_history.json"),
            os.path.join(_tpar,  "elo_history.json"),
            os.path.join(os.getcwd(), "tools", "elo_history.json"),
            os.path.join(os.getcwd(), "elo_history.json"),
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    data = json.load(open(path, encoding="utf-8"))
                    if data:
                        import sys
                        print(f"  [ELO] {len(data)} tarih yuklendi: {path}", file=sys.stderr)
                        return data
                except Exception:
                    continue
        import sys
        print(f"  [ELO] elo_history.json bulunamadi. Denenen: {candidates}", file=sys.stderr)
        return {}

    @staticmethod
    def _get_elo_at(team_name: str, date_str: str, history: dict) -> float:
        """Belirli tarihte takim ELO'sunu bul — yakin tarihe geri don."""
        if not history or not date_str:
            return 1500.0
        # Onceki en yakin tarihi bul
        past = [d for d in history if d <= date_str]
        if not past:
            return 1500.0
        nearest = max(past)
        day_data = history[nearest]
        # Direkt eslesme
        if team_name in day_data:
            return float(day_data[team_name])
        # Fuzzy
        tu = team_name.upper()
        for k, v in day_data.items():
            if tu in k.upper() or k.upper() in tu:
                return float(v)
        return 1500.0

    @staticmethod
    def _add_elo_col(df, elo_history: dict, season_start: str = "2024-08-01"):
        """Her satira ev/dep ELO farki ekle."""
        df = df.copy()
        df["_elo_diff_norm"] = 0.0
        if not elo_history:
            return df
        import datetime
        for idx in df.index:
            ht = str(df.at[idx, "HomeTeam"])
            at = str(df.at[idx, "AwayTeam"])
            ds = str(df.at[idx, "Date"])
            # DD/MM/YYYY -> YYYY-MM-DD
            date_iso = ""
            for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"]:
                try:
                    date_iso = datetime.datetime.strptime(ds, fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            if not date_iso:
                continue
            elo_h = TrainingLoader._get_elo_at(ht, date_iso, elo_history)
            elo_a = TrainingLoader._get_elo_at(at, date_iso, elo_history)
            # normalize: /400 (ELO fark birimi)
            df.at[idx, "_elo_diff_norm"] = round((elo_h - elo_a) / 400.0, 4)
        return df



    @staticmethod
    def fetch_team_stats_api(home: str, away: str,
                             league_code: str,
                             season_code: str) -> dict:
        """
        /teams/statistics → home_win_rate, btts_rate, clean_sheet_rate çek.
        Cache TTL=24h, hata durumunda boş dict döner.
        """
        try:
            from data.api_football import APIFootball, LEAGUE_ID_MAP, SEASON_MAP
            api = APIFootball()
            if not api.key: return {}
            lid = LEAGUE_ID_MAP.get(league_code)
            sea = SEASON_MAP.get(season_code, 2025)
            if not lid: return {}

            result = {}
            for side, team in [("h", home), ("a", away)]:
                tid = api.get_team_id(team, lid, sea)
                if not tid: continue
                stats = api.team_statistics(tid, lid, sea)
                if stats:
                    result[side] = stats
            return result
        except Exception:
            return {}

    @staticmethod
    def fetch_h2h_api(home: str, away: str,
                      league_code: str, season_code: str) -> dict:
        """
        /fixtures/headtohead → H2H istatistikleri çek.
        Son 10 maç. Cache TTL=24h.
        """
        try:
            from data.api_football import APIFootball, LEAGUE_ID_MAP, SEASON_MAP
            api = APIFootball()
            if not api.key: return {}
            lid = LEAGUE_ID_MAP.get(league_code)
            sea = SEASON_MAP.get(season_code, 2025)
            if not lid: return {}

            h_id = api.get_team_id(home, lid, sea)
            a_id = api.get_team_id(away, lid, sea)
            if not h_id or not a_id: return {}

            matches = api.head_to_head(h_id, a_id, last_n=10)
            if not matches: return {}

            n = len(matches)
            h_wins = sum(1 for m in matches
                         if m["home"] == home and m["result"] == "H"
                         or m["away"] == home and m["result"] == "A")
            draws  = sum(1 for m in matches if m["result"] == "D")
            return {
                "n":                n,
                "h2h_home_win_rate": round(h_wins / n, 3),
                "h2h_draw_rate":    round(draws  / n, 3),
                "h2h_goals_avg":    round(
                    sum(m["home_score"] + m["away_score"] for m in matches) / n, 2
                ),
            }
        except Exception:
            return {}

    @staticmethod
    def fetch_fixture_stats_api(fixture_id: int) -> dict:
        """
        /fixtures/statistics → xG, şut, sahip verisi çek.
        Training verisi için geçmiş maçlarda çağrılır.
        """
        try:
            from data.api_football import APIFootball
            api = APIFootball()
            if not api.key or not fixture_id: return {}
            return api.fixture_statistics(fixture_id)
        except Exception:
            return {}

    @staticmethod
    def get_api_standings(league_code: str, season_code: str) -> dict:
        """
        API-Football'dan güncel lig tablosunu çek.
        Inference sırasında pos_diff_norm'u daha doğru yapar.

        Returns:
            {"Galatasaray": {"rank":1,"form":"WWWDW","pts":86}, ...}
        """
        try:
            from data.api_football import APIFootball, LEAGUE_ID_MAP, SEASON_MAP
            api = APIFootball()
            if not api.key:
                return {}
            league_id = LEAGUE_ID_MAP.get(league_code)
            season    = SEASON_MAP.get(season_code, 2025)
            if not league_id:
                return {}
            table = api.standings(league_id, season)
            return {entry["team"]: entry for entry in table}
        except Exception:
            return {}

    @staticmethod
    def calc_pos_diff_from_standings(home: str, away: str,
                                     standings: dict, n_teams: int = 20) -> float:
        """
        API standings'ten pos_diff_norm hesapla.
        Inference sırasında ML feature olarak kullanılır.
        """
        h_entry = standings.get(home, {})
        a_entry = standings.get(away, {})
        h_rank  = h_entry.get("rank", n_teams // 2)
        a_rank  = a_entry.get("rank", n_teams // 2)
        return round((a_rank - h_rank) / max(1, n_teams), 3)

    @staticmethod
    def _add_standings(df):
        """Her maç için o ana kadarki kümülatif lig pozisyonunu hesapla."""
        df = df.copy()
        df["_home_pos"] = 9
        df["_away_pos"] = 9
        df["_n_teams"]  = 18
        pts = {}
        for idx in df.index:
            ht = str(df.at[idx, "HomeTeam"])
            at = str(df.at[idx, "AwayTeam"])
            # Mevcut sıralamayı kaydet
            if pts:
                ranked = sorted(pts.items(), key=lambda x:-x[1])
                rank_map = {t:r+1 for r,(t,_) in enumerate(ranked)}
                df.at[idx,"_home_pos"] = rank_map.get(ht, len(ranked)//2+1)
                df.at[idx,"_away_pos"] = rank_map.get(at, len(ranked)//2+1)
                df.at[idx,"_n_teams"]  = max(18, len(ranked))
            # Maç sonrası puan güncelle
            ftr = str(df.at[idx,"FTR"])
            pts.setdefault(ht,0); pts.setdefault(at,0)
            if ftr=="H":   pts[ht]+=3
            elif ftr=="A": pts[at]+=3
            else:          pts[ht]+=1; pts[at]+=1
        return df

    @staticmethod
    def _add_rolling_form(df):
        df = df.copy()
        df["_form_h_gf"]=1.5; df["_form_h_ga"]=1.5
        df["_form_a_gf"]=1.5; df["_form_a_ga"]=1.5
        hist: dict = {}
        for idx in df.index:
            ht = str(df.at[idx,"HomeTeam"]); at = str(df.at[idx,"AwayTeam"])
            for team, col_gf, col_ga in [(ht,"_form_h_gf","_form_h_ga"),
                                          (at,"_form_a_gf","_form_a_ga")]:
                h = hist.get(team,[])[-5:]
                if h:
                    df.at[idx,col_gf]=sum(g for g,_ in h)/len(h)
                    df.at[idx,col_ga]=sum(g for _,g in h)/len(h)
            try:
                fthg=int(df.at[idx,"FTHG"]); ftag=int(df.at[idx,"FTAG"])
                hist.setdefault(ht,[]).append((fthg,ftag))
                hist.setdefault(at,[]).append((ftag,fthg))
            except Exception: pass
        return df

    @staticmethod
    def _row_to_features(row, league, season_start="2024-08-01"):
        try:
            import math
            o1=float(row.get("B365H",0) or 0)
            ox=float(row.get("B365D",0) or 0)
            o2=float(row.get("B365A",0) or 0)
            if o1<=0 or ox<=0 or o2<=0: return None
            raw=1/o1+1/ox+1/o2
            p1_b=round((1/o1)/raw,4); px_b=round((1/ox)/raw,4); p2_b=round((1/o2)/raw,4)
            odds_spread=round(max(o1,ox,o2)-min(o1,ox,o2),2)
            # Pinnacle
            ps_h=float(row.get("PSH",0) or 0)
            ps_d=float(row.get("PSD",0) or 0)
            ps_a=float(row.get("PSA",0) or 0)
            if ps_h>0 and ps_d>0 and ps_a>0:
                rp=1/ps_h+1/ps_d+1/ps_a
                p1_pin=round((1/ps_h)/rp,4); px_pin=round((1/ps_d)/rp,4); p2_pin=round((1/ps_a)/rp,4)
            else: p1_pin,px_pin,p2_pin=p1_b,px_b,p2_b
            # Avg
            ah=float(row.get("AvgH",0) or 0)
            ad=float(row.get("AvgD",0) or 0)
            aa=float(row.get("AvgA",0) or 0)
            if ah>0 and ad>0 and aa>0:
                ra=1/ah+1/ad+1/aa
                p1_avg=round((1/ah)/ra,4); px_avg=round((1/ad)/ra,4); p2_avg=round((1/aa)/ra,4)
            else: p1_avg,px_avg,p2_avg=p1_b,px_b,p2_b
            # Line movement
            c1=float(row.get("B365CH",0) or 0)
            cd=float(row.get("B365CD",0) or 0)
            ca=float(row.get("B365CA",0) or 0)
            lm_h=round(c1-o1,3) if c1>0 else 0.0
            lm_d=round(cd-ox,3) if cd>0 else 0.0
            lm_a=round(ca-o2,3) if ca>0 else 0.0
            # Lambda
            lam_h=max(0.2,round(-math.log(max(0.01,1-p1_b))*1.5,3))
            lam_a=max(0.2,round(-math.log(max(0.01,1-p2_b))*1.5,3))
            lam_diff=round(lam_h-lam_a,3)
            # O/U
            ov=float(row.get("B365>2.5",0) or 0)
            un=float(row.get("B365<2.5",0) or 0)
            if ov>0 and un>0:
                rou=1/ov+1/un; over25=round((1/ov)/rou,4); under25=round((1/un)/rou,4)
            else: over25,under25=0.52,0.48
            # Form
            fhgf=round(float(row.get("_form_h_gf",1.5) or 1.5),3)
            fhga=round(float(row.get("_form_h_ga",1.5) or 1.5),3)
            fagf=round(float(row.get("_form_a_gf",1.5) or 1.5),3)
            faga=round(float(row.get("_form_a_ga",1.5) or 1.5),3)
            fdiff=round((fhgf-fhga)-(fagf-faga),3)
            # Sezon haftası
            sw=20
            try:
                from datetime import datetime
                ds=str(row.get("Date",""))
                for fmt in ["%d/%m/%Y","%Y-%m-%d","%d/%m/%y"]:
                    try:
                        md=datetime.strptime(ds,fmt)
                        sd=datetime.strptime(season_start,"%Y-%m-%d")
                        sw=max(1,min(52,(md-sd).days//7+1)); break
                    except ValueError: continue
            except Exception: pass
            is_hf=1 if o1<o2 else 0
            dr=LEAGUE_DRAW_RATES.get(league,0.265)

            # ARAŞTIRMA GÜNCELLEMESİ (Haziran 2026): 28 → 15 özellik
            # FEATURE_NAMES sırasıyla: p1_pin, px_pin, p2_pin, odds_spread,
            # lam_h, lam_a, lam_diff, over25, form_diff,
            # lm_h, lm_d, season_week, is_home_fav, draw_rate_lig, pos_diff_norm
            pos_diff_norm = round(
                (float(row.get("_away_pos", 9)) - float(row.get("_home_pos", 9)))
                / max(1, float(row.get("_n_teams", 18))), 3)

            return [
                p1_pin, px_pin, p2_pin,   # Oran (Shin-kalibre)
                odds_spread,               # Spread
                lam_h, lam_a, lam_diff,   # Lambda
                over25,                    # O/U
                fdiff,                     # Form diff
                lm_h, lm_d,               # Line movement
                sw, is_hf, dr,            # Bağlam
                pos_diff_norm,             # Pozisyon/ELO proxy
            ]
        except Exception as e:
            logger.debug("Feature err: %s",e); return None

    @staticmethod
    def _copy_from_cache(league, season, dest):
        import shutil
        src=os.path.join(FD_CACHE_DIR,f"{league}_{season}.csv")
        if not os.path.exists(src): return False
        try:
            os.makedirs(os.path.dirname(dest),exist_ok=True)
            shutil.copy2(src,dest); return True
        except Exception: return False

    def _print_summary(self, X, y, w):
        if not X: print("  ⚠ Veri yok!"); return
        n=len(X); h=y.count(0); d=y.count(1); a=y.count(2)
        print(f"\n  ── Eğitim Özeti ────────────────────────────")
        print(f"  Toplam: {n:,} maç | {len(X[0])} özellik")
        print(f"  1=%{h/n*100:.1f}  X=%{d/n*100:.1f}  2=%{a/n*100:.1f}")
        for s in sorted(self.stats.keys(),reverse=True):
            t=sum(self.stats[s].values()); sw=SEASON_WEIGHTS.get(s,0)
            print(f"  {s}: {t:,} maç × {sw}")
        print(f"  ────────────────────────────────────────────")


def load_training_data(verbose=True): return TrainingLoader(verbose).load()
