"""
SEZON FAZI ANALİZİ
==================
Sezonun hangi fazında olduğuna göre strateji ayarlar.

Faz yapısı (kullanıcı verisi — 31.05.2026):
  ┌─────────────────────────────────────────────────────────┐
  │ Sezon    │ Normal Lig │ Uzama │ Toplam │ Uzama farkı    │
  ├─────────────────────────────────────────────────────────┤
  │ 2022-23  │    46      │   7   │   53   │ Çok uzun       │
  │ 2023-24  │    44      │   6   │   50   │                │
  │ 2024-25  │    43      │   9   │   52   │                │
  │ 2025-26  │    42      │   ?   │  44+   │ Devam ediyor   │
  └─────────────────────────────────────────────────────────┘

4 Faz:
  "start"     → Sezon başı     (Ağu-Eyl, ST1-ST8)
  "middle"    → Sezon ortası   (Eki-Oca, ST9-ST30)
  "end"       → Sezon sonu     (Şub-May, ST31-ST42)
  "extension" → Uzama dönemi   (Haz-Tem, ST43+) — yabancı ligler
"""

from __future__ import annotations
import datetime
from typing import Literal

PhaseKey = Literal["start", "middle", "end", "extension"]


# ─── Faz Tanımları ────────────────────────────────────────────────────────────

PHASE_STATS: dict[PhaseKey, dict] = {
    "start": {
        "label":   "🟢 Sezon Başı (Ağu–Eyl, ST1–ST8)",
        "months":  [8, 9],
        "home":    47.6,
        "draw":    22.4,
        "away":    30.1,
        "avg_x":    2.2,
        "devret_rate": "1/8",
        "notes": [
            "Kadro oturmamış — form verisi güvenilmez",
            "ELO + Oran ağır basar (sezon ağırlığı düşük)",
            "BANKO güvenli — X en az",
            "is_normal_league_week=True (büyük ligler aktif)",
        ],
        "strategy": {
            "banko":             "Normal",
            "double":            "Normal",
            "kaos":              "Normal",
            "x_bias":            "Normal",
            "banko_thr_delta":    0.00,
            "x_bias_delta":       0.00,
            "kaos_spread_mult":   1.00,
            "double_weight":      1.00,
        },
    },
    "middle": {
        "label":   "🟡 Sezon Ortası (Eki–Oca, ST9–ST30)",
        "months":  [10, 11, 12, 1],
        "home":    47.6,
        "draw":    22.4,
        "away":    30.1,
        "avg_x":    2.2,
        "devret_rate": "2/10",
        "notes": [
            "En stabil dönem — form + ELO dengeli",
            "Ev galibiyeti en yüksek",
            "X en az → BANKO'lar en güvenli",
            "⭐ Sistem için altın dönem",
        ],
        "strategy": {
            "banko":             "↑ Artır",
            "double":            "Normal",
            "kaos":              "↓ Azalt",
            "x_bias":            "Düşür",
            "banko_thr_delta":   -0.03,
            "x_bias_delta":      -0.02,
            "kaos_spread_mult":   0.90,
            "double_weight":      0.95,
        },
    },
    "end": {
        "label":   "🔴 Sezon Sonu (Şub–May, ST31–ST42)",
        "months":  [2, 3, 4, 5],
        "home":    42.1,
        "draw":    32.0,
        "away":    25.3,
        "avg_x":    3.5,
        "devret_rate": "4/7",
        "notes": [
            "X oranı %32 — en yüksek dönem",
            "Devret oranı kritik: %57",
            "Küme düşme/şampiyonluk baskısı X'i artırıyor",
            "BANKO sayısını azalt — sadece #12, #14 güvenli",
            "is_normal_league_week=True (büyük ligler aktif)",
        ],
        "strategy": {
            "banko":             "↓ Azalt",
            "double":            "↑ Artır",
            "kaos":              "↑ Artır",
            "x_bias":            "Yükselt",
            "banko_thr_delta":   +0.05,
            "x_bias_delta":      +0.04,
            "kaos_spread_mult":   1.20,
            "double_weight":      1.15,
        },
    },
    "extension": {
        "label":   "🌍 Uzama Dönemi (Haz–Tem, ST43+)",
        "months":  [6, 7],
        "home":    42.1,   # Tahmini — büyük lig verisi yok
        "draw":    21.1,   # Sezon başı fazına benzer (yabancı ligler)
        "away":    36.8,
        "avg_x":    2.5,
        "devret_rate": "3/8",
        "notes": [
            "Büyük Avrupa ligleri bitti — İzlanda, K.Kore, Vietnam, Finlandiya",
            "Sezon istatistikleri GEÇERSİZ — is_normal_league_week=False",
            "Dixon-Coles lambda güvenilmez (veri yok)",
            "K3 ELO: ClubElo bu ligleri bilmez → devre dışı",
            "K9 Injuries: API fixture_id bulunamaz → devre dışı",
            "Tahminler sezon ortasından daha zayıf — KAOS ağırlığı artır",
            f"Ortalama uzama: 6-9 hafta (geçmiş: 7, 6, 9 hafta)",
        ],
        "strategy": {
            "banko":             "↓ Azalt",
            "double":            "↑ Artır",
            "kaos":              "↑↑ Artır",
            "x_bias":            "Normal",
            "banko_thr_delta":   +0.08,   # BANKO çok zorlaştır
            "x_bias_delta":       0.00,   # X bias nötr (yabancı ligler farklı dağılım)
            "kaos_spread_mult":   1.35,   # KAOS alanı genişlet — belirsizlik yüksek
            "double_weight":      1.20,
        },
    },
}

