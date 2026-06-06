# -*- coding: utf-8 -*-
"""
tools/setup_training.py — fd_cache → training/ kopyalama scripti

Çalıştır: python tools/setup_training.py

fd_cache/T1_2526.csv  → training/2526/T1.csv
fd_cache/T1_2425.csv  → training/2425/T1.csv
fd_cache/T1_2324.csv  → training/2324/T1.csv
... (11 lig × 3 sezon = 33 dosya)
"""

import os
import shutil

_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FD_CACHE_DIR = os.path.join(_ROOT, "fd_cache")
TRAINING_DIR = os.path.join(_ROOT, "training")

LEAGUES = ["T1","E0","SP1","I1","D1","F1","N1","B1","P1","G1","SC0"]
SEASONS = ["2526","2425","2324"]

def setup():
    print("\n=== training/ klasörü dolduruluyor ===\n")

    copied = 0
    missing = []

    for season in SEASONS:
        season_dir = os.path.join(TRAINING_DIR, season)
        os.makedirs(season_dir, exist_ok=True)

        for league in LEAGUES:
            src = os.path.join(FD_CACHE_DIR, f"{league}_{season}.csv")
            dst = os.path.join(season_dir, f"{league}.csv")

            if os.path.exists(dst):
                print(f"  ✓ {season}/{league}.csv  (zaten var)")
                copied += 1
                continue

            if os.path.exists(src):
                shutil.copy2(src, dst)
                size = os.path.getsize(dst) // 1024
                print(f"  ✅ {season}/{league}.csv  ({size} KB)")
                copied += 1
            else:
                missing.append(f"{league}_{season}.csv")
                print(f"  ✗ {league}_{season}.csv  fd_cache'te yok")

    print(f"\nToplam: {copied}/33 dosya")
    if missing:
        print(f"Eksik ({len(missing)}): {missing}")
        print("\nEksik dosyalar için Menü 6 → Geçmiş Sezonları İndir")
    else:
        print("✅ Tüm dosyalar hazır — Menü B ile eğitim yapılabilir")

if __name__ == "__main__":
    setup()
