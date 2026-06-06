# -*- coding: utf-8 -*-
"""
Cache işlemleri — fd_cache/ yönetimi.
Menü 6 alt fonksiyonları: temizle, indir, durum göster.
"""
import os
import time

from config import (FD_CACHE_DIR, FD_CACHE_TTL_H,
                    LEAGUES, PAST_SEASONS, CURRENT_SEASON)
from data.downloader import (_cache_path, _cache_fresh,
                             _load_pkl, download_league)


def _clear_cache():
    """fd_cache klasorundeki tum pkl dosyalarini sil."""
    if not os.path.exists(FD_CACHE_DIR):
        print("  Cache klasoru yok.")
        return
    count = 0
    for f in os.listdir(FD_CACHE_DIR):
        if f.endswith(".pkl") or f.endswith(".json"):
            try:
                os.remove(os.path.join(FD_CACHE_DIR, f))
                count += 1
            except (OSError, IOError, ValueError, TypeError, KeyError):
                pass
    print(f"  {count} cache dosyasi silindi.")


def _download_past_seasons_menu():
    """
    Menü 6→3: Geçmiş 3 sezonu indir ve cache'e kaydet.
    football-data.co.uk/mmz4281/{sezon}/{kod}.csv
    """
    print("\n" + "═"*58)
    print("  GEÇMİŞ SEZON VERİLERİ İNDİR")
    print("  Oran karşılaştırması için 3 sezon gerekli")
    print("═"*58)

    all_leagues = list(LEAGUES.keys())
    print(f"\n  Ligler: {', '.join(all_leagues)}")
    print(f"  Sezonlar: {', '.join(PAST_SEASONS)}")

    total = len(all_leagues) * len(PAST_SEASONS)
    print(f"\n  Toplam {total} CSV indirilecek (~{total*60}KB)")
    print(f"  VPN aktif olmalı!")
    print(f"\n  Devam? (Enter=Evet, q=İptal): ", end="", flush=True)
    try:
        ans = input().strip().lower()[:1]
        if ans == "q":
            print("  İptal.")
            return
    except (OSError, IOError, ValueError, TypeError, KeyError):
        pass

    ok = 0
    fail = 0
    skip = 0

    for code in all_leagues:
        print(f"\n  [{code}] {LEAGUES.get(code,code)}")
        for season in PAST_SEASONS:
            cache = _cache_path(f"{code}_{season}.pkl")
            if _cache_fresh(cache, FD_CACHE_TTL_H * 30):
                df = _load_pkl(cache)
                if df is not None:
                    print(f"    {season}: cache mevcut ({len(df)} maç) ✓")
                    skip += 1
                    continue
            df = download_league(code, season)
            if df is not None and not df.empty:
                ok += 1
            else:
                fail += 1

    print(f"\n{'═'*58}")
    print(f"  Tamamlandı:")
    print(f"    ✓ İndirilen : {ok}")
    print(f"    ⊙ Zaten vardı: {skip}")
    if fail:
        print(f"    ✗ Başarısız : {fail}")
    print(f"\n  Veriler fd_cache/ klasöründe saklandı.")
    print(f"  Sonraki analizde otomatik kullanılır.")
    print("═"*58)


def _show_cache_status():
    """Cache'deki dosyaları ve boyutlarını göster."""
    print("\n  Cache Durumu (fd_cache/):")
    if not os.path.exists(FD_CACHE_DIR):
        print("  Boş — henüz veri indirilmemiş.")
        return

    files = sorted(os.listdir(FD_CACHE_DIR))
    total_size = 0
    season_counts = {}

    for f in files:
        path = os.path.join(FD_CACHE_DIR, f)
        size = os.path.getsize(path)
        total_size += size
        age_h = (time.time() - os.path.getmtime(path)) / 3600

        df = _load_pkl(path) if f.endswith(".pkl") else None
        rows = len(df) if df is not None else 0

        for season in PAST_SEASONS + [CURRENT_SEASON]:
            if season in f:
                season_counts[season] = season_counts.get(season, 0) + 1

        age_str = f"{age_h:.0f}sa" if age_h < 48 else f"{age_h/24:.0f}g"
        print(f"    {f:<30} {rows:>4} maç  {size//1024:>3}KB  {age_str}")

    print(f"\n  Toplam: {len(files)} dosya, {total_size//1024}KB")

    for season, count in sorted(season_counts.items()):
        name = "Güncel" if season == CURRENT_SEASON else \
               f"20{season[:2]}/20{season[2:]}"
        check = "✓" if count >= 4 else f"⚠ {count}/6"
        print(f"    {name}: {check}")

    try:
        from data.api_football import APIFootball
        _api_s = APIFootball()
        print(f"\n  {_api_s.status()}")
        u = _api_s._get_usage()
        ep = u.get("endpoints", {})
        if ep:
            print("  Endpoint dağılımı:")
            for _ep, _n in sorted(ep.items(), key=lambda x: -x[1])[:6]:
                print(f"    {_ep:<30} {_n} istek")
    except Exception:
        pass
