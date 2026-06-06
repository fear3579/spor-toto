# -*- coding: utf-8 -*-
"""
data/api_football.py — API-Football v3 Merkezi İstemcisi
=========================================================

Kullanım:
  from data.api_football import APIFootball
  api = APIFootball()
  fixtures = api.fixtures(league_id=203, season=2025, date="2026-05-24")

Güvenlik:
  API_KEY'i asla koda yazma — .env veya config.py kullan:
  .env dosyasında: API_FOOTBALL_KEY=xxxxxxxx
  config.py'de:    API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY","")

Cache:
  Her endpoint sonucu cache klasöründe saklanır.
  Aynı sorgu TTL süresi dolmadan tekrar API'ye gitmez.
"""

from __future__ import annotations

import os
import json
import time
import hashlib
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ── Yollar ────────────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.dirname(_HERE)
CACHE_DIR = os.path.join(_ROOT, "fd_cache", "api_football")

# ── API Sabitleri ─────────────────────────────────────────────────────────────
API_BASE    = "https://v3.football.api-sports.io"
RATE_LIMIT  = 0.3      # Pro plan: 30 istek/dakika → 0.3s arası yeterli
TIMEOUT     = 15       # saniye
DAILY_LIMIT = 7500     # Pro plan günlük limit

# ── Günlük kullanım sayacı dosyası ───────────────────────────────────────────
_USAGE_FILE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "fd_cache", "api_usage.json")

# ── Cache TTL (saat) ──────────────────────────────────────────────────────────
TTL = {
    "fixtures":         2.0,    # Maç sonuçları 2 saatte bir
    "injuries":         6.0,    # Sakatlıklar 6 saatte bir
    "standings":        24.0,   # Lig tablosu günde bir
    "leagues":          168.0,  # Lig listesi haftada bir
    "predictions":      4.0,    # Tahminler 4 saatte bir
    "odds":             1.0,    # Oranlar maç günü saatlik
    "sidelined":        12.0,   # Uzun süreli sakat günde 2 kez
    "lineups":          1.0,    # 11 maçtan 1 saat önce açıklanır
    "topscorers":       24.0,   # Gol krallığı günde bir
    "players":          24.0,   # Oyuncu istatistikleri günde bir
    "coachs":           168.0,  # Hoca bilgisi haftada bir
    "transfers":        168.0,  # Transfer haftada bir
    "default":          2.0,
}

# ── Lig ID Haritası ───────────────────────────────────────────────────────────
LEAGUE_ID_MAP: Dict[str, int] = {
    "T1":   203,   # Türkiye Süper Lig
    "E0":   39,    # İngiltere Premier League
    "SP1":  140,   # İspanya La Liga
    "I1":   135,   # İtalya Serie A
    "D1":   78,    # Almanya Bundesliga
    "F1":   61,    # Fransa Ligue 1
    "N1":   88,    # Hollanda Eredivisie
    "B1":   144,   # Belçika Pro League
    "P1":   94,    # Portekiz Primeira Liga
    "G1":   197,   # Yunanistan Super League
    "SC0":  179,   # İskoçya Premiership
}

# Sezon yıl haritası (API sezon formatı)
SEASON_MAP: Dict[str, int] = {
    "2526": 2025,
    "2627": 2026,
    "2425": 2024,
    "2324": 2023,
}

