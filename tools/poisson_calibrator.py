# -*- coding: utf-8 -*-
"""
tools/poisson_calibrator.py — CSV Bazlı Poisson Kalibratör
===========================================================

training/ klasöründeki CSV'lerden her takım için
saldırı/savunma güç katsayıları hesaplar.

Yöntem: Dixon-Coles (1997) takım güç modeli
  λH = attack_h(ev) × defense_a(dep) × lig_avg_ev
  λA = attack_a(dep) × defense_h(ev) × lig_avg_dep

Çıktı: tools/team_strengths.json
  {
    "T1": {
      "lig_avg_h": 1.413,
      "lig_avg_a": 1.201,
      "teams": {
        "Galatasaray": {
          "attack_h":  1.857,   # evde gol gücü
          "defense_h": 0.624,   # evde savunma
          "attack_a":  1.612,   # deplasanda gol
          "defense_a": 0.663,   # deplasanda savunma
          "n_ev": 16,
          "n_dep": 16,
          "confidence": 0.84    # veri kalitesi
        }
      }
    }
  }

Kullanım:
  from tools.poisson_calibrator import get_lambda
  lam_h, lam_a = get_lambda("T1", "Galatasaray", "Fenerbahce")
  # → (2.09, 1.33)

  from tools.poisson_calibrator import PoissonCalibrator
  cal = PoissonCalibrator()
  cal.fit_all()     # tüm ligler
  cal.save()        # team_strengths.json
"""

from __future__ import annotations

import os
import json
import logging
from typing import Optional, Tuple, Dict

logger = logging.getLogger(__name__)

# ── Yollar ────────────────────────────────────────────────────────────────────
_HERE          = os.path.dirname(os.path.abspath(__file__))
_ROOT          = os.path.dirname(_HERE)
TRAINING_DIR   = os.path.join(_ROOT, "training")
OUTPUT_FILE    = os.path.join(_HERE, "team_strengths.json")

# ── Ligler ────────────────────────────────────────────────────────────────────
LEAGUES = ["T1","E0","SP1","I1","D1","F1","N1","B1","P1","G1","SC0"]

# ── Sezon ağırlıkları ─────────────────────────────────────────────────────────
SEASON_WEIGHTS = {"2526": 1.00, "2425": 0.70, "2324": 0.40}

# ── Minimum veri eşikleri ─────────────────────────────────────────────────────
MIN_MATCHES = 5   # Güvenilir güç için minimum maç


