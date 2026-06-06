# -*- coding: utf-8 -*-
"""
memory/clv_tracker.py — Closing Line Value (CLV) Takip Sistemi
===============================================================
CLV = model tahminimiz kapanış oranından ne kadar "değer" içeriyordu?

Akademik temel (Buchdahl 2014; Štrumbelj 2014):
  CLV > 0 → model kapanış çizgisini aştı → gerçek edge var
  CLV < 0 → model kapanış çizgisinin gerisinde → edge yok, revizyon gerekli

Kullanım:
  from memory.clv_tracker import CLVTracker
  clv = CLVTracker()
  clv.record(week_id, match_no, model_p, opening_odds, closing_odds, outcome)
  clv.summary()

~50 bahis sonrası istatistiksel anlamlılık gösterir.
"""

from __future__ import annotations
import os, json, math
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
CLV_FILE = os.path.join(_ROOT, "clv_history.json")


def _safe_prob(odds: float) -> float:
    """Oran → ham olasılık (overround çıkarılmadan)."""
    if not odds or odds <= 1.0:
        return 0.0
    return round(1.0 / float(odds), 6)


def _closing_edge(model_p: float, closing_odds: float) -> float:
    """
    CLV = model_p - closing_implied_p
    > 0: model kapanış değerinin üzerinde → iyi sinyal
    < 0: model kapanış değerinin altında → kötü sinyal
    """
    if not closing_odds or closing_odds <= 1.0 or not model_p:
        return None
    closing_p = _safe_prob(closing_odds)
    if closing_p <= 0:
        return None
    return round(model_p - closing_p, 4)


