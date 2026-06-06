# -*- coding: utf-8 -*-
"""
memory/season_transition.py — Ağustos 2026 Sezon Geçiş Scripti
================================================================

Tek seferlik çalıştırılır. Yeni sezon başında:
  1. ST_SEASON_TAG: 2526 → 2627
  2. ST_WEEK_OFFSET güncelle
  3. T1_XG tablosu: promosyon/küme düşen takımlar
  4. st_memory.json sıfırlama (opsiyonel)
  5. Checklist yazır

Çalıştır:
  python memory/season_transition.py
"""

import os, json, sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# ── 2626/27 Sezon Değişiklikleri (Mayıs sonunda güncelle) ──────────────────────
# Spor Toto Süper Lig 2025/26 → 2026/27

# Küme düşenler (25/26 sezonunda) — Ağustos'ta güncelle
RELEGATED_2526 = [
    "Antalyaspor",    # Küme düştü (örnek — kesinleşince güncelle)
    "Genclerbirligi", # Küme düştü (örnek)
    "Kasimpasa",      # Küme düştü (örnek)
]

# Promosyon gelenler (TFF 1. Lig → Süper Lig) — Ağustos'ta güncelle
PROMOTED_2627 = [
    "Adana Demirspor",  # Promosyon (örnek — kesinleşince güncelle)
    "Altay",            # Promosyon (örnek)
    "Boluspor",         # Promosyon (örnek)
]

# Yeni takımlar için XG başlangıç değeri
NEW_TEAM_XG_TEMPLATE = {"xg": 1.20, "xga": 1.50, "luck": 0.00}

# Premier League 25/26 → 26/27 değişiklikleri
RELEGATED_E0_2526 = ["Ipswich", "Leicester", "Southampton"]  # örnek
PROMOTED_E0_2627  = ["Leeds", "Sheffield Utd", "Burnley"]     # örnek


def check_config(dry_run: bool = True) -> list:
    """config.py'deki ST_SEASON_TAG ve XG tablosunu güncelle."""
    config_path = os.path.join(_ROOT, "config.py")
    src = open(config_path, encoding="utf-8").read()

    changes = []

    # ST_SEASON_TAG kontrolü
    if "ST_SEASON_TAG  = \"2526\"" in src:
        changes.append(('ST_SEASON_TAG', '2526', '2627'))
    if "ST_WEEK_OFFSET = 36" in src:
        # 2526 sezon 37-42 arası → 2627 sezon 43'ten başlar
        # Offset: 42 (son hafta) → yeni sezon 43. hafta
        changes.append(('ST_WEEK_OFFSET', '36', '42'))

    # Küme düşenler
    for team in RELEGATED_2526:
        if team in src:
            changes.append(('KALDIRILAN', team, 'T1_XG tablosundan çıkar'))

    # Promosyon
    for team in PROMOTED_2627:
        if team not in src:
            changes.append(('EKLENECEk', team, 'T1_XG tablosuna ekle'))

    return changes


def run_transition(dry_run: bool = True):
    """Sezon geçişini çalıştır."""
    print("\n" + "═"*60)
    print("  AĞUSTOS 2026 — YENİ SEZON GEÇİŞ SCRIPTI")
    print("═"*60)
    print(f"  Mod: {'DRY RUN (değişiklik yok)' if dry_run else 'GERÇEK GEÇİŞ'}")
    print(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    changes = check_config(dry_run)

    print("  ── Tespit Edilen Değişiklikler ──────────────────────")
    for change in changes:
        print(f"  {'[DRY]' if dry_run else '[YAPILDI]'} {change[0]}: {change[1]} → {change[2]}")

    if not changes:
        print("  ✓ config.py zaten güncel")

    if dry_run:
        print("\n  Gerçek geçiş için: python memory/season_transition.py --run")
        return

    # ── Gerçek değişiklikler ───────────────────────────────────
    config_path = os.path.join(_ROOT, "config.py")
    src = open(config_path, encoding="utf-8").read()

    src = src.replace(
        'ST_SEASON_TAG  = "2526"',
        'ST_SEASON_TAG  = "2627"'
    )
    src = src.replace(
        'ST_WEEK_OFFSET = 36',
        'ST_WEEK_OFFSET = 42  # 2627: ST43ten baslar'
    )

    # Küme düşen takımları kaldır
    for team in RELEGATED_2526:
        # XG satırını bul ve kaldır
        lines = src.split("\n")
        new_lines = []
        for line in lines:
            if f'"{team}"' in line and '"xg"' in line:
                print(f"  [KALDIRILDI] {team}")
            else:
                new_lines.append(line)
        src = "\n".join(new_lines)

    # Promosyon takımlarını ekle
    xg_insert = "# YENİ SEZON TAKIMLARI (2627)\n"
    for team in PROMOTED_2627:
        xg_insert += f'    "{team}": {{"xg": 1.20, "xga": 1.50, "luck": 0.00}},\n'
        print(f"  [EKLENDİ] {team}")

    src = src.replace("}\n\nE0_XG", xg_insert + "}\n\nE0_XG")

    open(config_path, "w", encoding="utf-8").write(src)
    print("  ✅ config.py güncellendi")


def print_checklist():
    """Ağustos checklist yazır."""
    print("""
  ── AĞUSTOS 2026 YAPILACAKLAR LİSTESİ ──────────────────────

  OTOMATIK (elle yapmana gerek yok):
  ✅ config.py → _current_season() 1 Ağustos'ta 2627'ye geçer
  ✅ Sezon ağırlıkları kayar: 2526→%35, 2425→%10

  ELLE YAPILACAKLAR:
  □ 1. Süper Lig son durum → küme düşen/promosyon kesinleş
       → memory/season_transition.py'deki listeleri güncelle
  □ 2. python memory/season_transition.py --run
       → config.py otomatik güncellenir
  □ 3. Menü 4 → Cache sil (eski CSV'ler temizlenir)
  □ 4. Menü 6 → Geçmiş sezonları indir (2526 arşive girer)
  □ 5. Menü C → ELO tam güncelle (yeni sezon ELO tarihleri)
  □ 6. Menü B → ML yeniden eğit (yeni 2627 verileriyle)

  st_memory.json KARARI (ikisi de kabul edilebilir):
  □ KORU  → Önerilen: KAOS/BANKO öğrenmeleri korunur
  □ SIFIRLA → Taze başlangıç (Menü 9)

  DİKKAT:
  ⚠ Yeni sezonun ilk 6-8 haftası tahminler zayıf olabilir
  ⚠ Bu dönemde BANKO sayısını azalt, ÇİFT artır
  ⚠ Yeni takımlar için XG değerleri tahmindir

  TAKVİM:
  1 Ağustos    → config.py otomatik 2627 geçişi
  Ağustos ortası → Yeni sezon CSV'leri oluşmaya başlar
  Eylül        → Sistem stabil, tahminler güvenilir
    """)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true",
                        help="Gerçek geçiş yap (dry run olmadan)")
    parser.add_argument("--checklist", action="store_true",
                        help="Yapılacaklar listesini yaz")
    args = parser.parse_args()

    if args.checklist:
        print_checklist()
    elif args.run:
        run_transition(dry_run=False)
    else:
        run_transition(dry_run=True)
        print_checklist()
