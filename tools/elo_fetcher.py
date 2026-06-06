# -*- coding: utf-8 -*-
"""
tools/elo_fetcher.py — Tarihe Göre ClubElo ELO İndirici
=========================================================

İki mod:
  1. Haftalık (Menü 1 entegrasyonu):
     Bu haftanın maç tarihleri → API → elo_weekly.json

  2. Tam güncelleme (Menü C):
     training/ CSV'lerindeki tüm tarihler → API → elo_history.json
     → training_loader.py elo_diff feature'ını doldurur
     → ML doğruluğu %54 → %58+ hedefi

API: http://api.clubelo.com/{YYYY-MM-DD}
     CSV formatı: Rank, Club, Country, Level, Elo, From, To

Cache yapısı:
  elo_history.json:
  {
    "2026-05-24": {"Galatasaray": 1823.5, "Fenerbahce": 1801.2, ...},
    "2026-05-17": {"Galatasaray": 1820.1, ...},
    ...
  }

Kullanım:
  from tools.elo_fetcher import get_elo, fetch_weekly, fetch_full
  elo_h = get_elo("Galatasaray", "2026-05-24")   # → 1823.5
  fetch_weekly(match_dates)                        # Menü 1
  fetch_full()                                     # Menü C
"""

from __future__ import annotations

import os
import json
import time
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Yollar ────────────────────────────────────────────────────────────────────
_HERE          = os.path.dirname(os.path.abspath(__file__))
_ROOT          = os.path.dirname(_HERE)
HISTORY_FILE   = os.path.join(_HERE, "elo_history.json")
WEEKLY_FILE    = os.path.join(_HERE, "elo_weekly.json")
TRAINING_DIR   = os.path.join(_ROOT, "training")

# ── API ───────────────────────────────────────────────────────────────────────
API_BASE    = "http://api.clubelo.com"
TIMEOUT     = 12
RATE_LIMIT  = 1.2   # saniye — API rate limit koruma

# ── Statik FD → ClubElo takım adı eşleştirmesi ───────────────────────────────
TEAM_MAP = {
    # Süper Lig
    "Galatasaray":    "Galatasaray",
    "Fenerbahce":     "Fenerbahce",
    "Besiktas":       "Besiktas",
    "Trabzonspor":    "Trabzonspor",
    "Basaksehir":     "Istanbul Basaksehir",
    "Buyuksehyr":     "Istanbul Basaksehir",
    "Antalyaspor":    "Antalyaspor",
    "Samsunspor":     "Samsunspor",
    "Kasimpasa":      "Kasimpasa",
    "Kayserispor":    "Kayserispor",
    "Konyaspor":      "Konyaspor",
    "Rizespor":       "Caykur Rizespor",
    "Alanyaspor":     "Alanyaspor",
    "Karagumruk":     "Fatih Karagumruk",
    "Fatih Karagumruk":"Fatih Karagumruk",
    "Genclerbirligi": "Genclerbirligi",
    "Gaziantep":      "Gaziantep FK",
    "Eyupspor":       "Eyupspor",
    "Goztepe":        "Goztepe",
    "Sivasspor":      "Sivasspor",
    # Premier League
    "Man City":       "Manchester City",
    "Man United":     "Manchester United",
    "Arsenal":        "Arsenal",
    "Chelsea":        "Chelsea",
    "Liverpool":      "Liverpool",
    "Tottenham":      "Tottenham",
    "Newcastle":      "Newcastle United",
    "Aston Villa":    "Aston Villa",
    "Brighton":       "Brighton",
    "Crystal Palace": "Crystal Palace",
    "Brentford":      "Brentford",
    "Everton":        "Everton",
    "West Ham":       "West Ham United",
    # La Liga
    "Barcelona":      "Barcelona",
    "Real Madrid":    "Real Madrid",
    "Ath Bilbao":     "Athletic Club",
    "Ath Madrid":     "Atletico Madrid",
    "Betis":          "Real Betis",
    "Celta":          "Celta Vigo",
    "Espanyol":       "Espanyol",
    "Girona":         "Girona",
    "Levante":        "Levante",
    "Osasuna":        "Osasuna",
    "Sevilla":        "Sevilla",
    "Sociedad":       "Real Sociedad",
    "Villarreal":     "Villarreal",
    "Valencia":       "Valencia",
    # Serie A
    "AC Milan":       "AC Milan",
    "Inter":          "Inter Milan",
    "Juventus":       "Juventus",
    "Napoli":         "Napoli",
    "Roma":           "Roma",
    "Lazio":          "Lazio",
    "Atalanta":       "Atalanta",
    "Fiorentina":     "Fiorentina",
    "Torino":         "Torino",
    "Cagliari":       "Cagliari",
    # Bundesliga
    "Bayern Munich":  "Bayern Munich",
    "Dortmund":       "Borussia Dortmund",
    "Ein Frankfurt":  "Eintracht Frankfurt",
    "Leverkusen":     "Bayer Leverkusen",
    "Stuttgart":      "VfB Stuttgart",
    # Ligue 1
    "Paris SG":       "Paris Saint-Germain",
    "Lyon":           "Lyon",
    "Lens":           "RC Lens",
    "Monaco":         "Monaco",
    "Lille":          "Lille",
    # Belgian
    "Club Brugge":    "Club Brugge",
    "Anderlecht":     "Anderlecht",
    "Union SG":       "Royale Union Saint-Gilloise",
}