class CLVTracker:
    """
    Tahmin başına CLV kaydeder ve istatistik üretir.
    JSON'a atomik yazar (crash-safe).
    """

    def __init__(self):
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(CLV_FILE):
            try:
                with open(CLV_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"records": [], "created": datetime.now().isoformat()}

    def _save(self):
        try:
            tmp = CLV_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CLV_FILE)
        except Exception as e:
            print(f"  [CLV] Kayıt hatası: {e}")

    def record(self,
               week_id: str,
               match_no: int,
               match_name: str,
               selection: str,          # "1", "X", "2"
               model_p: float,          # modelimizin olasılığı (0-1)
               opening_odds: float,     # açılış oranı
               closing_odds: float,     # kapanış oranı (en değerli)
               outcome: str = None,     # "W" / "L" / None (bilinmiyor)
               league: str = "") -> dict:
        """
        Tek bahis kaydı ekle.
        outcome daha sonra update_outcome() ile girilebilir.
        """
        clv = _closing_edge(model_p, closing_odds)
        opening_edge = _closing_edge(model_p, opening_odds)

        rec = {
            "week":         week_id,
            "no":           match_no,
            "mac":          match_name,
            "sel":          selection,
            "model_p":      round(float(model_p), 4),
            "open_odds":    opening_odds,
            "close_odds":   closing_odds,
            "open_edge":    opening_edge,
            "clv":          clv,
            "outcome":      outcome,
            "league":       league,
            "ts":           datetime.now().isoformat()[:16],
        }
        # Güncelle veya ekle
        idx = next((i for i, r in enumerate(self.data["records"])
                    if r["week"] == week_id and r["no"] == match_no), None)
        if idx is not None:
            self.data["records"][idx] = rec
        else:
            self.data["records"].append(rec)
        self._save()
        return rec

    def update_outcome(self, week_id: str, match_no: int,
                       outcome: str) -> bool:
        """
        Maç bittikten sonra sonucu kaydet.
        outcome: "W" (kazandı) veya "L" (kaybetti) — seçime göre.
        """
        for r in self.data["records"]:
            if r["week"] == week_id and r["no"] == match_no:
                r["outcome"] = outcome
                self._save()
                return True
        return False

    def summary(self, last_n: int = None) -> dict:
        """
        CLV istatistikleri.

        Döner:
          avg_clv      : ortalama CLV (>0 = edge var)
          clv_positive : CLV > 0 olan bahis oranı
          n            : toplam bahis
          win_rate     : sonuçlanan bahislerde kazanma oranı
          roi          : birim bahis başına net kazanç
          signal       : "GÜÇLÜ EDGE" / "ZAYIF EDGE" / "EDGE YOK"
        """
        recs = self.data["records"]
        if last_n:
            recs = recs[-last_n:]

        n = len(recs)
        if n == 0:
            return {"n": 0, "avg_clv": None, "signal": "VERİ YOK"}

        # CLV hesapları
        clv_vals = [r["clv"] for r in recs if r["clv"] is not None]
        avg_clv  = round(sum(clv_vals) / len(clv_vals), 4) if clv_vals else None
        clv_pos  = sum(1 for v in clv_vals if v > 0) / len(clv_vals) if clv_vals else None

        # Kazanç istatistikleri
        done = [r for r in recs if r.get("outcome") in ("W", "L")]
        win_rate = sum(1 for r in done if r["outcome"]=="W") / len(done) if done else None

        # ROI (closing odds bazlı)
        roi = None
        if done:
            profit = sum(
                (float(r["close_odds"] or 1) - 1) if r["outcome"] == "W" else -1.0
                for r in done if r.get("close_odds")
            )
            roi = round(profit / len(done), 4) if done else None

        # Sinyal değerlendirmesi (Buchdahl kriterleri)
        if avg_clv is None:
            signal = "KALİBRASYON YOK (kapanış oranı eksik)"
        elif avg_clv > 0.02 and len(clv_vals) >= 30:
            signal = "✅ GÜÇLÜ EDGE (+%{:.1f} CLV, n={})".format(avg_clv*100, len(clv_vals))
        elif avg_clv > 0:
            signal = "🟡 ZAYIF EDGE (+%{:.1f} CLV — {} bahis yeterli değil, 50+ gerek)".format(
                avg_clv*100, len(clv_vals))
        else:
            signal = "❌ EDGE YOK (%{:.1f} CLV — tahmin stratejisi gözden geçir)".format(
                avg_clv*100)

        return {
            "n":            n,
            "clv_n":        len(clv_vals),
            "avg_clv":      avg_clv,
            "clv_positive": round(clv_pos, 3) if clv_pos else None,
            "win_rate":     round(win_rate, 3) if win_rate else None,
            "roi":          roi,
            "signal":       signal,
        }

    def print_summary(self, last_n: int = None):
        """CLV özetini terminale yazdır."""
        s = self.summary(last_n=last_n)

        print("\n  ── CLV TRACKER ──────────────────────────────")
        print(f"  Toplam kayıt  : {s['n']} bahis")
        if s.get("avg_clv") is not None:
            print(f"  Ort. CLV      : %{s['avg_clv']*100:+.2f}")
        if s.get("clv_positive") is not None:
            print(f"  CLV > 0 oranı : %{s['clv_positive']*100:.0f}")
        if s.get("win_rate") is not None:
            print(f"  Kazanma oranı : %{s['win_rate']*100:.1f}")
        if s.get("roi") is not None:
            print(f"  ROI           : %{s['roi']*100:.1f}")
        print(f"\n  {s['signal']}")
        print(f"  {'─'*44}")

        # Son 10 kayıt
        recs = self.data["records"]
        if recs:
            print(f"\n  Son {min(10,len(recs))} kayıt:")
            print(f"  {'Hafta':<12} {'#':>2} {'Sel':>3} {'Mdl%':>6} "
                  f"{'Açılış':>6} {'Kapanış':>7} {'CLV':>7} {'S'}")
            print(f"  {'─'*58}")
            for r in recs[-10:]:
                clv_str = f"%{r['clv']*100:+.1f}" if r['clv'] is not None else "  —  "
                out = r.get("outcome") or "?"
                print(f"  {r['week']:<12} {r['no']:>2} {r['sel']:>3} "
                      f"%{r['model_p']*100:>5.1f} "
                      f"{r.get('open_odds') or '—':>6} "
                      f"{r.get('close_odds') or '—':>7} "
                      f"{clv_str:>7} {out}")


# ── Singleton ──────────────────────────────────────────────────────────────
_clv: CLVTracker = None

def get_clv_tracker() -> CLVTracker:
    global _clv
    if _clv is None:
        _clv = CLVTracker()
    return _clv
