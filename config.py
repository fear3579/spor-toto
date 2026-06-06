# -*- coding: utf-8 -*-
"""
Spor Toto AUGUR — Merkezi Konfigürasyon
Tüm sabitler, URL'ler, lig haritası burada.
"""
import os
from datetime import datetime

# ── Otomatik sezon tespiti ───────────────────────────────────────
def _current_season() -> str:
    now = datetime.now()
    y   = now.year
    if now.month >= 8:
        return f"{str(y)[2:]}{str(y+1)[2:]}"
    else:
        return f"{str(y-1)[2:]}{str(y)[2:]}"

def _past_seasons(current: str) -> list:
    y2 = int(current[:2])
    seasons = []
    for i in range(1, 3):   # 3→2: 0.00 ağırlıklı 3. sezon kaldırıldı (boşa indirme)
        s = f"{str(y2-i).zfill(2)}{str(y2-i+1).zfill(2)}"
        seasons.append(s)
    return seasons

CURRENT_SEASON = _current_season()
PAST_SEASONS   = _past_seasons(CURRENT_SEASON)

# ── Spor Toto Sezon Hafta Veritabanı ────────────────────────────────────────
# Kaynak: Kullanıcı verisi (31.05.2026)
# Normal lig haftası = Türkiye Süper Lig + büyük Avrupa ligleri
# Toplam hafta      = Normal + yabancı ligler (İzlanda, K.Kore, vb.)
ST_SEASON_WEEKS = {
    "2223": {
        "normal_lig":  46,   # Süper Lig + Avrupa ligleri
        "toplam":      53,   # Ligler başlayana kadar uzatıldı
        "uzama":        7,   # 53 - 46 = 7 hafta yabancı lig
    },
    "2324": {
        "normal_lig":  44,
        "toplam":      50,
        "uzama":        6,
    },
    "2425": {
        "normal_lig":  43,
        "toplam":      52,
        "uzama":        9,
    },
    "2526": {
        "normal_lig":  42,   # Süper Lig normal lig fazı
        "toplam":      44,   # 2025-2026 sezonu bitti (Haziran 2026)
        "uzama":        2,   # Avrupa uzama haftaları
        "bitti":       True, # Sezon kapandı
    },
    "2627": {
        "normal_lig":  None, # 14 Ağustos 2026'da başlıyor
        "toplam":      None, # Sezon devam edecek
        "uzama":       None,
        "baslangic":  "2026-08-14",
    },
}

def get_season_weeks(season: str = None) -> dict:
    """Sezon hafta verisini döner."""
    s = season or CURRENT_SEASON
    return ST_SEASON_WEEKS.get(s, {})

def is_normal_league_week(st_week_no: int, season: str = None) -> bool:
    """
    Verilen ST hafta numarasının 'normal lig' fazında olup olmadığını döner.
    Normal lig = Türkiye Süper Lig + büyük Avrupa ligleri aktif.
    Normal lig sonrası = Yabancı ligler (İzlanda, K.Kore, Vietnam vb.)
    """
    s    = season or CURRENT_SEASON
    data = ST_SEASON_WEEKS.get(s, {})
    nl   = data.get("normal_lig", 44)
    return st_week_no <= nl

# ST hafta ID'den hafta numarası çıkar
def st_week_number(st_week_id: str) -> int:
    """'ST42-2526' → 42"""
    import re
    m = re.match(r"ST(\d+)", st_week_id or "")
    return int(m.group(1)) if m else 0

# Spor Toto resmi hafta numarası hesaplama
# ST_SEASON_TAG artık CURRENT_SEASON'dan otomatik türetiliyor — manuel güncelleme gerekmez
ST_SEASON_TAG  = CURRENT_SEASON  # _current_season() Ağustos'ta otomatik 2627'ye geçer

# ST_WEEK_OFFSET: ISO hafta → ST hafta numarası dönüşümü
# 2025-2026: ST37 = ISO hafta 1 (offset=36)
# 2026-2027: 14 Ağustos 2026 = ISO hafta 33 → ST1 olacak (offset=-32)
# Ağustos öncesi (2526): offset=36, Ağustos sonrası (2627): offset otomatik sıfırlanır
_now_m = datetime.now().month
_now_y = datetime.now().year
if _now_m >= 8:
    # Yeni sezon — ST1 ISO 33. haftadan başlar (14 Ağustos ~hafta 33)
    ST_WEEK_OFFSET = -32
else:
    # Eski sezon (2526)
    ST_WEEK_OFFSET = 36

def st_week_id(iso_week: int) -> str:
    """ISO hafta numarasından Spor Toto resmi hafta ID üret."""
    st_num = iso_week + ST_WEEK_OFFSET
    return f"ST{st_num}-{ST_SEASON_TAG}"
