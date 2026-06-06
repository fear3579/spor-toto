# -*- coding: utf-8 -*-
"""
LPRM v2 — Lig Pozisyonu Tekrar Modeli
======================================
Takımların "lig hiyerarşisindeki tarihsel kimliğine" dayanan
4 katmanlı kompozit analiz modülü.

Temel felsefe:
  xG → "ne oldu" söyler
  LPRM → "ne olacak, çünkü daha önce defalarca böyle oldu" söyler

4 Katman AYRI değil, BİRLEŞİK filtre olarak çalışır:
  "Elit ev sahibi, Dip deplasmana karşı, dominant oranda,
   sezon sonunda, düşük bloklu rakiple" → ne olmuş?

Katman 1: Tier Matching      — EV+DEP tier kombinasyonu
Katman 2: Odds Pattern        — tier+oran bandı kronik davranış
Katman 3: Contextual Replay   — puan baskısı + sezon fazı
Katman 4: Tactical Ghosting   — rakip tarz profili (PPDA proxy)
"""

import pandas as pd
import numpy as np
from collections import defaultdict
import re

# ── Sabitler ────────────────────────────────────────────────
TIER_LABELS  = {0:"Elit", 1:"Üst Orta", 2:"Orta", 3:"Dip"}
TACTIC_LABELS = {0:"Yoğun Pres", 1:"Orta Pres", 2:"Pasif Blok"}

def _get_tier(pos: int, n: int = 18) -> int:
    p = pos / n
    if p <= 0.22: return 0   # Elit: ilk 4
    if p <= 0.44: return 1   # Üst Orta: 5-8
    if p <= 0.72: return 2   # Orta: 9-13
    return 3                 # Dip: 14-18

def _odds_band(odds) -> str:
    if odds is None: return "?"
    o = float(odds)
    if o < 1.35: return "dominant"    # ezici favori
    if o < 1.70: return "strong_fav"  # güçlü favori
    if o < 2.10: return "fav"         # favori
    if o < 2.60: return "slight_fav"  # hafif favori
    if o < 3.20: return "even"        # dengeli
    return "underdog"

def _tactic_profile(row) -> int:
    """
    Rakibin taktik tarzını şut verisinden tespit et (PPDA proxy).
    Yüksek şut baskısı → Yoğun Pres, Düşük → Pasif Blok
    """
    # Deplasman şut agresifliği (A = deplasman)
    ash  = float(row.get("AS", 5) or 5)
    asht = float(row.get("AST", 2) or 2)
    ac   = float(row.get("AC", 3) or 3)  # Corner = baskı göstergesi
    # Baskı skoru: şut sayısı + köşe sayısı normalize
    press_score = (ash + ac) / 15.0
    if press_score > 0.75: return 0   # Yoğun Pres
    if press_score > 0.45: return 1   # Orta Pres
    return 2                          # Pasif Blok (düşük blok)

def _norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', str(name).lower().strip())