# Takım adı normalizasyon (API adı → sistemdeki fd_cache adı)
TEAM_NAME_MAP: Dict[str, str] = {
    # Türk takımları
    "Galatasaray":             "Galatasaray",
    "Fenerbahçe":              "Fenerbahce",
    "Fenerbahce":              "Fenerbahce",
    "Beşiktaş":                "Besiktas",
    "Besiktas":                "Besiktas",
    "Trabzonspor":             "Trabzonspor",
    "Istanbul Basaksehir":     "Buyuksehyr",
    "Başakşehir":              "Buyuksehyr",
    "Samsunspor":              "Samsunspor",
    "Gaziantep FK":            "Gaziantep",
    "Fatih Karagümrük":        "Fatih Karagumruk",
    "Kasımpaşa":               "Kasimpasa",
    "Kayserispor":             "Kayserispor",
    "Alanyaspor":              "Alanyaspor",
    "Antalyaspor":             "Antalyaspor",
    "Rizespor":                "Caykur Rizespor",
    "Çaykur Rizespor":         "Caykur Rizespor",
    "Konyaspor":               "Konyaspor",
    "Göztepe":                 "Goztepe",
    "Eyüpspor":                "Eyupspor",
    "Gençlerbirliği":          "Genclerbirligi",
    "Kocaelispor":             "Kocaelispor",
    # Premier League
    "Manchester City":         "Man City",
    "Manchester United":       "Man United",
    "Arsenal":                 "Arsenal",
    "Chelsea":                 "Chelsea",
    "Liverpool":               "Liverpool",
    "Tottenham Hotspur":       "Tottenham",
    "Newcastle United":        "Newcastle",
    "Aston Villa":             "Aston Villa",
    "Brighton & Hove Albion":  "Brighton",
    "Crystal Palace":          "Crystal Palace",
    "Brentford":               "Brentford",
    "Everton":                 "Everton",
    "West Ham United":         "West Ham",
    "Fulham":                  "Fulham",
    "Nottingham Forest":       "Nottm Forest",
    "Bournemouth":             "Bournemouth",
    "Leicester City":          "Leicester",
    "Wolverhampton":           "Wolves",
    # La Liga
    "Barcelona":               "Barcelona",
    "Real Madrid":             "Real Madrid",
    "Athletic Club":           "Ath Bilbao",
    "Atletico Madrid":         "Ath Madrid",
    "Real Betis":              "Betis",
    "Celta Vigo":              "Celta",
    "Espanyol":                "Espanyol",
    "Girona":                  "Girona",
    "Levante":                 "Levante",
    "Osasuna":                 "Osasuna",
    "Sevilla":                 "Sevilla",
    "Real Sociedad":           "Sociedad",
    "Villarreal":              "Villarreal",
    "Valencia":                "Valencia",
    # Serie A
    "AC Milan":                "AC Milan",
    "Inter":                   "Inter",
    "Juventus":                "Juventus",
    "Napoli":                  "Napoli",
    "AS Roma":                 "Roma",
    "SS Lazio":                "Lazio",
    "Atalanta":                "Atalanta",
    "Fiorentina":              "Fiorentina",
    "Torino":                  "Torino",
    "Cagliari":                "Cagliari",
    # Bundesliga
    "Bayern Munich":           "Bayern Munich",
    "Borussia Dortmund":       "Dortmund",
    "Eintracht Frankfurt":     "Ein Frankfurt",
    "Bayer Leverkusen":        "Leverkusen",
    "VfB Stuttgart":           "Stuttgart",
    # Ligue 1
    "Paris Saint-Germain":     "Paris SG",
    "Olympique Lyonnais":      "Lyon",
    "RC Lens":                 "Lens",
    "AS Monaco":               "Monaco",
    "Lille":                   "Lille",
}