PAST_SEASON_WEIGHTS = {
    # S-1: Kadro sirkülasyonu var ama temel güç korunur
    PAST_SEASONS[0]: 0.35,
    # S-2: Transfer/TD değişimi etkisi → düşük ağırlık
    PAST_SEASONS[1]: 0.10,
    # S-3 kaldırıldı: ağırlık 0.00 olduğu için PAST_SEASONS listesine de alınmıyor
}


def get_current_season_weight(st_week_number: int) -> float:
    """
    Asimptotik sezon ağırlığı — Katman 1 form verisi için.

    Sezon başında form gürültülüdür → ELO + Oran ağır basar.
    Formül: w = 1 - exp(-0.2 × hafta_no)

    Hafta  1: 0.18  → Katman 1 hafif, ELO/Oran ağır
    Hafta  5: 0.63  → Form devreye giriyor
    Hafta 10: 0.86  → Form güvenilir
    Hafta 42: 1.00  → Sezon sonu, tam ağırlık
    """
    import math
    w = 1.0 - math.exp(-0.20 * max(1, int(st_week_number)))
    return round(min(1.0, max(0.10, w)), 4)


def get_past_season_weight(season_tag: str, st_week_number: int) -> float:
    """
    Geçmiş sezon ağırlığını mevcut hafta sayısına göre ölçekle.

    Sezon başı (hafta 1-5):  geçmiş sezon daha değerli (mevcut veri az)
    Sezon ortası (hafta 10+): geçmiş sezon etkisi hafifçe azalır.

    Formül: base × (1 - get_current_season_weight × 0.5)
    """
    base = PAST_SEASON_WEIGHTS.get(season_tag, 0.0)
    if abs(base) < 1e-9:
        return 0.0
    cur_w  = get_current_season_weight(st_week_number)
    scale  = 1.0 - (cur_w * 0.50)
    return round(base * scale, 4)


# ── Model parametreleri ──────────────────────────────────────────
CFG = {
    "simulations":         50_000,
    "model_weight":        0.65,
    "odds_weight":         0.35,
    "form_games":          6,
    "home_advantage":      1.10,
    "unit_price":          10,
    "max_cols_per_coupon": 2500,
    "banko_threshold":     0.65,
    "tek_threshold":       0.50,
    "double_threshold":    0.40,
    "kaos_spread":         0.10,
    "min_columns":         32,
    "lambda_target":       2.60,
    "fuzzy_cutoff":        0.72,
    # ── Akademik iyileştirmeler ──────────────────────────────────
    # Zaman decay: her maçı exp(-k * gün_farkı) ile ağırlıklandır
    # k=0.007 → ~100 günlük yarı-ömür (literatür standardı)
    "time_decay_k":        0.007,
    # Kelly kriteri: tam Kelly yerine çeyrek Kelly (güvenli)
    "kelly_fraction":      0.25,
    # Shin metodu: vig çıkarırken power exponent (1.0=normal, >1=Shin-like)
    "shin_power":          1.04,
    # Platt kalibrasyon alpha — monte_carlo.calibrate_from_history() tarafından kullanılır
    # 0.15 = hafif düzeltme; artırmak overconfidence'ı daha agresif düzeltir
    "calibration_alpha":   0.15,
}

# ── Football-data URL'leri ───────────────────────────────────────
# Ana ligler: sezon bazlı CSV
FD_URL          = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
# Extra ligler: tek büyük CSV (tüm tarih)
FD_URL_EXTRA    = "https://www.football-data.co.uk/new_leagues/{code}.csv"
FD_FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

# Extra lig kodları — farklı URL ve CSV formatı kullanır
EXTRA_LEAGUES = {
    # Extra ligler kaldırıldı (Spor Toto'da çıkmıyor + URL 404)
    "MEX", "ROU", "IRL", "USA",
}

# ── Cache ayarları ───────────────────────────────────────────────
_PROJECT_DIR   = os.path.dirname(os.path.abspath(__file__))
FD_CACHE_DIR   = os.path.join(_PROJECT_DIR, "fd_cache")
FD_CACHE_TTL_H  = 24
FD_EXTRA_TTL_H  = 72   # Extra ligler daha seyrek güncellenir
FD_FIX_TTL_H    = 6

# ── Ligler ──────────────────────────────────────────────────────
LEAGUES = {
    # ── Ana ligler (mmz4281 URL — sezon bazlı) ───────────────────
    "T1":  "Süper Lig",
    "E0":  "Premier League",
    "D1":  "Bundesliga",
    "I1":  "Serie A",
    "SP1": "La Liga",
    "F1":  "Ligue 1",
    "N1":  "Eredivisie",
    "B1":  "Belgian Pro League",
    "P1":  "Primeira Liga",
    "G1":  "Greek Super League",
    "SC0": "Scottish Premiership",
    # SWE/NOR/JPN/FIN/SWI/DNK/RUS/CHN/POL/AUT kaldırıldı
    # → Spor Toto listesinde çıkmıyor + URL 404
}