class PoissonCalibrator:
    """
    CSV verilerinden takım saldırı/savunma güçlerini hesaplar.
    Ağırlıklı sezon ortalaması kullanır.
    """

    def __init__(self, verbose: bool = True):
        self.verbose  = verbose
        self.data: Dict = {}   # {lig: {lig_avg_h, lig_avg_a, teams: {team: {...}}}}

    # ── Tek lig fit ───────────────────────────────────────────────────────────
    def fit_league(self, league: str) -> Optional[dict]:
        """
        Bir lig için tüm sezonları ağırlıklı olarak birleştirip
        takım güçlerini hesapla.
        """
        try:
            import pandas as pd
            import numpy as np
        except ImportError:
            logger.error("pandas yok")
            return None

        # Tüm sezonları ağırlıklı topla
        rows_h, rows_a = [], []   # (fthg, ftag, weight)
        total_rows = 0

        for season, sw in sorted(SEASON_WEIGHTS.items(), reverse=True):
            csv_path = os.path.join(TRAINING_DIR, season, f"{league}.csv")
            if not os.path.exists(csv_path):
                continue
            try:
                df = pd.read_csv(csv_path, low_memory=False)
            except Exception:
                continue

            if not all(c in df.columns for c in
                       ["HomeTeam","AwayTeam","FTHG","FTAG","FTR"]):
                continue

            df = df[df["FTR"].isin(["H","D","A"])].dropna(
                subset=["FTHG","FTAG","HomeTeam","AwayTeam"]).copy()
            df["FTHG"] = pd.to_numeric(df["FTHG"], errors="coerce")
            df["FTAG"] = pd.to_numeric(df["FTAG"], errors="coerce")
            df = df.dropna(subset=["FTHG","FTAG"])

            for _, row in df.iterrows():
                rows_h.append((str(row["HomeTeam"]), str(row["AwayTeam"]),
                                float(row["FTHG"]), float(row["FTAG"]), sw))
            total_rows += len(df)

        if total_rows < 30:
            if self.verbose:
                print(f"  ✗ {league}: yetersiz veri ({total_rows})")
            return None

        # ── Ağırlıklı lig ortalamaları ─────────────────────────────────────
        sum_h  = sum(fthg * w for _, _, fthg, _, w in rows_h)
        sum_a  = sum(ftag * w for _, _, _, ftag, w in rows_h)
        sum_w  = sum(w for *_, w in rows_h)
        lig_avg_h = sum_h / sum_w
        lig_avg_a = sum_a / sum_w

        # ── Takım güçleri ──────────────────────────────────────────────────
        # Her takım için: ev ve deplasman verilerini ayrı topla
        team_ev : Dict  = {}   # team → {fthg: [], ftag: [], weights: []}
        team_dep: Dict  = {}

        for ht, at, fthg, ftag, w in rows_h:
            if ht not in team_ev:
                team_ev[ht]  = {"gf":[], "ga":[], "w":[]}
            if at not in team_dep:
                team_dep[at] = {"gf":[], "ga":[], "w":[]}

            team_ev[ht]["gf"].append(fthg); team_ev[ht]["ga"].append(ftag)
            team_ev[ht]["w"].append(w)
            team_dep[at]["gf"].append(ftag); team_dep[at]["ga"].append(fthg)
            team_dep[at]["w"].append(w)

        teams = sorted(set(team_ev) | set(team_dep))
        strengths = {}

        for team in teams:
            ev  = team_ev.get(team)
            dep = team_dep.get(team)

            if not ev or not dep:
                continue
            if len(ev["gf"]) < MIN_MATCHES or len(dep["gf"]) < MIN_MATCHES:
                continue

            # Ağırlıklı ortalama
            def wavg(vals, ws):
                return sum(v*w for v,w in zip(vals,ws)) / sum(ws)

            ev_gf  = wavg(ev["gf"],  ev["w"])
            ev_ga  = wavg(ev["ga"],  ev["w"])
            dep_gf = wavg(dep["gf"], dep["w"])
            dep_ga = wavg(dep["ga"], dep["w"])

            # Lig ortalamasına normalize et
            attack_h  = ev_gf  / lig_avg_h  if lig_avg_h  > 0 else 1.0
            defense_h = ev_ga  / lig_avg_a  if lig_avg_a  > 0 else 1.0
            attack_a  = dep_gf / lig_avg_a  if lig_avg_a  > 0 else 1.0
            defense_a = dep_ga / lig_avg_h  if lig_avg_h  > 0 else 1.0

            # Veri kalitesi skoru
            n_total = len(ev["gf"]) + len(dep["gf"])
            confidence = min(1.0, n_total / 60)  # 60 maç = tam güven

            strengths[team] = {
                "attack_h":  round(attack_h,  4),
                "defense_h": round(defense_h, 4),
                "attack_a":  round(attack_a,  4),
                "defense_a": round(defense_a, 4),
                "n_ev":      len(ev["gf"]),
                "n_dep":     len(dep["gf"]),
                "confidence":round(confidence,3),
            }

        result = {
            "lig_avg_h": round(lig_avg_h, 4),
            "lig_avg_a": round(lig_avg_a, 4),
            "n_matches":  total_rows,
            "teams":      strengths,
        }

        if self.verbose:
            print(f"  ✓ {league}: {len(strengths)} takım, "
                  f"{total_rows} maç | "
                  f"λH_avg={lig_avg_h:.2f} λA_avg={lig_avg_a:.2f}")

        return result

    # ── Tüm ligler ───────────────────────────────────────────────────────────
    def fit_all(self) -> dict:
        """Tüm ligler için fit et."""
        if self.verbose:
            print(f"\n  ── Poisson Kalibrasyon ─────────────────────")

        for league in LEAGUES:
            result = self.fit_league(league)
            if result:
                self.data[league] = result

        if self.verbose:
            total_teams = sum(len(v["teams"]) for v in self.data.values())
            print(f"  Toplam: {len(self.data)} lig, {total_teams} takım")
            print(f"  ────────────────────────────────────────────")

        return self.data

    # ── Kaydet / Yükle ───────────────────────────────────────────────────────
    def save(self) -> bool:
        try:
            tmp = OUTPUT_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, OUTPUT_FILE)
            if self.verbose:
                print(f"  ✅ team_strengths.json kaydedildi")
            return True
        except Exception as e:
            logger.warning("Kayıt hatası: %s", e)
            return False

    def load(self) -> bool:
        if not os.path.exists(OUTPUT_FILE):
            return False
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                self.data = json.load(f)
            return True
        except Exception:
            return False

    # ── Lambda hesabı ─────────────────────────────────────────────────────────
    def get_lambda(self, league: str,
                   home_team: str,
                   away_team: str) -> Tuple[float, float]:
        """
        İki takım için beklenen gol λH ve λA hesapla.

        Returns:
            (lam_h, lam_a)  → varsayılan: lig ortalaması
        """
        lig = self.data.get(league)
        if not lig:
            return 1.4, 1.2   # genel fallback

        avg_h = lig.get("lig_avg_h", 1.4)
        avg_a = lig.get("lig_avg_a", 1.2)
        teams = lig.get("teams", {})

        # Fuzzy match
        ht_data = self._find_team(home_team, teams)
        at_data = self._find_team(away_team, teams)

        if not ht_data or not at_data:
            return round(avg_h, 3), round(avg_a, 3)

        lam_h = ht_data["attack_h"] * at_data["defense_a"] * avg_h
        lam_a = at_data["attack_a"] * ht_data["defense_h"] * avg_a

        # Güven ağırlığı: düşük veri → lig ortalamasına doğru çek
        conf = min(ht_data["confidence"], at_data["confidence"])
        lam_h = conf * lam_h + (1 - conf) * avg_h
        lam_a = conf * lam_a + (1 - conf) * avg_a

        return round(max(0.3, lam_h), 3), round(max(0.3, lam_a), 3)

    @staticmethod
    def _find_team(name: str, teams: dict) -> Optional[dict]:
        """Takım adını bul — tam eşleşme veya fuzzy."""
        if name in teams:
            return teams[name]
        # Kısmi eşleşme
        name_upper = name.upper()
        for k, v in teams.items():
            if name_upper in k.upper() or k.upper() in name_upper:
                return v
        return None

    # ── Menü B entegrasyonu için özet ────────────────────────────────────────
    def top_teams(self, league: str, n: int = 5) -> str:
        """En güçlü ve en zayıf takımlar."""
        lig = self.data.get(league, {})
        teams = lig.get("teams", {})
        if not teams:
            return ""

        ranked = sorted(teams.items(),
                        key=lambda x: x[1]["attack_h"], reverse=True)
        lines = [f"\n  {league} — En Güçlü Ev (attack_h):"]
        for name, d in ranked[:n]:
            conf = d["confidence"]
            lines.append(f"    {name:<20} atk={d['attack_h']:.2f} "
                         f"def={d['defense_h']:.2f} (n={d['n_ev']} "
                         f"güven={conf:.0%})")
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────
_calibrator: Optional[PoissonCalibrator] = None


def get_calibrator() -> PoissonCalibrator:
    """Singleton — yüklü değilse fit et."""
    global _calibrator
    if _calibrator is None:
        _calibrator = PoissonCalibrator(verbose=False)
        if not _calibrator.load():
            _calibrator.fit_all()
            _calibrator.save()
    return _calibrator


def get_lambda(league: str, home: str, away: str) -> Tuple[float, float]:
    """Kısa yol: λH, λA döndür."""
    return get_calibrator().get_lambda(league, home, away)


# ── Komut satırı ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    cal = PoissonCalibrator(verbose=True)
    cal.fit_all()
    cal.save()
    print(cal.top_teams("T1"))
    print(cal.top_teams("E0"))
    # Test
    lh, la = cal.get_lambda("T1", "Galatasaray", "Fenerbahce")
    print(f"\n  Test: GS(ev) vs FB → λH={lh}, λA={la}")