class APIFootball:
    """
    API-Football v3 istemcisi.
    Cache-first: aynı sorgu TTL dolmadan tekrar API'ye gitmez.
    """

    def __init__(self, api_key: str = None):
        # API_KEY öncelik: parametre > .env > config.py
        self.key = api_key or self._load_key()
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._last_request = 0.0
        self._coverage_cache: dict = {}  # {league_id: coverage_dict}

    # ── Günlük Kullanım Sayacı ────────────────────────────────────────────────
    @staticmethod
    def _get_usage() -> dict:
        """Bugünkü API kullanımını oku."""
        today = time.strftime("%Y-%m-%d")
        try:
            if os.path.exists(_USAGE_FILE):
                d = json.load(open(_USAGE_FILE, encoding="utf-8"))
                if d.get("date") == today:
                    return d
        except Exception:
            pass
        return {"date": today, "count": 0, "endpoints": {}}

    @staticmethod
    def _inc_usage(endpoint: str):
        """API isteği sayacını artır."""
        today = time.strftime("%Y-%m-%d")
        try:
            usage = APIFootball._get_usage()
            if usage.get("date") != today:
                usage = {"date": today, "count": 0, "endpoints": {}}
            usage["count"] = usage.get("count", 0) + 1
            ep = usage.setdefault("endpoints", {})
            ep[endpoint] = ep.get(endpoint, 0) + 1
            os.makedirs(os.path.dirname(_USAGE_FILE), exist_ok=True)
            with open(_USAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(usage, f)
        except Exception:
            pass

    def usage_status(self) -> str:
        """Günlük kullanım durumu."""
        u = self._get_usage()
        n = u.get("count", 0)
        pct = n / DAILY_LIMIT * 100
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        color = "\033[32m" if pct < 60 else ("\033[33m" if pct < 85 else "\033[31m")
        return (f"  API Kullanım: {color}{n}/{DAILY_LIMIT} ({pct:.1f}%)\033[0m\n"
                f"  [{bar}]")

    # ── API Anahtarı ──────────────────────────────────────────────────────────
    @staticmethod
    def _load_key() -> str:
        # 1. ortam değişkeni
        k = os.getenv("API_FOOTBALL_KEY", "")
        if k: return k

        # 2. .env dosyası
        env_path = os.path.join(_ROOT, ".env")
        if os.path.exists(env_path):
            for line in open(env_path).readlines():
                if line.startswith("API_FOOTBALL_KEY="):
                    k = line.split("=", 1)[1].strip()
                    if k: return k

        # 3. config.py
        try:
            from config import CFG
            k = CFG.get("API_FOOTBALL_KEY", "")
            if k: return k
        except Exception:
            pass

        return ""

    # ── Cache ─────────────────────────────────────────────────────────────────
    def _cache_key(self, endpoint: str, params: dict) -> str:
        raw = endpoint + json.dumps(params, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _cache_path(self, cache_key: str) -> str:
        return os.path.join(CACHE_DIR, f"{cache_key}.json")

    def _cache_get(self, endpoint: str, params: dict,
                   ttl_h: float) -> Optional[dict]:
        path = self._cache_path(self._cache_key(endpoint, params))
        if not os.path.exists(path):
            return None
        age_h = (time.time() - os.path.getmtime(path)) / 3600
        if age_h > ttl_h:
            return None
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return None

    def _cache_set(self, endpoint: str, params: dict, data: dict):
        path = self._cache_path(self._cache_key(endpoint, params))
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Cache yazma hatası: %s", e)

    # ── HTTP İstek ────────────────────────────────────────────────────────────
    def _request(self, endpoint: str, params: dict) -> Optional[dict]:
        if not self.key:
            logger.warning("API_FOOTBALL_KEY boş — istek yapılamıyor")
            return None

        # Günlük limit kontrolü
        usage = self._get_usage()
        if usage.get("count", 0) >= DAILY_LIMIT:
            logger.warning("API günlük limit aşıldı (%d/%d)", usage["count"], DAILY_LIMIT)
            return None

        # Rate limit
        elapsed = time.time() - self._last_request
        if elapsed < RATE_LIMIT:
            time.sleep(RATE_LIMIT - elapsed)

        url = f"{API_BASE}/{endpoint}"
        headers = {
            "x-rapidapi-host": "v3.football.api-sports.io",
            "x-rapidapi-key":  self.key,
        }

        try:
            import requests
            r = requests.get(url, headers=headers, params=params,
                             timeout=TIMEOUT)
            self._last_request = time.time()

            if r.status_code == 200:
                data = r.json()
                errors = data.get("errors", {})
                if errors:
                    logger.warning("API hatası %s: %s", endpoint, errors)
                    return None
                self._inc_usage(endpoint)  # Başarılı istek sayıldı
                return data

            elif r.status_code == 403:
                logger.error("API 403 Forbidden — API_KEY geçersiz veya kota doldu")
                return None
            else:
                logger.warning("API HTTP %d — %s", r.status_code, endpoint)
                return None

        except Exception as e:
            logger.warning("API istek hatası %s: %s", endpoint, e)
            return None

    # ── Genel GET ─────────────────────────────────────────────────────────────
    def get(self, endpoint: str, params: dict = None,
            ttl_h: float = None) -> Optional[dict]:
        params = params or {}
        ttl_h  = ttl_h or TTL.get(endpoint.split("/")[0], TTL["default"])

        # Cache kontrol
        cached = self._cache_get(endpoint, params, ttl_h)
        if cached is not None:
            return cached

        # API isteği
        data = self._request(endpoint, params)
        if data:
            self._cache_set(endpoint, params, data)

        return data

    # ── Endpoint Metodları ────────────────────────────────────────────────────

    def fixtures(self, league_id: int, season: int,
                 date: str = None, status: str = None) -> list:
        """
        /fixtures — Maç listesi.

        Args:
            league_id: API lig ID (ör. 203 = Süper Lig)
            season:    Sezon yılı (ör. 2025)
            date:      YYYY-MM-DD formatında tarih (opsiyonel)
            status:    "FT" = bitti, "NS" = başlamadı (opsiyonel)

        Returns:
            [{"fixture_id":..., "home":"GS", "away":"FB",
              "home_score":2, "away_score":1, "status":"FT"}, ...]
        """
        params = {"league": league_id, "season": season}
        if date:   params["date"]   = date
        if status: params["status"] = status

        data = self.get("fixtures", params, TTL["fixtures"])
        if not data:
            return []

        results = []
        for item in data.get("response", []):
            fix   = item.get("fixture", {})
            teams = item.get("teams", {})
            goals = item.get("goals", {})

            home_raw = teams.get("home", {}).get("name", "")
            away_raw = teams.get("away", {}).get("name", "")

            results.append({
                "fixture_id": fix.get("id"),
                "date":       fix.get("date", "")[:10],
                "status":     fix.get("status", {}).get("short", ""),
                "home":       TEAM_NAME_MAP.get(home_raw, home_raw),
                "away":       TEAM_NAME_MAP.get(away_raw, away_raw),
                "home_raw":   home_raw,
                "away_raw":   away_raw,
                "home_score": goals.get("home"),
                "away_score": goals.get("away"),
                "league_id":  league_id,
            })

        return results

    def injuries(self, fixture_id: int) -> list:
        """
        /injuries — Maç sakatlık/ceza listesi.

        Returns:
            [{"team":"home"/"away", "player":"...",
              "type":"injury"/"suspension", "reason":"..."}, ...]
        """
        params = {"fixture": fixture_id}
        data   = self.get("injuries", params, TTL["injuries"])
        if not data:
            return []

        results = []
        for item in data.get("response", []):
            player = item.get("player", {})
            team   = item.get("team", {})
            results.append({
                "player":   player.get("name", ""),
                "team_id":  team.get("id"),
                "team_name":team.get("name", ""),
                "type":     item.get("type", ""),
                "reason":   item.get("reason", ""),
            })

        return results

    def standings(self, league_id: int, season: int) -> list:
        """
        /standings — Lig tablosu.

        Returns:
            [{"rank":1, "team":"Galatasaray", "points":86,
              "played":38, "win":27, "draw":5, "lose":6,
              "form":"WWWDW"}, ...]
        """
        params = {"league": league_id, "season": season}
        data   = self.get("standings", params, TTL["standings"])
        if not data:
            return []

        results = []
        try:
            table = data["response"][0]["league"]["standings"][0]
            for entry in table:
                team_raw = entry.get("team", {}).get("name", "")
                results.append({
                    "rank":     entry.get("rank"),
                    "team":     TEAM_NAME_MAP.get(team_raw, team_raw),
                    "team_raw": team_raw,
                    "team_id":  entry.get("team",{}).get("id", 0),
                    "points": entry.get("points"),
                    "played": entry.get("all", {}).get("played"),
                    "win":    entry.get("all", {}).get("win"),
                    "draw":   entry.get("all", {}).get("draw"),
                    "lose":   entry.get("all", {}).get("lose"),
                    "gf":     entry.get("all", {}).get("goals", {}).get("for"),
                    "ga":     entry.get("all", {}).get("goals", {}).get("against"),
                    "form":   entry.get("form", ""),
                })
        except (KeyError, IndexError, TypeError):
            pass

        return results

    def predictions(self, fixture_id: int) -> Optional[dict]:
        """
        /predictions — API tahminleri (meta-model olarak).

        Returns:
            {"winner_team":"GS", "p1":65, "px":20, "p2":15,
             "advice":"Home win"} veya None
        """
        params = {"fixture": fixture_id}
        data   = self.get("predictions", params, TTL["predictions"])
        if not data:
            return None

        try:
            pred = data["response"][0]["predictions"]
            pct  = pred.get("percent", {})
            return {
                "winner_team": pred.get("winner", {}).get("name", ""),
                "advice":      pred.get("advice", ""),
                "p1": int(pct.get("home", "0").replace("%","")),
                "px": int(pct.get("draw", "0").replace("%","")),
                "p2": int(pct.get("away", "0").replace("%","")),
            }
        except Exception:
            return None

    def leagues(self, country: str = None) -> list:
        """
        /leagues — Lig listesi + coverage bilgisi.

        Returns:
            [{"id":203, "name":"Süper Lig", "country":"Turkey",
              "has_injuries":True, "has_odds":True}, ...]
        """
        params = {}
        if country: params["country"] = country

        data = self.get("leagues", params, TTL["leagues"])
        if not data:
            return []

        results = []
        for item in data.get("response", []):
            league   = item.get("league", {})
            coverage = item.get("seasons", [{}])[-1].get("coverage", {})
            results.append({
                "id":            league.get("id"),
                "name":          league.get("name", ""),
                "country":       item.get("country", {}).get("name", ""),
                "has_injuries":  coverage.get("injuries", False),
                "has_odds":      coverage.get("odds", False),
                "has_standings": coverage.get("standings", False),
                "has_players":   coverage.get("players", False),
            })

        return results

    # ── Yardımcı ─────────────────────────────────────────────────────────────

    def find_fixture_id(self, league_code: str, season_code: str,
                        home_team: str, away_team: str,
                        date_str: str) -> Optional[int]:
        """
        Takım adı + tarihten fixture ID bul.

        Args:
            league_code: "T1", "E0" gibi
            season_code: "2526" gibi
            home_team:   fd_cache takım adı
            away_team:   fd_cache takım adı
            date_str:    "YYYY-MM-DD"

        Returns:
            fixture_id (int) veya None
        """
        league_id = LEAGUE_ID_MAP.get(league_code)
        season    = SEASON_MAP.get(season_code)
        if not league_id or not season:
            return None

        fixtures = self.fixtures(league_id, season, date=date_str)
        for f in fixtures:
            if (self._team_match(f["home"], home_team) and
                    self._team_match(f["away"], away_team)):
                return f["fixture_id"]

        return None

    @staticmethod
    def _team_match(api_name: str, fd_name: str) -> bool:
        """Fuzzy takım adı eşleştirme."""
        a = api_name.upper().replace(" ", "")
        b = fd_name.upper().replace(" ", "")
        if a == b: return True
        if a in b or b in a: return True
        # 3 karakter prefix eşleştirme
        if len(a) >= 3 and len(b) >= 3 and a[:4] == b[:4]: return True
        return False

    # ── Durum raporu ─────────────────────────────────────────────────────────

    def status(self) -> str:
        """API durumu + günlük kullanım."""
        if not self.key:
            return "❌ API_KEY eksik — .env dosyasına API_FOOTBALL_KEY=xxx ekle"
        n_cached = len([f for f in os.listdir(CACHE_DIR)
                        if f.endswith(".json")]) if os.path.exists(CACHE_DIR) else 0
        usage = self._get_usage()
        n = usage.get("count", 0)
        pct = round(n / DAILY_LIMIT * 100, 1)
        return (f"✅ API_KEY: ...{self.key[-4:]}  |  "
                f"Günlük: {n}/{DAILY_LIMIT} ({pct}%)  |  "
                f"Cache: {n_cached} dosya")

    def team_statistics(self, team_id: int, league_id: int,
                        season: int) -> dict:
        """
        /teams/statistics — Takım sezon özeti.

        Döner:
            {
              "home_win_rate":    0.55,
              "away_win_rate":    0.38,
              "home_draw_rate":   0.22,
              "away_draw_rate":   0.28,
              "clean_sheet_rate": 0.35,
              "btts_rate":        0.48,
              "goals_scored_avg": 1.62,
              "goals_conceded_avg": 1.05,
              "form": "WWDLW",
            }
        """
        params = {"team": team_id, "league": league_id, "season": season}
        data   = self.get("teams/statistics", params, TTL["standings"])
        if not data:
            return {}
        try:
            r = data["response"]
            total  = r.get("fixtures", {})
            home   = total.get("played", {}).get("home", 1) or 1
            away   = total.get("played", {}).get("away", 1) or 1
            wins_h = total.get("wins",   {}).get("home", 0)
            wins_a = total.get("wins",   {}).get("away", 0)
            draw_h = total.get("draws",  {}).get("home", 0)
            draw_a = total.get("draws",  {}).get("away", 0)
            goals  = r.get("goals", {})
            gf_h   = goals.get("for",     {}).get("total", {}).get("home", 0)
            gf_a   = goals.get("for",     {}).get("total", {}).get("away", 0)
            ga_h   = goals.get("against", {}).get("total", {}).get("home", 0)
            ga_a   = goals.get("against", {}).get("total", {}).get("away", 0)
            cs     = r.get("clean_sheet", {})
            cs_tot = cs.get("home", 0) + cs.get("away", 0)
            total_p= home + away
            btts   = r.get("failed_to_score", {})
            btts_n = total_p - btts.get("total", 0) if btts else total_p // 2
            return {
                "home_win_rate":       round(wins_h / home, 3),
                "away_win_rate":       round(wins_a / away, 3),
                "home_draw_rate":      round(draw_h / home, 3),
                "away_draw_rate":      round(draw_a / away, 3),
                "clean_sheet_rate":    round(cs_tot / max(1, total_p), 3),
                "btts_rate":           round(btts_n / max(1, total_p), 3),
                "goals_scored_avg":    round((gf_h + gf_a) / max(1, total_p), 3),
                "goals_conceded_avg":  round((ga_h + ga_a) / max(1, total_p), 3),
                "home_goals_avg":      round(gf_h / home, 3),
                "away_goals_avg":      round(gf_a / away, 3),
                "form":                r.get("form", ""),
            }
        except Exception:
            return {}

    def fixture_statistics(self, fixture_id: int) -> dict:
        """
        /fixtures/statistics — Maç istatistikleri (şut, sahip, xG).

        Döner:
            {
              "home": {"possession": 58, "shots_on_target": 6,
                       "xg": 1.8, "corners": 7, "fouls": 11},
              "away": {"possession": 42, "shots_on_target": 3,
                       "xg": 0.9, "corners": 4, "fouls": 14},
            }
        """
        params = {"fixture": fixture_id}
        data   = self.get("fixtures/statistics", params, TTL["fixtures"])
        if not data:
            return {}
        try:
            result = {}
            for team_data in data.get("response", []):
                stats = {s["type"]: s["value"]
                         for s in team_data.get("statistics", [])}
                side  = "home" if len(result) == 0 else "away"

                def _num(key, default=0):
                    val = stats.get(key)
                    if val is None: return default
                    if isinstance(val, str):
                        val = val.replace("%", "").strip()
                    try: return float(val)
                    except: return default

                result[side] = {
                    "possession":       _num("Ball Possession"),
                    "shots_on_target":  _num("Shots on Goal"),
                    "shots_total":      _num("Total Shots"),
                    "xg":               _num("expected_goals", -1),
                    "corners":          _num("Corner Kicks"),
                    "fouls":            _num("Fouls"),
                    "yellow_cards":     _num("Yellow Cards"),
                    "red_cards":        _num("Red Cards"),
                }
            return result
        except Exception:
            return {}

    def fixtures_batch(self, fixture_ids: list) -> list:
        """
        /fixtures?ids= — 20'şer batch çağrısı.
        1 istek = 20 maç × (events + lineups + statistics + players).
        Tekil fixture_statistics() çağrısına göre ~20x istek tasarrufu.

        Döner:
            [{"fixture_id": 12345,
              "stats": {"home": {...}, "away": {...}},
              "lineups": [...], "players": [...], "events": [...]}]
        """
        results = []
        for i in range(0, len(fixture_ids), 20):
            batch   = fixture_ids[i:i + 20]
            ids_str = "-".join(str(fid) for fid in batch)
            data    = self.get("fixtures", {"ids": ids_str}, TTL["fixtures"])
            if not data:
                continue
            for item in data.get("response", []):
                fid = item.get("fixture", {}).get("id")
                if not fid:
                    continue
                # fixture_statistics ile aynı parse mantığı
                raw_stats = item.get("statistics", [])
                parsed_stats: dict = {}
                for idx, team_data in enumerate(raw_stats[:2]):
                    side = "home" if idx == 0 else "away"
                    st = {s["type"]: s["value"]
                          for s in team_data.get("statistics", [])}
                    def _n(key, d=0):
                        v = st.get(key)
                        if v is None: return d
                        if isinstance(v, str): v = v.replace("%", "").strip()
                        try: return float(v)
                        except: return d
                    parsed_stats[side] = {
                        "possession":      _n("Ball Possession"),
                        "shots_on_target": _n("Shots on Goal"),
                        "shots_total":     _n("Total Shots"),
                        "xg":              _n("expected_goals", -1),
                        "corners":         _n("Corner Kicks"),
                        "fouls":           _n("Fouls"),
                    }
                results.append({
                    "fixture_id": fid,
                    "stats":      parsed_stats,
                    "lineups":    item.get("lineups", []),
                    "players":    item.get("players", []),
                    "events":     item.get("events", []),
                })
        return results

    def odds_prematch(self, fixture_id: int,
                      bookmaker_id: int = 8) -> dict:
        """
        /odds — Maç öncesi 1X2 oranları (varsayılan: Bet365).
        bookmaker_id: 8=Bet365, 11=Bwin, 6=Betfair

        Döner:
            {"close": {"1": 1.75, "X": 3.50, "2": 4.50}}
        """
        params = {"fixture": fixture_id, "bookmaker": bookmaker_id}
        data   = self.get("odds", params, TTL.get("odds", 1.0))
        if not data:
            return {}
        try:
            bets = data["response"][0]["bookmakers"][0]["bets"]
            market = next((b for b in bets if b["name"] == "Match Winner"), None)
            if not market:
                return {}
            values = {v["value"]: float(v["odd"]) for v in market["values"]}
            close = {
                "1": values.get("Home", 0.0),
                "X": values.get("Draw", 0.0),
                "2": values.get("Away", 0.0),
            }
            return {"close": close}
        except Exception:
            return {}

    def sidelined(self, player_id: int) -> list:
        """
        /sidelined — Oyuncunun uzun süreli sakatlık geçmişi.
        Haftalık injury listesinin görmediği sezon boyu sakatlıkları verir.

        Döner:
            [{"player": "Adı Soyadı", "reason": "Knee", "start": "2026-01-10"}]
        """
        params = {"player": player_id}
        data   = self.get("sidelined", params, TTL.get("sidelined", 12.0))
        if not data:
            return []
        result = []
        for item in data.get("response", []):
            player = item.get("player", {}).get("name", "")
            reason = item.get("description", "")
            start  = item.get("start", "")
            result.append({"player": player, "reason": reason, "start": start})
        return result

    def check_coverage(self, league_id: int, season: int) -> dict:
        """
        /leagues — Lig için endpoint kapsamı kontrol et.
        Boşa istek atmayı önler (bazı liglerde statistics/odds kapalı).

        Döner:
            {"fixtures_stats": True, "odds": False, "injuries": True, ...}
        """
        data = self.get("leagues", {"id": league_id, "season": season},
                        TTL.get("leagues", 168.0))
        if not data or not data.get("response"):
            return {}
        try:
            cov = data["response"][0].get("coverage", {})
            fix = cov.get("fixtures", {})
            return {
                "fixtures_stats":  fix.get("statistics_fixtures", False),
                "players_stats":   fix.get("statistics_players", False),
                "lineups":         fix.get("lineups", False),
                "injuries":        cov.get("injuries", False),
                "odds":            cov.get("odds", False),
                "predictions":     cov.get("predictions", False),
            }
        except Exception:
            return {}

    def head_to_head(self, team1_id: int, team2_id: int,
                     last_n: int = 10) -> list:
        """
        /fixtures/headtohead — H2H geçmiş maçlar.

        Döner:
            [{"date":"2024-03-15", "home":"GS", "away":"FB",
              "home_score":2, "away_score":1, "result":"H"}, ...]
        """
        params = {"h2h": f"{team1_id}-{team2_id}", "last": last_n,
                  "status": "FT"}
        data   = self.get("fixtures/headtohead", params, TTL["standings"])
        if not data:
            return []
        results = []
        for item in data.get("response", []):
            fix   = item.get("fixture", {})
            teams = item.get("teams", {})
            goals = item.get("goals", {})
            h_raw = teams.get("home", {}).get("name", "")
            a_raw = teams.get("away", {}).get("name", "")
            h_g   = goals.get("home")
            a_g   = goals.get("away")
            if h_g is None or a_g is None:
                continue
            result = "H" if h_g > a_g else ("D" if h_g == a_g else "A")
            results.append({
                "fixture_id": fix.get("id"),
                "date":       fix.get("date", "")[:10],
                "home":       TEAM_NAME_MAP.get(h_raw, h_raw),
                "away":       TEAM_NAME_MAP.get(a_raw, a_raw),
                "home_score": h_g,
                "away_score": a_g,
                "result":     result,
            })
        return results

    def get_team_id(self, team_name: str, league_id: int,
                    season: int) -> int:
        """
        Takım adından team_id bul — standings üzerinden (daha hızlı).
        """
        standings = self.standings(league_id, season)
        for entry in standings:
            if self._team_match(entry.get("team", ""), team_name):
                return entry.get("team_id", 0)
        return 0

    def lineups(self, fixture_id: int) -> dict:
        """
        /fixtures/lineups — Maçın başlangıç 11'i (maçtan ~1 saat önce açıklanır).

        Döner:
            {
              "home": {
                "formation": "4-3-3",
                "coach": "Okan Buruk",
                "players": [
                  {"id": 123, "name": "İcardi", "pos": "F",
                   "number": 9, "grid": "1:1"},
                  ...
                ]
              },
              "away": { ... }
            }
        """
        params = {"fixture": fixture_id}
        data   = self.get("fixtures/lineups", params, TTL["lineups"])
        if not data:
            return {}

        result: dict = {}
        for idx, team_data in enumerate(data.get("response", [])[:2]):
            side  = "home" if idx == 0 else "away"
            coach = team_data.get("coach", {}).get("name", "")
            players = []
            for entry in team_data.get("startXI", []):
                p = entry.get("player", {})
                players.append({
                    "id":     p.get("id", 0),
                    "name":   p.get("name", ""),
                    "pos":    p.get("pos", ""),
                    "number": p.get("number", 0),
                    "grid":   p.get("grid", ""),
                })
            result[side] = {
                "formation": team_data.get("formation", ""),
                "coach":     coach,
                "players":   players,
            }
        return result

    def topscorers(self, league_id: int, season: int,
                   limit: int = 10) -> list:
        """
        /players/topscorers — Lig gol krallığı listesi.

        Döner:
            [{"player_id": 123, "name": "İcardi",
              "team": "Galatasaray", "team_id": 645,
              "goals": 15, "assists": 7,
              "minutes": 2640, "rating": 7.45}, ...]
        """
        params = {"league": league_id, "season": season}
        data   = self.get("players/topscorers", params, TTL["topscorers"])
        if not data:
            return []

        results = []
        for item in data.get("response", [])[:limit]:
            player = item.get("player", {})
            stats  = (item.get("statistics") or [{}])[0]
            team   = stats.get("team", {})
            goals  = stats.get("goals", {})
            games  = stats.get("games", {})
            results.append({
                "player_id": player.get("id", 0),
                "name":      player.get("name", ""),
                "team":      TEAM_NAME_MAP.get(team.get("name", ""),
                                               team.get("name", "")),
                "team_id":   team.get("id", 0),
                "goals":     goals.get("total") or 0,
                "assists":   goals.get("assists") or 0,
                "minutes":   games.get("minutes") or 0,
                "rating":    float(games.get("rating") or 0),
            })
        return results

    def player_stats(self, team_id: int, league_id: int,
                     season: int) -> list:
        """
        /players — Takımın sezon bazlı oyuncu istatistikleri.
        Gol katkı yüzdesini (goals + assists / takım toplam) hesaplamak için
        kullanılır.

        Döner:
            [{"player_id": 123, "name": "İcardi",
              "goals": 15, "assists": 7, "minutes": 2640,
              "rating": 7.45, "appearances": 28}, ...]
        """
        params = {"team": team_id, "league": league_id, "season": season}
        data   = self.get("players", params, TTL["players"])
        if not data:
            return []

        results = []
        for item in data.get("response", []):
            player = item.get("player", {})
            stats  = (item.get("statistics") or [{}])[0]
            goals  = stats.get("goals", {})
            games  = stats.get("games", {})
            results.append({
                "player_id":   player.get("id", 0),
                "name":        player.get("name", ""),
                "goals":       goals.get("total") or 0,
                "assists":     goals.get("assists") or 0,
                "minutes":     games.get("minutes") or 0,
                "appearances": games.get("appearences") or 0,
                "rating":      float(games.get("rating") or 0),
            })
        return results

    def coaches(self, team_id: int) -> dict:
        """
        /coachs — Takımın güncel teknik direktörü ve göreve başlama tarihi.
        Yeni hoca tespiti için kullanılır (ilk 6 hafta = yüksek belirsizlik).

        Döner:
            {"id": 456, "name": "Okan Buruk",
             "nationality": "Turkey",
             "career_start": "2022-11-07",   ← mevcut görevin başlangıcı
             "is_new": False}                ← son 42 gün içinde atandıysa True
        """
        params = {"team": team_id}
        data   = self.get("coachs", params, TTL["coachs"])
        if not data or not data.get("response"):
            return {}

        try:
            coach = data["response"][0]
            career = coach.get("career", [])
            current_stint = next(
                (c for c in career if c.get("end") is None), {}
            )
            start_str = current_stint.get("start", "")

            is_new = False
            if start_str:
                from datetime import datetime as _dt
                try:
                    start_d = _dt.strptime(start_str[:10], "%Y-%m-%d")
                    days_in_job = (_dt.now() - start_d).days
                    is_new = days_in_job < 42   # 6 hafta
                except ValueError:
                    pass

            return {
                "id":           coach.get("id", 0),
                "name":         coach.get("name", ""),
                "nationality":  coach.get("nationality", ""),
                "career_start": start_str[:10] if start_str else "",
                "is_new":       is_new,
            }
        except Exception:
            return {}

    def transfers(self, team_id: int, season: int = None) -> list:
        """
        /transfers — Takımın son transfer hareketleri.

        Döner:
            [{"player": "İcardi", "type": "in"/"out",
              "date": "2025-08-01", "from_team": "PSG",
              "to_team": "Galatasaray"}, ...]
        """
        params: dict = {"team": team_id}
        if season:
            params["season"] = season
        data = self.get("transfers", params, TTL["transfers"])
        if not data:
            return []

        results = []
        for item in data.get("response", []):
            player = item.get("player", {}).get("name", "")
            for t in item.get("transfers", []):
                teams = t.get("teams", {})
                results.append({
                    "player":    player,
                    "type":      "in"  if teams.get("in",  {}).get("id") == team_id
                                 else "out",
                    "date":      t.get("date", "")[:10],
                    "from_team": teams.get("out", {}).get("name", ""),
                    "to_team":   teams.get("in",  {}).get("name", ""),
                })
        return results


# ── Singleton ─────────────────────────────────────────────────────────────────
_api: Optional[APIFootball] = None


def get_api() -> APIFootball:
    global _api
    if _api is None:
        _api = APIFootball()
    return _api