# ── Oran kolon öncelikleri (football-data) ───────────────────────
ODDS_COL_SETS = [
    ("B365H", "B365D", "B365A"),
    ("PSH",   "PSD",   "PSA"),
    ("BWH",   "BWD",   "BWA"),
    ("WHH",   "WHD",   "WHA"),
    ("VCH",   "VCD",   "VCA"),
    ("IWH",   "IWD",   "IWA"),
    ("BbMxH", "BbMxD", "BbMxA"),
    ("BbAvH", "BbAvD", "BbAvA"),
    ("SBH",   "SBD",   "SBA"),
    ("GBH",   "GBD",   "GBA"),
    # Extra lig colonları (new_leagues CSV formatı)
    ("MaxH",  "MaxD",  "MaxA"),
    ("AvgH",  "AvgD",  "AvgA"),
]

# Lig bazlı oran önceliği
ODDS_COL_SETS_BY_LEAGUE = {
    # ── Mevcut ana ligler ──────────────────────────────────────────
    "T1":  [("B365H","B365D","B365A"),("BWH","BWD","BWA"),("WHH","WHD","WHA")],
    "E0":  [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    "D1":  [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    "I1":  [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    "SP1": [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    "F1":  [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    # ── Yeni ana ligler ────────────────────────────────────────────
    "N1":  [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    "B1":  [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    "P1":  [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    "G1":  [("B365H","B365D","B365A"),("BWH","BWD","BWA"),("WHH","WHD","WHA")],
    "SC0": [("PSH","PSD","PSA"),("B365H","B365D","B365A"),("BWH","BWD","BWA")],
    # ── Extra ligler — Max/Avg kolonları ───────────────────────────
}

# ── HTTP headers ─────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Accept": "application/json, text/html, */*",
}

# ── Spor Toto API endpoint'leri ──────────────────────────────────
SPORTOTO_API_CANDIDATES = [
    "https://webapi.sportoto.gov.tr/SportToto/GetActiveLists",
    "https://webapi.sportoto.gov.tr/SportToto/GetCurrentList",
    "https://webapi.sportoto.gov.tr/api/SportToto/GetActiveLists",
    "https://webapi.sportoto.gov.tr/api/list/active",
]

# ── Öğrenme parametreleri ────────────────────────────────────────
MIN_SAMPLES = 10

# ── Hafıza dosyaları ────────────────────────────────────────────
# Dosya yolları — çalışma dizininden bağımsız mutlak yol
import os as _os
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
MEMORY_FILE   = _os.path.join(_BASE_DIR, "st_memory.json")
MEMORY_BACKUP = _os.path.join(_BASE_DIR, "st_memory_backup.json")
PRED_LOG_FILE = _os.path.join(_BASE_DIR, "st_predictions.json")
ARCHIVE_FILE  = _os.path.join(_BASE_DIR, "st_arsiv.xlsx")
MEMORY_VERSION = 3

# ── FTR haritası ────────────────────────────────────────────────
FTR_MAP = {"1": "H", "X": "D", "2": "A",
           "H": "H", "D": "D", "A": "A",
           "0": "D"}  # Spor Toto geleneksel kupon: 0 = X = beraberlik

# ── Süper Lig xG Tablosu ─────────────────────────────────────────
T1_XG = {
    "Fenerbahce":        {"xg": 1.90, "xga": 1.11, "luck":  0.05},
    "Besiktas":          {"xg": 1.80, "xga": 1.30, "luck": -0.10},
    "Galatasaray":       {"xg": 1.77, "xga": 1.13, "luck":  0.35},
    "Trabzonspor":       {"xg": 1.64, "xga": 1.41, "luck":  0.95},
    "Istanbul Basaksehir":{"xg":1.50, "xga": 1.36, "luck": -0.15},
    "Goztepe":           {"xg": 1.47, "xga": 1.34, "luck":  0.00},
    "Konyaspor":         {"xg": 1.44, "xga": 1.32, "luck": -0.35},
    "Samsunspor":        {"xg": 1.41, "xga": 1.23, "luck": -0.05},
    "Alanyaspor":        {"xg": 1.37, "xga": 1.24, "luck": -0.35},
    "Gaziantep":         {"xg": 1.37, "xga": 1.57, "luck": -0.10},
    "Caykur Rizespor":   {"xg": 1.34, "xga": 1.52, "luck":  0.15},
    "Kayserispor":       {"xg": 1.27, "xga": 1.62, "luck": -0.10},
    "Fatih Karagumruk":  {"xg": 1.18, "xga": 1.58, "luck": -0.05},
    "Kocaelispor":       {"xg": 1.17, "xga": 1.21, "luck": -0.05},
    "Eyupspor":          {"xg": 1.14, "xga": 1.56, "luck": -0.20},
    "Genclerbirligi":    {"xg": 1.11, "xga": 1.65, "luck":  0.00},
    "Antalyaspor":       {"xg": 1.07, "xga": 1.57, "luck":  0.40},
    "Kasimpasa":         {"xg": 1.07, "xga": 1.35, "luck":  0.30},
}

E0_XG = {
    "Man City":       {"xg": 1.75, "xga": 1.13, "luck": +0.000},
    "Man United":     {"xg": 1.75, "xga": 1.34, "luck": -0.033},
    "Liverpool":      {"xg": 1.75, "xga": 1.29, "luck": -0.233},
    "Ipswich":        {"xg": 1.15, "xga": 1.75, "luck": +0.100},
    "Leicester":      {"xg": 1.20, "xga": 1.68, "luck": +0.067},
    "Arsenal":        {"xg": 1.70, "xga": 0.94, "luck": -0.033},
    "Chelsea":        {"xg": 1.60, "xga": 1.29, "luck": -0.567},
    "Bournemouth":    {"xg": 1.55, "xga": 1.50, "luck": +0.233},
    "Newcastle":      {"xg": 1.55, "xga": 1.39, "luck": -0.367},
    "Brighton":       {"xg": 1.50, "xga": 1.39, "luck": -0.067},
    "Aston Villa":    {"xg": 1.49, "xga": 1.44, "luck": +0.367},
    "Nottm Forest":   {"xg": 1.45, "xga": 1.43, "luck": -0.167},
    "Fulham":         {"xg": 1.39, "xga": 1.39, "luck": +0.133},
    "Tottenham":      {"xg": 1.32, "xga": 1.45, "luck": -0.367},
    "Crystal Palace": {"xg": 1.32, "xga": 1.36, "luck": +0.133},
    "Everton":        {"xg": 1.30, "xga": 1.53, "luck": +0.167},
    "Brentford":      {"xg": 1.27, "xga": 1.47, "luck": +0.567},
    "West Ham":       {"xg": 1.20, "xga": 1.78, "luck": +0.400},
    "Wolves":         {"xg": 1.10, "xga": 1.65, "luck": -0.367},
    "Burnley":        {"xg": 1.08, "xga": 1.84, "luck": +0.167},
}

SP1_XG = {
    "Barcelona":       {"xg": 2.20, "xga": 1.06, "luck": +0.000},
    "Real Madrid":     {"xg": 2.10, "xga": 1.12, "luck": -0.333},
    "Atletico Madrid": {"xg": 1.61, "xga": 1.25, "luck": -0.100},
    "Athletic Bilbao": {"xg": 1.61, "xga": 1.15, "luck": -0.567},
    "Rayo Vallecano":  {"xg": 1.52, "xga": 1.37, "luck": -0.433},
    "Real Betis":      {"xg": 1.57, "xga": 1.42, "luck": +0.033},
    "Real Sociedad":   {"xg": 1.49, "xga": 1.48, "luck": -0.067},
    "Valencia":        {"xg": 1.27, "xga": 1.36, "luck": -0.200},
    "Espanyol":        {"xg": 1.40, "xga": 1.51, "luck": -0.100},
    "Osasuna":         {"xg": 1.31, "xga": 1.46, "luck": -0.033},
    "Sevilla":         {"xg": 1.28, "xga": 1.26, "luck": -0.133},
    "Celta Vigo":      {"xg": 1.28, "xga": 1.40, "luck": +0.267},
    "Alaves":          {"xg": 1.35, "xga": 1.42, "luck": -0.067},
    "Elche":           {"xg": 1.29, "xga": 1.61, "luck": +0.033},
    "Villarreal":      {"xg": 1.38, "xga": 1.49, "luck": +1.000},
    "Getafe":          {"xg": 1.09, "xga": 1.31, "luck": +0.400},
    "Girona":          {"xg": 1.26, "xga": 1.72, "luck": +0.400},
    "Levante":         {"xg": 1.27, "xga": 1.77, "luck": +0.133},
    "Mallorca":        {"xg": 1.21, "xga": 1.69, "luck": +0.433},
    "Real Oviedo":     {"xg": 1.11, "xga": 1.76, "luck": +0.333},
}

D1_XG = {
    "Bayern Munich":      {"xg": 2.32, "xga": 1.06, "luck": +0.000},
    "RB Leipzig":         {"xg": 1.78, "xga": 1.35, "luck": +0.000},
    "Bayer Leverkusen":   {"xg": 1.70, "xga": 1.40, "luck": -0.167},
    "Dortmund":           {"xg": 1.59, "xga": 1.23, "luck": +0.400},
    "Stuttgart":          {"xg": 1.78, "xga": 1.44, "luck": +0.167},
    "Hoffenheim":         {"xg": 1.62, "xga": 1.40, "luck": +0.167},
    "Werder Bremen":      {"xg": 1.48, "xga": 1.55, "luck": -0.600},
    "Freiburg":           {"xg": 1.41, "xga": 1.50, "luck": +0.167},
    "Union Berlin":       {"xg": 1.37, "xga": 1.44, "luck": -0.133},
    "Ein Frankfurt":      {"xg": 1.39, "xga": 1.44, "luck": +0.200},
    "Augsburg":           {"xg": 1.44, "xga": 1.62, "luck": +0.100},
    "St Pauli":           {"xg": 1.21, "xga": 1.47, "luck": -0.200},
    "FC Koln":            {"xg": 1.47, "xga": 1.55, "luck": +0.000},
    "Mainz":              {"xg": 1.36, "xga": 1.58, "luck": +0.200},
    "B Monchengladbach":  {"xg": 1.29, "xga": 1.72, "luck": +0.133},
    "Wolfsburg":          {"xg": 1.31, "xga": 1.93, "luck": +0.000},
    "Hamburger SV":       {"xg": 1.33, "xga": 1.66, "luck": +0.300},
    "Heidenheim":         {"xg": 1.23, "xga": 1.73, "luck": +0.033},
}

I1_XG = {
    "Inter":      {"xg": 1.97, "xga": 1.02, "luck": -0.100},
    "Juventus":   {"xg": 1.88, "xga": 1.12, "luck": -0.367},
    "Como":       {"xg": 1.61, "xga": 1.05, "luck": -0.167},
    "Atalanta":   {"xg": 1.64, "xga": 1.33, "luck": -0.200},
    "Napoli":     {"xg": 1.52, "xga": 1.11, "luck": +0.300},
    "Roma":       {"xg": 1.53, "xga": 1.17, "luck": +0.100},
    "AC Milan":   {"xg": 1.51, "xga": 1.27, "luck": +0.433},
    "Bologna":    {"xg": 1.40, "xga": 1.16, "luck": -0.100},
    "Fiorentina": {"xg": 1.37, "xga": 1.45, "luck": -0.300},
    "Torino":     {"xg": 1.29, "xga": 1.51, "luck": +0.100},
    "Lazio":      {"xg": 1.26, "xga": 1.43, "luck": +0.400},
    "Genoa":      {"xg": 1.30, "xga": 1.44, "luck": +0.133},
    "Parma":      {"xg": 1.16, "xga": 1.58, "luck": +0.167},
    "Verona":     {"xg": 1.25, "xga": 1.40, "luck": -0.500},
    "Udinese":    {"xg": 1.25, "xga": 1.42, "luck": +0.367},
    "Cagliari":   {"xg": 1.10, "xga": 1.50, "luck": +0.100},
    "Pisa":       {"xg": 1.09, "xga": 1.62, "luck": -0.300},
    "Sassuolo":   {"xg": 1.19, "xga": 1.64, "luck": +0.700},
    "Lecce":      {"xg": 1.06, "xga": 1.48, "luck": +0.133},
    "Cremonese":  {"xg": 1.05, "xga": 1.76, "luck": +0.000},
}

F1_XG = {
    "Paris SG":   {"xg": 2.12, "xga": 0.94, "luck": -0.500},
    "Marseille":  {"xg": 1.67, "xga": 1.14, "luck": -0.367},
    "Lille":      {"xg": 1.60, "xga": 1.10, "luck": -0.067},
    "Lens":       {"xg": 1.75, "xga": 1.25, "luck": +0.267},
    "Rennes":     {"xg": 1.59, "xga": 1.40, "luck": +0.167},
    "Lyon":       {"xg": 1.38, "xga": 1.36, "luck": +0.367},
    "Lorient":    {"xg": 1.28, "xga": 1.36, "luck": +0.000},
    "Toulouse":   {"xg": 1.38, "xga": 1.36, "luck": -0.067},
    "Strasbourg": {"xg": 1.35, "xga": 1.35, "luck": +0.167},
    "Monaco":     {"xg": 1.47, "xga": 1.48, "luck": +0.467},
    "Paris FC":   {"xg": 1.27, "xga": 1.43, "luck": +0.133},
    "Le Havre":   {"xg": 1.29, "xga": 1.47, "luck": -0.033},
    "Brest":      {"xg": 1.23, "xga": 1.50, "luck": +0.233},
    "Auxerre":    {"xg": 1.19, "xga": 1.40, "luck": -0.100},
    "Nice":       {"xg": 1.26, "xga": 1.66, "luck": +0.067},
    "Nantes":     {"xg": 1.13, "xga": 1.53, "luck": -0.100},
    "Metz":       {"xg": 1.11, "xga": 1.70, "luck": -0.167},
    "Angers":     {"xg": 1.06, "xga": 1.64, "luck": +0.500},
}

# Yeni ligler için xG — 2024-25 sezonu verileri
N1_XG = {
    "PSV":              {"xg": 2.18, "xga": 0.88, "luck": +0.100},
    "Ajax":             {"xg": 1.85, "xga": 1.10, "luck": -0.100},
    "Feyenoord":        {"xg": 1.78, "xga": 1.12, "luck": +0.050},
    "AZ Alkmaar":       {"xg": 1.62, "xga": 1.18, "luck": +0.150},
    "Twente":           {"xg": 1.48, "xga": 1.25, "luck": -0.050},
    "Utrecht":          {"xg": 1.35, "xga": 1.35, "luck": +0.100},
    "Groningen":        {"xg": 1.25, "xga": 1.42, "luck": -0.100},
    "Heerenveen":       {"xg": 1.22, "xga": 1.45, "luck": +0.050},
    "Almere City":      {"xg": 1.15, "xga": 1.52, "luck": +0.000},
    "NEC Nijmegen":     {"xg": 1.18, "xga": 1.48, "luck": -0.050},
    "Sparta Rotterdam": {"xg": 1.20, "xga": 1.50, "luck": +0.100},
    "Go Ahead Eagles":  {"xg": 1.14, "xga": 1.55, "luck": +0.050},
    "Fortuna Sittard":  {"xg": 1.08, "xga": 1.62, "luck": -0.100},
    "RKC Waalwijk":     {"xg": 1.05, "xga": 1.68, "luck": +0.000},
    "PEC Zwolle":       {"xg": 1.02, "xga": 1.72, "luck": +0.050},
    "Heracles":         {"xg": 1.10, "xga": 1.60, "luck": -0.050},
}

B1_XG = {
    "Club Brugge":      {"xg": 1.95, "xga": 0.95, "luck": +0.100},
    "Anderlecht":       {"xg": 1.72, "xga": 1.15, "luck": -0.050},
    "Gent":             {"xg": 1.60, "xga": 1.20, "luck": +0.100},
    "Union SG":         {"xg": 1.55, "xga": 1.22, "luck": -0.100},
    "Antwerp":          {"xg": 1.45, "xga": 1.30, "luck": +0.050},
    "Standard":         {"xg": 1.35, "xga": 1.40, "luck": -0.050},
    "Westerlo":         {"xg": 1.25, "xga": 1.45, "luck": +0.100},
    "Cercle Brugge":    {"xg": 1.28, "xga": 1.42, "luck": -0.050},
    "Mechelen":         {"xg": 1.20, "xga": 1.48, "luck": +0.000},
    "OHL":              {"xg": 1.15, "xga": 1.52, "luck": +0.050},
    "Genk":             {"xg": 1.42, "xga": 1.35, "luck": +0.150},
    "Sint-Truiden":     {"xg": 1.10, "xga": 1.58, "luck": -0.100},
    "Kortrijk":         {"xg": 1.05, "xga": 1.65, "luck": +0.000},
    "Charleroi":        {"xg": 1.18, "xga": 1.50, "luck": -0.050},
    "Eupen":            {"xg": 1.02, "xga": 1.70, "luck": +0.050},
    "Dender":           {"xg": 0.98, "xga": 1.75, "luck": +0.000},
}

P1_XG = {
    "Benfica":          {"xg": 2.05, "xga": 0.92, "luck": +0.050},
    "Porto":            {"xg": 1.90, "xga": 1.00, "luck": -0.100},
    "Sporting CP":      {"xg": 1.85, "xga": 0.98, "luck": +0.100},
    "Braga":            {"xg": 1.58, "xga": 1.25, "luck": -0.050},
    "Vitoria Guimaraes":{"xg": 1.38, "xga": 1.38, "luck": +0.050},
    "Boavista":         {"xg": 1.22, "xga": 1.45, "luck": -0.050},
    "Famalicao":        {"xg": 1.18, "xga": 1.48, "luck": +0.100},
    "Rio Ave":          {"xg": 1.15, "xga": 1.50, "luck": -0.100},
    "Moreirense":       {"xg": 1.12, "xga": 1.55, "luck": +0.050},
    "Estoril":          {"xg": 1.10, "xga": 1.58, "luck": +0.000},
    "Gil Vicente":      {"xg": 1.08, "xga": 1.60, "luck": -0.050},
    "Arouca":           {"xg": 1.05, "xga": 1.62, "luck": +0.100},
    "Farense":          {"xg": 1.02, "xga": 1.65, "luck": -0.050},
    "Casa Pia":         {"xg": 1.00, "xga": 1.68, "luck": +0.000},
    "Estrela Amadora":  {"xg": 0.98, "xga": 1.72, "luck": +0.050},
    "Nacional":         {"xg": 0.95, "xga": 1.78, "luck": -0.100},
    "Santa Clara":      {"xg": 1.14, "xga": 1.52, "luck": +0.050},
    "AVS":              {"xg": 1.06, "xga": 1.63, "luck": +0.000},
}

G1_XG = {
    "PAOK":             {"xg": 1.88, "xga": 0.98, "luck": +0.100},
    "Olympiacos":       {"xg": 1.75, "xga": 1.05, "luck": -0.050},
    "AEK Athens":       {"xg": 1.65, "xga": 1.15, "luck": +0.050},
    "Panathinaikos":    {"xg": 1.58, "xga": 1.20, "luck": -0.100},
    "Aris":             {"xg": 1.38, "xga": 1.35, "luck": +0.050},
    "Atromitos":        {"xg": 1.25, "xga": 1.42, "luck": -0.050},
    "OFI Crete":        {"xg": 1.18, "xga": 1.50, "luck": +0.100},
    "Panetolikos":      {"xg": 1.12, "xga": 1.55, "luck": -0.050},
    "Volos":            {"xg": 1.10, "xga": 1.58, "luck": +0.000},
    "Asteras Tripolis": {"xg": 1.08, "xga": 1.60, "luck": +0.050},
    "Lamia":            {"xg": 1.05, "xga": 1.65, "luck": -0.100},
    "Levadiakos":       {"xg": 1.02, "xga": 1.68, "luck": +0.000},
    "Ionikos":          {"xg": 1.15, "xga": 1.52, "luck": -0.050},
    "Kallithea":        {"xg": 0.98, "xga": 1.72, "luck": +0.050},
    "Panaitolikos":     {"xg": 1.00, "xga": 1.70, "luck": +0.000},
    "Platanias":        {"xg": 0.95, "xga": 1.78, "luck": +0.050},
}

SC0_XG = {
    "Celtic":           {"xg": 2.10, "xga": 0.85, "luck": +0.050},
    "Rangers":          {"xg": 1.85, "xga": 1.00, "luck": -0.050},
    "Aberdeen":         {"xg": 1.38, "xga": 1.35, "luck": +0.100},
    "Hearts":           {"xg": 1.32, "xga": 1.38, "luck": -0.100},
    "Motherwell":       {"xg": 1.22, "xga": 1.45, "luck": +0.050},
    "Hibernian":        {"xg": 1.25, "xga": 1.42, "luck": -0.050},
    "Kilmarnock":       {"xg": 1.18, "xga": 1.48, "luck": +0.100},
    "St Mirren":        {"xg": 1.12, "xga": 1.52, "luck": -0.050},
    "Dundee Utd":       {"xg": 1.10, "xga": 1.55, "luck": +0.000},
    "St Johnstone":     {"xg": 1.05, "xga": 1.60, "luck": +0.050},
    "Dundee":           {"xg": 1.08, "xga": 1.58, "luck": -0.100},
    "Ross County":      {"xg": 1.02, "xga": 1.65, "luck": +0.000},
}
SWE_XG = {}   # Allsvenskan
NOR_XG = {}   # Eliteserien
JPN_XG = {}   # J1 League
FIN_XG = {}   # Veikkausliiga
SWI_XG = {}   # Swiss Super League
DNK_XG = {}   # Danish Superliga
RUS_XG = {}   # Russian Premier League
CHN_XG = {}   # Chinese Super League
POL_XG = {}   # Polish Ekstraklasa
AUT_XG = {}   # Austrian Bundesliga

# ── Lig bazlı Dixon-Coles rho değerleri ──────────────────────────────────────
# rho = -0.13 literatür standardı (Dixon & Coles 1997)
# Yüksek gollü liglar: rho daha az negatif (daha az düzelt)
# Defansif liglar: rho daha negatif (daha fazla düzelt)
# ARAŞTIRMA GÜNCELLEMESİ (Haziran 2026):
# rho = Dixon-Coles düzeltme parametresi (düşük skorlu maçlar için)
# Değerler opisthokonta.net ve akademik literatür bazlı güncellendi
# (Tam MLE için: poisson_calibrator.py içindeki fit_rho() fonksiyonu)
# Kural: ortalama gol ↑ → |rho| ↓ (düzeltmeye daha az ihtiyaç)
#         ortalama gol ↓ → |rho| ↑ (düzeltmeye daha fazla ihtiyaç)
DIXON_COLES_RHO = {
    "T1":  -0.130,  # Süper Lig        — ort 2.82 gol, standart
    "E0":  -0.115,  # Premier League   — ort 2.85 gol, yüksek tempo
    "D1":  -0.095,  # Bundesliga       — ort 3.24 gol, EN gollü → en az düzelt
    "I1":  -0.150,  # Serie A          — ort 2.63 gol, defansif → fazla düzelt
    "SP1": -0.125,  # La Liga          — ort 2.69 gol, orta
    "F1":  -0.130,  # Ligue 1          — ort 2.60 gol, defansif
    "N1":  -0.110,  # Eredivisie       — ort 3.10 gol, açık oyun
    "B1":  -0.120,  # Belgian Pro Lg   — ort 2.90 gol
    "P1":  -0.135,  # Primeira Liga    — ort 2.55 gol, defansif
    "G1":  -0.145,  # Greek Super Lg   — ort 2.50 gol, defansif
    "SC0": -0.115,  # Scottish Prem    — ort 3.00 gol, açık stil
}
# NOT: poisson_calibrator.py → fit_rho(df, league_code) ile MLE tahmini yapılabilir

# ── Lig bazlı kalibrasyon çarpanları (Fix 4) ───────────────────────────────
# Kaynak: backtest 5.584 maç. Alpha = base_alpha × LEAGUE_CALIB[code]
# Düşük Brier → iyi model → az düzelt (0.80)
# Yüksek Brier → zayıf model → fazla düzelt (1.40)
LEAGUE_CALIB = {
    "T1":  0.80,   # Süper Lig  — Brier=0.1854 ✅ en iyi
    "E0":  1.00,   # Premier Lg — Brier=0.1910 ✅ standart
    "SP1": 0.95,   # La Liga    — Brier=0.1920 ✅ yakın
    "I1":  1.00,   # Serie A    — standart
    "F1":  1.10,   # Ligue 1    — Brier=0.1940 biraz fazla düzelt
    "D1":  1.40,   # Bundesliga — Brier=0.2146 ⚠ en zayıf → çok düzelt
    "N1":  1.05,
    "B1":  1.05,
    "P1":  1.05,
    "G1":  1.10,
    "SC0": 1.05,
}


XG_BY_LEAGUE = {
    "T1":  T1_XG,
    "E0":  E0_XG,
    "SP1": SP1_XG,
    "D1":  D1_XG,
    "I1":  I1_XG,
    "F1":  F1_XG,
    "N1":  N1_XG,
    "B1":  B1_XG,
    "P1":  P1_XG,
    "G1":  G1_XG,
    "SC0": SC0_XG,
}

# ── Pozisyon Bazlı Bias (25 hafta verisi — 294 lig maçı) ──────────────────
# Kaynak: SporToto-sonuclar.docx | Güncelleme: 08.05.2026
# Lambda bias: ev(1) veya dep(2) için çarpan delta
# Draw bias: suggest.py draw_thr için delta (negatif = X kolaylaşır)
POS_BIAS = {
    # DOCX 54 hafta analizi (731 lig maçı)
    # Yüksek X pozisyonlar → draw_thr düşür
    3:  {"draw": -0.037, "note": "X yüksek"},
    8:  {"draw": -0.030, "note": "X yüksek (DOCX)"},
    15: {"draw": -0.020, "note": "X/1 eşit — KAOS"},
    # Dep güçlü
    4:  {"draw": -0.021, "lam_a": +0.030, "note": "Dep güçlü"},
    # BANKO güvenli ev pozisyonlar
    1:  {"lam_h": +0.030, "draw": +0.015, "note": "BANKO güvenli"},
    2:  {"lam_h": +0.030, "draw": +0.015, "note": "BANKO güvenli"},
    5:  {"lam_h": +0.025, "draw": +0.010, "note": "BANKO güvenli"},
    11: {"lam_h": +0.030, "draw": +0.015, "note": "BANKO güvenli"},
    12: {"lam_h": +0.040, "draw": +0.023, "note": "BANKO güvenli"},
    13: {"lam_h": +0.035, "draw": +0.018, "note": "BANKO güvenli"},
    14: {"lam_h": +0.060, "draw": +0.023, "note": "En güvenli BANKO"},
}

# Pozisyon grupları
BANKO_SAFE_POSITIONS = {1, 2, 5, 11, 12, 13, 14}  # DOCX 54 hafta analizi
HIGH_X_POSITIONS     = {3, 8, 15}  # DOCX: 4 dep güçlü
AWAY_STRONG_POSITIONS = {4}  # DOCX: sadece 4 dep güçlü


# ── API-Football Konfigürasyonu ──────────────────────────────────────────────
# API_KEY .env dosyasından okunur — buraya yazmayın!
import os as _os
try:
    # .env yükle
    _env_path = _os.path.join(_os.path.dirname(__file__), ".env")
    if _os.path.exists(_env_path):
        for _line in open(_env_path).readlines():
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                _os.environ.setdefault(_k, _v)
except Exception:
    pass

API_FOOTBALL_KEY = _os.getenv("API_FOOTBALL_KEY", "")

LEAGUE_ID_MAP = {
    "T1":  203, "E0":  39,  "SP1": 140, "I1":  135,
    "D1":   78, "F1":  61,  "N1":   88, "B1":  144,
    "P1":   94, "G1": 197,  "SC0": 179,
}
SEASON_MAP = {"2526": 2025, "2627": 2026, "2425": 2024, "2324": 2023}