# Ay → Faz eşlemesi
MONTH_TO_PHASE: dict[int, PhaseKey] = {
    1:  "middle",    # Ocak    → sezon ortası devam
    2:  "end",       # Şubat   → sezon sonu başlar
    3:  "end",
    4:  "end",
    5:  "end",       # Mayıs   → sezon sonu (normal lig bitiyor)
    6:  "extension", # Haziran → uzama
    7:  "extension", # Temmuz  → uzama / yeni sezon öncesi
    8:  "start",     # Ağustos → yeni sezon başı
    9:  "start",
    10: "middle",
    11: "middle",
    12: "middle",
}


# ─── Fonksiyonlar ─────────────────────────────────────────────────────────────

def get_current_phase(date: datetime.date | None = None) -> PhaseKey:
    """Tarihe göre sezon fazını döner."""
    if date is None:
        date = datetime.date.today()
    return MONTH_TO_PHASE.get(date.month, "end")


def get_phase_for_week(st_week_no: int, season: str = None) -> PhaseKey:
    """
    ST hafta numarasına göre faz döner.
    Normal lig haftası aşılmışsa → extension.
    """
    try:
        from config import is_normal_league_week
        if not is_normal_league_week(st_week_no, season):
            return "extension"
    except ImportError:
        pass
    return get_current_phase()


def get_phase_stats(phase: PhaseKey | None = None) -> dict:
    """Faz istatistikleri ve strateji ayarları."""
    if phase is None:
        phase = get_current_phase()
    return PHASE_STATS[phase]


def get_phase_adjustments(date: datetime.date | None = None,
                          st_week_no: int = None,
                          season: str = None) -> dict:
    """
    Strateji ayarlarını döner.
    st_week_no verilirse hafta bazlı faz kontrolü de yapılır.
    """
    if st_week_no is not None:
        phase = get_phase_for_week(st_week_no, season)
    else:
        phase = get_current_phase(date)
    return PHASE_STATS[phase]["strategy"]


def get_season_progress(week_number: int, total_weeks: int = None) -> float:
    """
    Sezonun kaçta kaçında olunduğunu döner (0.0 → 1.0).
    total_weeks verilmezse config'den alır.
    """
    if total_weeks is None:
        try:
            from config import get_season_weeks, CURRENT_SEASON
            data = get_season_weeks(CURRENT_SEASON)
            total_weeks = data.get("normal_lig", 42)
        except ImportError:
            total_weeks = 42
    return min(week_number / total_weeks, 1.0)


def is_extension_week(st_week_no: int, season: str = None) -> bool:
    """True ise uzama dönemi — yabancı ligler, zayıf tahmin."""
    return get_phase_for_week(st_week_no, season) == "extension"


def print_phase_hud(date: datetime.date | None = None,
                    st_week_no: int = None,
                    season: str = None) -> None:
    """Pipeline HUD'una sezon fazı bilgisi yazar."""
    if st_week_no is not None:
        phase = get_phase_for_week(st_week_no, season)
    else:
        phase = get_current_phase(date)

    data  = PHASE_STATS[phase]
    strat = data["strategy"]

    if phase == "extension":
        try:
            from config import get_season_weeks, CURRENT_SEASON
            sw = get_season_weeks(season or CURRENT_SEASON)
            nl = sw.get("normal_lig", "?")
            son= sw.get("son_bilinen", "?")
            print(f"\n  📅 SEZON FAZI: {data['label']}")
            print(f"     Normal lig bitti (ST{nl}). Şu an: ST{son}")
        except ImportError:
            print(f"\n  📅 SEZON FAZI: {data['label']}")
    else:
        print(f"\n  📅 SEZON FAZI: {data['label']}")

    print(f"     Tarihsel → 1:%{data['home']:.1f}  X:%{data['draw']:.1f}"
          f"  2:%{data['away']:.1f}  |  Ort.X/hafta:{data['avg_x']:.1f}"
          f"  |  Devret:{data['devret_rate']}")
    print(f"     Strateji → BANKO:{strat['banko']}  ÇİFT:{strat['double']}"
          f"  KAOS:{strat['kaos']}  X-Bias:{strat['x_bias']}")
    for note in data["notes"]:
        print(f"     • {note}")