class EloFetcher:
    """Tarihe göre ClubElo ELO indirici."""

    def __init__(self, verbose: bool = True):
        self.verbose  = verbose
        self.history: Dict[str, Dict[str, float]] = {}   # {tarih: {takım: elo}}
        self._load()

    # ── Yükle ────────────────────────────────────────────────────────────────
    def _load(self) -> None:
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, encoding="utf-8") as f:
                    self.history = json.load(f)
                if self.verbose:
                    logger.info("elo_history.json: %d tarih yüklendi",
                                len(self.history))
            except Exception:
                self.history = {}

    # ── Kaydet ───────────────────────────────────────────────────────────────
    def _save(self) -> None:
        try:
            tmp = HISTORY_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
            os.replace(tmp, HISTORY_FILE)
        except Exception as e:
            logger.warning("elo_history kayıt hatası: %s", e)

    # ── Tek tarih için API çağrısı ────────────────────────────────────────────
    def _fetch_date(self, date_str: str) -> Optional[Dict[str, float]]:
        """
        API'den belirli tarihteki tüm ELO puanlarını çek.

        Args:
            date_str: YYYY-MM-DD formatında tarih

        Returns:
            {"Galatasaray": 1823.5, ...} veya None
        """
        # Cache kontrolü
        if date_str in self.history:
            return self.history[date_str]

        try:
            import requests
            url = f"{API_BASE}/{date_str}"
            r   = requests.get(url, timeout=TIMEOUT,
                               headers={"User-Agent": "Mozilla/5.0"})

            if r.status_code != 200:
                logger.warning("ClubElo API %s: HTTP %d", date_str, r.status_code)
                return None

            # CSV parse
            import io, pandas as pd
            df = pd.read_csv(io.StringIO(r.text))

            if "Club" not in df.columns or "Elo" not in df.columns:
                return None

            elo_dict = {
                str(row["Club"]): float(row["Elo"])
                for _, row in df.iterrows()
                if pd.notna(row.get("Elo"))
            }

            if elo_dict:
                self.history[date_str] = elo_dict
                return elo_dict

        except ImportError:
            # requests yoksa urllib dene
            try:
                import urllib.request, io, csv
                req = urllib.request.Request(
                    f"{API_BASE}/{date_str}",
                    headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    content = resp.read().decode("utf-8")

                reader  = csv.DictReader(io.StringIO(content))
                elo_dict = {}
                for row in reader:
                    try:
                        elo_dict[row["Club"]] = float(row["Elo"])
                    except (KeyError, ValueError):
                        continue

                if elo_dict:
                    self.history[date_str] = elo_dict
                    return elo_dict

            except Exception as e2:
                logger.warning("ClubElo urllib %s: %s", date_str, e2)

        except Exception as e:
            logger.warning("ClubElo fetch %s: %s", date_str, e)

        return None

    # ── ELO al ───────────────────────────────────────────────────────────────
    def get_elo(self, team_fd: str, date_str: str) -> float:
        """
        Belirli tarihte takımın ELO değerini döndür.

        Args:
            team_fd:  Football-data takım adı (örn: "Galatasaray")
            date_str: YYYY-MM-DD

        Returns:
            ELO değeri veya 1500.0 (bilinmiyor)
        """
        day_data = self.history.get(date_str)
        if not day_data:
            day_data = self._fetch_date(date_str)
        if not day_data:
            return 1500.0

        # Takım adı eşleştir
        mapped = TEAM_MAP.get(team_fd, team_fd)
        if mapped in day_data:
            return day_data[mapped]

        # Fuzzy
        team_upper = mapped.upper()
        for club, elo in day_data.items():
            if team_upper in club.upper() or club.upper() in team_upper:
                return elo

        return 1500.0

    # ── Haftalık mod (Menü 1) ─────────────────────────────────────────────────
    def fetch_weekly(self, matches: list) -> Dict[str, float]:
        """
        Bu haftanın maçları için ELO çek.

        Args:
            matches: [{"home":"Galatasaray","away":"Fenerbahce",
                       "date":"2026-05-24"}, ...]

        Returns:
            {"Galatasaray_2026-05-24": 1823.5, ...}
        """
        dates = sorted(set(m.get("date","") for m in matches if m.get("date")))
        new_fetched = 0

        for date_str in dates:
            if date_str and date_str not in self.history:
                result = self._fetch_date(date_str)
                if result:
                    new_fetched += 1
                    if self.verbose:
                        print(f"  ✓ ELO {date_str}: {len(result)} kulüp")
                    time.sleep(RATE_LIMIT)

        if new_fetched:
            self._save()

        # Sonuç: her maç için ev/dep ELO
        result_map = {}
        for m in matches:
            date = m.get("date","")
            for team_key in ["home","away"]:
                team = m.get(team_key,"")
                if team and date:
                    elo = self.get_elo(team, date)
                    result_map[f"{team}_{date}"] = elo

        return result_map

    # ── Tam güncelleme (Menü C) ───────────────────────────────────────────────
    def fetch_full(self, progress_cb=None) -> int:
        """
        training/ CSV'lerindeki tüm benzersiz tarihleri çek.
        Uzun sürebilir (~100-500 istek × 1.2s = 2-10 dakika).

        Args:
            progress_cb: ilerleme callback (fetched, total) → None

        Returns:
            Yeni eklenen tarih sayısı
        """
        try:
            import pandas as pd
        except ImportError:
            print("  ✗ pandas yok")
            return 0

        # Tüm benzersiz tarihleri topla
        all_dates = set()
        for season in ["2526","2425","2324"]:
            season_dir = os.path.join(TRAINING_DIR, season)
            if not os.path.exists(season_dir):
                continue
            for fname in os.listdir(season_dir):
                if not fname.endswith(".csv"):
                    continue
                try:
                    df = pd.read_csv(os.path.join(season_dir, fname),
                                     usecols=["Date"],
                                     low_memory=False)
                    for d in df["Date"].dropna().unique():
                        # DD/MM/YYYY → YYYY-MM-DD
                        try:
                            from datetime import datetime
                            parsed = None
                            for fmt in ["%d/%m/%Y","%Y-%m-%d","%d/%m/%y"]:
                                try:
                                    parsed = datetime.strptime(str(d), fmt)
                                    break
                                except ValueError:
                                    continue
                            if parsed:
                                all_dates.add(parsed.strftime("%Y-%m-%d"))
                        except Exception:
                            pass
                except Exception:
                    continue

        # Cache'te olmayanları çek
        missing = sorted(all_dates - set(self.history.keys()))
        total   = len(missing)

        if self.verbose:
            print(f"\n  ── ELO Tam Güncelleme ────────────────────")
            print(f"  Toplam benzersiz tarih: {len(all_dates)}")
            print(f"  Cache'te var: {len(all_dates) - total}")
            print(f"  İndirilecek: {total}")
            if total > 0:
                est_min = total * RATE_LIMIT / 60
                print(f"  Tahmini süre: ~{est_min:.0f} dakika")
            print()

        new_count = 0
        for i, date_str in enumerate(missing):
            result = self._fetch_date(date_str)
            if result:
                new_count += 1
                if self.verbose and (i+1) % 10 == 0:
                    print(f"  [{i+1}/{total}] {date_str}: {len(result)} kulüp")
                if progress_cb:
                    progress_cb(i+1, total)
                time.sleep(RATE_LIMIT)

            # Her 50 tarihte kaydet
            if new_count % 50 == 0 and new_count > 0:
                self._save()

        self._save()

        if self.verbose:
            print(f"\n  ✅ {new_count} yeni tarih eklendi")
            print(f"  elo_history.json: {len(self.history)} toplam tarih")

        return new_count

    # ── Durum ────────────────────────────────────────────────────────────────
    def status(self) -> str:
        n = len(self.history)
        if n == 0:
            return "  ELO History: YOK — Menü C ile indir"
        dates = sorted(self.history.keys())
        return (f"  ELO History: {n} tarih "
                f"({dates[0]} → {dates[-1]})")


# ── Kısa yol fonksiyonları ────────────────────────────────────────────────────
_fetcher: Optional[EloFetcher] = None


def _get_fetcher() -> EloFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = EloFetcher(verbose=False)
    return _fetcher


def get_elo(team: str, date: str) -> float:
    """Kısa yol: takım + tarih → ELO."""
    return _get_fetcher().get_elo(team, date)


def fetch_weekly(matches: list) -> Dict[str, float]:
    """Kısa yol: haftalık ELO güncelleme."""
    f = EloFetcher(verbose=True)
    return f.fetch_weekly(matches)


def fetch_full(verbose: bool = True) -> int:
    """Kısa yol: tam tarihsel ELO indirimi."""
    f = EloFetcher(verbose=verbose)
    return f.fetch_full()