class LPRMEngine:
    """
    LPRM analiz motoru.
    df_all: tüm liglerin CSV birleşimi.
    min_n : pattern için minimum maç sayısı.
    """

    def __init__(self, df_all: pd.DataFrame, min_n: int = 4):
        self.df    = df_all.copy()
        self.min_n = min_n
        self._prep()
        self._build_indices()

    # ── Ön işleme ───────────────────────────────────────────
    def _prep(self):
        df = self.df
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        for c in ["FTHG","FTAG","HS","AS","HST","AST","HC","AC","HY","AY"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        for c in ["B365H","B365D","B365A","MaxH","MaxD","MaxA",
                  "B365CH","B365CD","B365CA"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        df["TotalGoals"] = df["FTHG"] + df["FTAG"]
        # Deplasman taktik profili
        df["_dep_tactic"] = df.apply(_tactic_profile, axis=1)
        self.df = df

    def _build_indices(self):
        """Hızlı sorgu için takım bazlı index."""
        self._hidx = defaultdict(list)  # ev sahibi
        self._aidx = defaultdict(list)  # deplasman
        for _, r in self.df.iterrows():
            hn = _norm(str(r.get("HomeTeam","")))
            an = _norm(str(r.get("AwayTeam","")))
            if hn: self._hidx[hn].append(r)
            if an: self._aidx[an].append(r)

    def _home_rows(self, team: str) -> list:
        return self._hidx.get(_norm(team), [])

    def _away_rows(self, team: str) -> list:
        return self._aidx.get(_norm(team), [])

    # ────────────────────────────────────────────────────────
    # KATMAN 1: Tier Matching — EV+DEP kombinasyon sorgusu
    # ────────────────────────────────────────────────────────
    def tier_match(self, home: str, home_tier: int,
                   away_tier: int, n_teams: int = 18) -> dict:
        """
        "Tier X ev sahibi, Tier Y deplasmana karşı ne yapmış?"
        Sorgu: ev sahibinin ev maçlarında, dep oranından
        rakip tier'ı tahmin ederek filtreler.

        Örnek:
          Elit (0) vs Dip (3) → "kazanılması zorunlu" maç
          Orta (2) vs Elit (0) → zayıf ev, güçlü dep
        """
        rows = self._home_rows(home)
        if not rows:
            return {"n":0, "signal":"veri_yok", "home_tier":home_tier,
                    "away_tier":away_tier}

        # Rakip tier'ını oran ile tahmin et:
        # ev oranı < 1.50 → dep muhtemelen Dip/Orta
        # ev oranı > 2.50 → dep muhtemelen Elit
        def est_away_tier(row):
            o = float(row.get("B365H") or row.get("MaxH") or 2.0)
            if o < 1.50: return 3   # dep zayıf
            if o < 2.00: return 2
            if o < 2.60: return 1
            return 0

        similar = [r for r in rows if est_away_tier(r) == away_tier]
        n = len(similar)
        if n < self.min_n:
            return {"n":n, "signal":"yetersiz", "home_tier":home_tier,
                    "away_tier":away_tier}

        # Son 20 maç — üstel ağırlık
        recent = similar[-20:]
        nr = len(recent)
        w  = np.array([0.85**(nr-1-i) for i in range(nr)])
        w /= w.sum()

        ftrs = [r.get("FTR","?") for r in recent]
        wins  = sum(wi for wi,f in zip(w,ftrs) if f=="H")
        draws = sum(wi for wi,f in zip(w,ftrs) if f=="D")
        goals = [r.get("TotalGoals",2) for r in recent]
        avg_g = float(np.dot(goals, w))

        # Tier kombinasyon sinyali
        signal = "normal"; warning = ""
        if home_tier == 0 and away_tier == 3:
            # Elit vs Dip — "kazanılması zorunlu"
            if wins < 0.55:
                signal = "upset_prone"
                warning = (f"Elit-Dip maçında %{wins*100:.0f} kazanıyor "
                           f"— Zorunlu maç tuzağı riski!")
            elif draws > 0.30:
                signal = "draw_magnet"
                warning = f"Bu tip maçta %{draws*100:.0f} beraberlik"
        elif home_tier > away_tier:
            # Ev sahibi zayıf → sürpriz riski
            if wins < 0.35:
                signal = "underdog_ev"
                warning = f"Güçlü deplasmanı evde %{wins*100:.0f} yenebiliyor"

        return {
            "n": nr, "wins": round(wins,3), "draws": round(draws,3),
            "avg_goals": round(avg_g,2),
            "signal": signal, "warning": warning,
            "home_tier": TIER_LABELS[home_tier],
            "away_tier": TIER_LABELS[away_tier],
        }

    # ────────────────────────────────────────────────────────
    # KATMAN 2: Odds Pattern — Tier + Oran Bandı Kronik Davranış
    # ────────────────────────────────────────────────────────
    def odds_pattern(self, home: str, odds_h: float,
                     home_tier: int) -> dict:
        """
        "Bu takım, bu oran bandında, bu tier seviyesindeyken ne yapmış?"
        Tier + oran bandı kombinasyonu = kronik kimlik filtresi.

        Örnek sorgu:
          Galatasaray + dominant (1.20 altı) + Elit tier
          → "Son 15 maçın 8'inde beraberlik → KİLİTLENME"
        """
        band = _odds_band(odds_h)
        rows = self._home_rows(home)
        if not rows:
            return {"band":band, "n":0, "signal":"veri_yok"}

        # Aynı oran bandı + benzer tier (oran bazlı tahmin)
        def match(row):
            o = row.get("B365H") or row.get("MaxH")
            if o is None: return False
            return _odds_band(float(o)) == band

        band_rows = [r for r in rows if match(r)]
        n = len(band_rows)
        if n < self.min_n:
            return {"band":band, "n":n, "signal":"yetersiz"}

        recent = band_rows[-15:]
        nr = len(recent)
        w  = np.array([0.85**(nr-1-i) for i in range(nr)])
        w /= w.sum()

        ftrs = [r.get("FTR","?") for r in recent]
        wins  = sum(wi for wi,f in zip(w,ftrs) if f=="H")
        draws = sum(wi for wi,f in zip(w,ftrs) if f=="D")
        goals = [r.get("TotalGoals",2) for r in recent]
        avg_g = float(np.dot(goals, w))
        avg_scored = float(np.dot([r.get("FTHG",1) for r in recent], w))

        # Kronik davranış tespiti
        signal = "normal"; warning = ""; chronic = ""
        if draws > 0.40:
            signal   = "kilitleme"
            chronic  = "KİLİTLENME DESENİ"
            warning  = (f"'{band}' oranında {nr} maçın %{draws*100:.0f}'i "
                        f"beraberlik — {chronic}!")
        elif wins < 0.40 and band in ("dominant","strong_fav"):
            signal   = "favori_tuzagi"
            chronic  = "FAVORİ TUZAĞI"
            warning  = (f"Ezici favori pozisyonunda %{wins*100:.0f} kazanıyor "
                        f"— {chronic}!")
        elif avg_scored < 1.0:
            signal   = "gol_kuyugsu"
            warning  = f"Bu oranda ort. {avg_scored:.1f} gol buluyor — düşük gol riski"
        elif wins > 0.75:
            signal   = "kronik_kazanan"
            warning  = f"Bu oranda %{wins*100:.0f} kazanıyor — güvenilir"

        return {
            "band": band, "n_total": n, "n_recent": nr,
            "wins": round(wins,3), "draws": round(draws,3),
            "avg_goals": round(avg_g,2), "avg_scored": round(avg_scored,2),
            "signal": signal, "warning": warning,
        }

    # ────────────────────────────────────────────────────────
    # KATMAN 3: Contextual Replay — Puan Baskısı + Sezon Fazı
    # ────────────────────────────────────────────────────────
    def contextual_replay(self, home: str,
                          current_pts: int, expected_pts: float,
                          week: int, n_teams: int = 18) -> dict:
        """
        "Bu takım, geçmişte benzer puan baskısında ne yaptı?"

        xPTS proxy: gerçek xPTS yoksa form bazlı tahmin
        Balon tespiti: pts >> xPTS + sezon sonu = düşüş riski
        Baskı tespiti: pts << xPTS = toparlanma potansiyeli
        """
        pts_gap = current_pts - expected_pts
        season_phase = week / 38  # 0=başlangıç, 1=son

        # Ev sahibinin geçmiş "benzer baskı" maçlarını bul
        rows = self._home_rows(home)

        # Sezon fazı benzerliği (±15%)
        similar = []
        for r in rows:
            d = r.get("Date")
            if d is None: continue
            try:
                m = d.month
                # Sezon fazı proxy: Ağustos-Ekim=başlangıç, Kasım-Şubat=orta, Mart-Mayıs=son
                if m in [8,9,10]:    phase = 0.15
                elif m in [11,12,1]: phase = 0.50
                else:                phase = 0.85
                if abs(phase - season_phase) < 0.25:
                    similar.append(r)
            except (TypeError, KeyError, ValueError): pass

        n = len(similar)
        signal = "normal"; warning = ""

        # Senaryo bazlı sinyal
        if pts_gap > 8 and season_phase > 0.65:
            signal  = "dusus_yakin"
            warning = (f"Hak ettiğinden {pts_gap:.0f} puan fazla "
                       f"(Hafta {week}) — Tarihsel düşüş sinyali")
        elif pts_gap < -6 and season_phase > 0.50:
            signal  = "toparlanma"
            warning = (f"Hak ettiğinden {abs(pts_gap):.0f} puan az "
                       f"— Toparlanma potansiyeli")
        elif season_phase > 0.85 and current_pts < n_teams * 1.1:
            signal  = "hayatta_kalma"
            warning = f"Küme düşme baskısı — son {38-week} hafta kritik"
        elif season_phase > 0.75 and pts_gap > 5:
            signal  = "lider_baskisi"
            warning = f"Lider/zirve takımı sezon sonunda kilitlenme eğilimi"

        # Benzer fazda form
        if similar and n >= self.min_n:
            recent = similar[-10:]
            nr = len(recent)
            ftrs = [r.get("FTR","?") for r in recent]
            phase_win  = sum(1 for f in ftrs if f=="H") / nr
            phase_draw = sum(1 for f in ftrs if f=="D") / nr
        else:
            phase_win = phase_draw = None

        return {
            "pts_gap":      round(pts_gap, 1),
            "season_phase": round(season_phase, 2),
            "week":         week,
            "n_phase":      n,
            "phase_win":    round(phase_win,3) if phase_win is not None else None,
            "phase_draw":   round(phase_draw,3) if phase_draw is not None else None,
            "signal":       signal,
            "warning":      warning,
        }

    # ────────────────────────────────────────────────────────
    # KATMAN 4: Tactical Ghosting — Rakip Tarz Eşleşmesi
    # ────────────────────────────────────────────────────────
    def tactical_ghosting(self, home: str,
                          opp_tactic: int = 1) -> dict:
        """
        "Bu ev sahibi, benzer taktik yapıdaki rakiplere karşı ne yapmış?"

        PPDA proxy: deplasman şut+köşe yoğunluğu
          0 = Yoğun Pres (PPDA < 8)
          1 = Orta Pres
          2 = Pasif Blok / Düşük Blok (ODC yüksek)

        Sorgu örneği:
          "Galatasaray, düşük bloklu (Pasif) 5 rakibe karşı
           son 3 sezonda ne yaptı?"
        """
        rows = self._home_rows(home)
        if not rows:
            return {"n":0, "signal":"veri_yok", "tactic": TACTIC_LABELS[opp_tactic]}

        # Benzer taktik profilli rakip maçları
        similar = [r for r in rows
                   if r.get("_dep_tactic") == opp_tactic]
        n = len(similar)
        if n < self.min_n:
            return {"n":n, "signal":"yetersiz",
                    "tactic": TACTIC_LABELS[opp_tactic]}

        recent = similar[-12:]
        nr = len(recent)
        w  = np.array([0.85**(nr-1-i) for i in range(nr)])
        w /= w.sum()

        ftrs  = [r.get("FTR","?") for r in recent]
        wins  = sum(wi for wi,f in zip(w,ftrs) if f=="H")
        draws = sum(wi for wi,f in zip(w,ftrs) if f=="D")

        scored   = float(np.dot([r.get("FTHG",1) for r in recent], w))
        conceded = float(np.dot([r.get("FTAG",1) for r in recent], w))

        signal = "normal"; warning = ""

        if opp_tactic == 2:  # Pasif Blok / Düşük Blok
            if wins < 0.45:
                signal  = "dusuk_blok_tuzagi"
                warning = (f"Düşük bloklu rakiplere karşı %{wins*100:.0f} "
                           f"kazanıyor — Blok aşma sorunu!")
            elif scored < 1.2:
                signal  = "gol_bulamama"
                warning = f"Kapalı rakibe karşı ort. {scored:.1f} gol — düşük gol riski"
        elif opp_tactic == 0:  # Yoğun Pres
            if wins < 0.40:
                signal  = "pres_hassasiyeti"
                warning = f"Yoğun baskıya karşı %{wins*100:.0f} kazanıyor — Pres tuzağı"
            elif conceded > 1.5:
                signal  = "savunma_acigi"
                warning = f"Baskıcı rakiplere karşı {conceded:.1f} gol yiyor"

        return {
            "n": nr, "tactic": TACTIC_LABELS[opp_tactic],
            "wins": round(wins,3), "draws": round(draws,3),
            "avg_scored": round(scored,2), "avg_conceded": round(conceded,2),
            "signal": signal, "warning": warning,
        }

    # ────────────────────────────────────────────────────────
    # KOMPOZİT ANALİZ — 4 Katman Birleşik Sorgu
    # ────────────────────────────────────────────────────────
    def analyze(self, home: str, away: str,
                odds_h: float = None,
                home_pos: int = 9, away_pos: int = 9,
                n_teams: int = 18,
                home_pts: int = 35, home_xpts: float = 33.0,
                week: int = 25) -> dict:
        """
        4 katmanı BİRLEŞİK olarak çalıştır.

        Kompozit sorgu mantığı:
          Her katman bağımsız analiz üretir
          → Ağırlıklı LPRM skoru birleştirir
          → Lambda düzeltme faktörü hesaplanır
          → Uyarı mesajları üretilir

        Döner:
          lprm_score    : -1.0 (güçlü dep) → +1.0 (güçlü ev)
          main_signal   : açıklayıcı sinyal
          lambda_adj_h  : ev lambda çarpanı
          lambda_adj_a  : dep lambda çarpanı
          warnings      : uyarı metinleri listesi
          hud           : HUD ekranı için özet metin
          layers        : her katmanın detayı
        """
        home_tier = _get_tier(home_pos, n_teams)
        away_tier = _get_tier(away_pos, n_teams)

        # Deplasman taktik profilini bul (son 5 deplasman maçından)
        away_rows = self._away_rows(away)[-5:]
        if away_rows:
            tactics = [r.get("_dep_tactic", 1) for r in away_rows]
            opp_tactic = max(set(tactics), key=tactics.count)
        else:
            opp_tactic = 1  # varsayılan: orta pres

        # ── 4 Katman çalıştır ───────────────────────────────
        L1 = self.tier_match(home, home_tier, away_tier, n_teams)
        L2 = self.odds_pattern(home, odds_h, home_tier)
        L3 = self.contextual_replay(home, home_pts, home_xpts, week, n_teams)
        L4 = self.tactical_ghosting(home, opp_tactic)

        # ── Ağırlıklı skor hesabı ───────────────────────────
        # Ağırlıklar: Tier+Odds kronik kimlik en önemli
        W = {"L1": 0.25, "L2": 0.35, "L3": 0.20, "L4": 0.20}
        score = 0.0

        # L1: Tier kombinasyon skoru
        if L1.get("n",0) >= self.min_n:
            s = (L1["wins"] - 0.45) * 2  # -1 to +1
            if L1["signal"] == "upset_prone":    s -= 0.30
            elif L1["signal"] == "draw_magnet":  s -= 0.15
            elif L1["signal"] == "underdog_ev":  s -= 0.25
            score += s * W["L1"]

        # L2: Odds pattern skoru — KRONİK KİMLİK
        if L2.get("n_recent",0) >= self.min_n:
            s = (L2["wins"] - 0.45) * 2
            if L2["signal"] == "kilitleme":      s -= 0.40
            elif L2["signal"] == "favori_tuzagi":s -= 0.45
            elif L2["signal"] == "gol_kuyugsu":  s -= 0.10
            elif L2["signal"] == "kronik_kazanan":s+= 0.20
            # Draw eğilimi → px artar
            if L2["draws"] > 0.35:
                s -= (L2["draws"] - 0.35) * 0.60
            score += s * W["L2"]

        # L3: Contextual replay skoru
        if L3["signal"] == "dusus_yakin":    score -= 0.25 * W["L3"]
        elif L3["signal"] == "toparlanma":   score += 0.15 * W["L3"]
        elif L3["signal"] == "hayatta_kalma":score -= 0.10 * W["L3"]
        elif L3["signal"] == "lider_baskisi":score -= 0.08 * W["L3"]
        # Sezon fazı form
        if L3.get("phase_win") is not None:
            s = (L3["phase_win"] - 0.45) * 2
            score += s * W["L3"] * 0.5

        # L4: Tactical ghosting skoru
        if L4.get("n",0) >= self.min_n:
            s = (L4["wins"] - 0.45) * 2
            if L4["signal"] == "dusuk_blok_tuzagi": s -= 0.35
            elif L4["signal"] == "pres_hassasiyeti":  s -= 0.25
            elif L4["signal"] == "gol_bulamama":      s -= 0.15
            score += s * W["L4"]

        score = max(-1.0, min(1.0, score))

        # ── Lambda düzeltmesi ────────────────────────────────
        # Küçük, kademeli — sistemin temel hesabını bozmaz
        lambda_adj_h = round(1.0 + score * 0.08, 4)
        lambda_adj_a = round(1.0 - score * 0.06, 4)

        # ── Sinyal ──────────────────────────────────────────
        if score > 0.40:    main_signal = "güçlü_ev"
        elif score > 0.15:  main_signal = "hafif_ev"
        elif score > -0.15: main_signal = "nötr"
        elif score > -0.40: main_signal = "hafif_dep"
        else:               main_signal = "güçlü_dep"

        # ── Uyarılar ────────────────────────────────────────
        warnings = []
        for layer in [L1, L2, L3, L4]:
            w = layer.get("warning","")
            if w: warnings.append(w)

        # ── HUD Metni ───────────────────────────────────────
        hud_lines = [
            f"LPRM | {TIER_LABELS[home_tier]} ev vs {TIER_LABELS[away_tier]} dep",
            f"Oran Bandı: {_odds_band(odds_h)} | Sezon: H{week} (%{L3['season_phase']*100:.0f})",
            f"Rakip Tarz: {TACTIC_LABELS[opp_tactic]}",
        ]
        if L2.get("n_recent",0) >= self.min_n:
            hud_lines.append(
                f"Kronik: {L2['n_recent']} maç → W%{L2['wins']*100:.0f} "
                f"D%{L2['draws']*100:.0f} — {L2.get('signal','?')}"
            )
        for w in warnings[:2]:
            hud_lines.append(f"⚠ {w}")

        # ── Hafıza kronik sinyal (DNA katmanı) ─────────────
        # Hafızada birikmis profil varsa lambda_adj'a ekle
        mem_signal = {"lambda_mod": 1.0, "warning": "", "confidence": 0.0}
        try:
            from memory.st_memory import get_memory as _gm
            _mem = _gm()
            # Oran bandı belirle
            # _odds_band aynı dosyada tanımlı — circular import kaldırıldı
            _band = _odds_band(odds_h) if odds_h else "even"
            mem_signal = _mem.get_chronic_signal(
                team=_norm(home), band=_band, tactic=opp_tactic)
            # Lambda'ya uygula (confidence ölçekli)
            _mod = mem_signal["lambda_mod"]
            _cf  = mem_signal["confidence"]
            # Güven ölçekli etki: tam güven → tam mod, düşük güven → hafif
            _eff = 1.0 + (_mod - 1.0) * _cf
            lambda_adj_h = round(lambda_adj_h * _eff, 4)
            lambda_adj_a = round(lambda_adj_a * (2.0 - _eff), 4)
            if mem_signal.get("warning"):
                warnings.append(mem_signal["warning"])
        except Exception:
            pass

        return {
            "lprm_score":   round(score, 3),
            "main_signal":  main_signal,
            "lambda_adj_h": lambda_adj_h,
            "lambda_adj_a": lambda_adj_a,
            "warnings":     warnings,
            "hud":          "\n".join(hud_lines),
            "mem_signal":   mem_signal,
            "layers": {
                "tier":     L1,
                "odds":     L2,
                "context":  L3,
                "tactical": L4,
            },
        }
