# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║         SPOR TOTO — AUGUR ENGINE                            ║
║                                                              ║
║  Kullanım: python main.py                                    ║
╚══════════════════════════════════════════════════════════════╝
"""
import sys, os, re, json, math, time, warnings, argparse, logging
from datetime import datetime
from difflib import SequenceMatcher
import requests
logger = logging.getLogger(__name__)
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")

# Proje kök dizinini path'e ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import *
from data.downloader import (download_league, download_fixtures,
    download_past_seasons, merge_fixture_odds, _cache_path,
    _cache_fresh, _load_pkl, _save_pkl, accumulate_current_season)
from data.odds_history import (build_odds_history, lookup_odds_history,
    lookup_profile)
from input.parser import fetch_weekly_list, _source_file, _source_image_ocr
from input.team_resolver import _normalize, resolve_team, guess_league
from model.team_stats import calc_xg, build_team_stats, get_h2h_stats
from model.lambda_calc import calc_lambda, load_clubelo, get_clubelo
from model.monte_carlo import (monte_carlo, monte_carlo_with_ci, monte_carlo_batch,
    implied_probs, blend_probs, context_adjust, value_check, compute_entropy)
from model.suggest import suggest, disagreement_check as _disagree_check
from coupon.optimizer import budget_optimize, split_coupons
from output.display import print_results, print_coupons
from output.xlsx_export import export_xlsx
from memory.st_memory import STMemory, get_memory
from modules.cache_ops import _clear_cache, _download_past_seasons_menu, _show_cache_status
from modules.results_sync import _auto_results_from_api, _auto_results_from_csv, _sync_results_from_docx
from modules.analysis_menu import (_run_test_center, _run_backtest, _run_backtest_toplu,
                                   _run_lprm_report, _run_lprm_report_toplu,
                                   _run_ab_test, _run_scenario_analysis)

# BÖLÜM 11 — ANA PIPELINE
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# GÜNCELLEME MERKEZİ (Menü 6)
# ═══════════════════════════════════════════════════════════════

def _run_update_center():
    """Menü 6 — Güncelleme Merkezi."""
    R  = "\033[0m"; B = "\033[1m"
    C  = "\033[36m"; G = "\033[32m"; Y = "\033[33m"; DM = "\033[2m"

    while True:
        print()
        print(f"\n  {C}{B}── GÜNCELLEME MERKEZİ {'─'*22}{R}")
        print(f"  {G}{B}1{R}  Güncel Sezon İndir   {DM}(CSV + fixtures){R}")
        print(f"  {Y}{B}2{R}  Güncel Sezon ZORLA   {DM}(cache sıfırla){R}")
        print(f"  {G}{B}3{R}  Geçmiş Sezon İndir   {DM}(oran DB){R}")
        print(f"  {G}{B}4{R}  ELO Tam Güncelleme   {DM}(ClubElo){R}")
        print(f"  {Y}{B}5{R}  Cache Sil            {DM}(tümünü temizle){R}")
        print(f"  {G}{B}6{R}  Cache Durumu         {DM}(yaş + boyut){R}")
        print(f"  {DM}{'─'*40}{R}")
        print(f"  {C}{B}7{R}  ST Geçmiş Veri       {DM}(2223→2526 tüm haftalar){R}")
        print(f"  {C}{B}8{R}  ST Geçmiş Veri Sezon {DM}(tek sezon seç){R}")
        print(f"  {C}{B}9{R}  Pozisyon Bias Güncelle {DM}(matches.csv → model){R}")
        print(f"  {C}{'─'*40}{R}")
        print(f"\n  {DM}Seçim (1-9, M=Geri):{R} ", end="", flush=True)
        try:
            ch = input().strip()[:1].upper()
        except (EOFError, KeyboardInterrupt):
            break

        if ch in ("M", ""):
            break
        if   ch == "1": _download_current_season(force=False)
        elif ch == "2": _download_current_season(force=True)
        elif ch == "3": _download_past_seasons_menu()
        elif ch == "4": _run_elo_full_update()
        elif ch == "5":
            _clear_cache()
            print("  Cache temizlendi. 1 veya 2 ile yeniden indir.")
        elif ch == "6": _show_cache_status()
        elif ch == "7": _run_st_downloader()
        elif ch == "8": _run_st_downloader(ask_season=True)
        elif ch == "9": _run_position_bias_update()

        print(f"\n  {DM}{'─'*38}{R}")
        input("  Enter ile geri dön...")



def _run_st_downloader(ask_season: bool = False):
    """
    Menü 6→7/8 — Spor Toto geçmiş veri indirici.
    sportoto_downloader.py'yi çağırır.
    """
    G = "\033[32m"; Y = "\033[33m"; C = "\033[36m"
    DM = "\033[2m"; R = "\033[0m"; B = "\033[1m"

    base_dir  = os.path.dirname(os.path.abspath(__file__))
    script    = os.path.join(base_dir, "sportoto_downloader.py")

    if not os.path.exists(script):
        print(f"\n  {Y}✗ sportoto_downloader.py bulunamadı!{R}")
        print(f"  Beklenen konum: {script}")
        return

    # Sezon bilgisi
    SEASON_MAP = {
        "1": "2223",   # 2022/2023
        "2": "2324",   # 2023/2024
        "3": "2425",   # 2024/2025
        "4": "2526",   # 2025/2026
    }

    season_arg = ""
    if ask_season:
        print(f"\n{C}{B}  ST Geçmiş Veri — Sezon Seç{R}")
        print(f"  {G}1{R}  2022/2023  {DM}(53 hafta, ID 315-367){R}")
        print(f"  {G}2{R}  2023/2024  {DM}(50 hafta, ID 368-417){R}")
        print(f"  {G}3{R}  2024/2025  {DM}(52 hafta, ID 418-469){R}")
        print(f"  {G}4{R}  2025/2026  {DM}(44+ hafta, ID 470-513+){R}")
        print(f"  {G}5{R}  Tümü       {DM}(~199 hafta, ~4 dakika){R}")
        print(f"\n  Seçim (1-5): ", end="", flush=True)
        try:
            ch = input().strip()[:1]
        except (EOFError, KeyboardInterrupt):
            return

        if ch in SEASON_MAP:
            season_arg = f"--season {SEASON_MAP[ch]}"
        elif ch == "5":
            season_arg = ""
        else:
            return

    # Veri klasörü durumu
    data_dir = os.path.join(base_dir, "sportoto_data")
    raw_dir  = os.path.join(data_dir, "raw")
    cached   = 0
    if os.path.exists(raw_dir):
        cached = len([f for f in os.listdir(raw_dir) if f.endswith(".json")])

    print(f"\n  {'─'*50}")
    print(f"  {C}{B}ST GEÇMİŞ VERİ İNDİRİCİ{R}")
    print(f"  Mevcut cache: {cached} hafta")
    print(f"  {'─'*50}")
    if cached > 0:
        print(f"  {DM}Cache'deki haftalar atlanır, sadece eksikler indirilir.{R}")

    print(f"\n  Başlamak için Enter, iptal için M: ", end="", flush=True)
    try:
        confirm = input().strip().upper()
    except (EOFError, KeyboardInterrupt):
        return
    if confirm == "M":
        return

    # Script'i doğrudan import et ve çalıştır (subprocess yerine)
    import importlib.util as _ilu
    try:
        _spec = _ilu.spec_from_file_location("sportoto_downloader", script)
        _mod  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mod.run(
            season_filter = season_arg.replace("--season ", "") if season_arg else None,
        )
    except Exception as e:
        print(f"  {Y}Hata: {e}{R}")

    # CSV var mı kontrol et
    csv_path = os.path.join(data_dir, "matches.csv")
    if os.path.exists(csv_path):
        size = os.path.getsize(csv_path) / 1024
        print(f"\n  {G}✓ matches.csv hazır ({size:.0f} KB){R}")



def _run_position_bias_update():
    """Menü 6→9 — Pozisyon bias güncelle."""
    G = "\033[32m"; Y = "\033[33m"; C = "\033[36m"
    DM = "\033[2m"; R = "\033[0m"; B = "\033[1m"

    base_dir = os.path.dirname(os.path.abspath(__file__))
    script   = os.path.join(base_dir, "tools", "update_position_bias.py")

    if not os.path.exists(script):
        print(f"\n  {Y}✗ tools/update_position_bias.py bulunamadı!{R}")
        return

    csv_path = os.path.join(base_dir, "sportoto_data", "matches.csv")
    if not os.path.exists(csv_path):
        print(f"\n  {Y}✗ sportoto_data/matches.csv yok — önce Menü 6→7 ile veri indir{R}")
        return

    import importlib.util as _ilu
    try:
        _spec = _ilu.spec_from_file_location("update_position_bias", script)
        _mod  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _mod.run()
        print(f"\n  {G}position_bias_generated.py güncellendi.{R}")
        print(f"  {DM}Bir sonraki Menü 1 analizinde otomatik kullanılır.{R}")
    except Exception as e:
        print(f"  {Y}Hata: {e}{R}")


def _download_current_season(force: bool = False):
    """Güncel sezon CSV + fixtures indir — tüm ligler.
    force=True → cache yaşına bakmadan yeniden indir.
    """
    DM = "\033[2m"; G = "\033[32m"; Y = "\033[33m"; R = "\033[0m"

    print("\n" + "═"*58)
    print("  GÜNCEL SEZON VERİSİ İNDİR")
    print(f"  Sezon: {CURRENT_SEASON}  |  Ligler: {len(LEAGUES)}"
          + (f"  {Y}[ZORLA]{R}" if force else ""))
    print("═"*58)

    ok = fail = skip = 0
    for code, name in LEAGUES.items():
        cache = _cache_path(f"{code}_{CURRENT_SEASON}.pkl")

        # Cache yaşını hesapla
        if os.path.exists(cache):
            age_h = (time.time() - os.path.getmtime(cache)) / 3600
            if age_h < 1:
                age_str = f"{DM}{int(age_h*60)}dk önce{R}"
            elif age_h < 24:
                age_str = f"{DM}{age_h:.1f}sa önce{R}"
            else:
                age_str = f"{Y}{age_h/24:.1f}gün önce{R}"
        else:
            age_str = f"{Y}yok{R}"

        if not force and _cache_fresh(cache, FD_CACHE_TTL_H):
            df = _load_pkl(cache)
            if df is not None and not df.empty:
                print(f"  {G}✓{R} [{code}] {name:<24} {len(df):>3} maç  {age_str}")
                skip += 1
                continue

        print(f"  ↓  [{code}] {name:<24} indiriliyor...", end="", flush=True)
        df = download_league(code, CURRENT_SEASON)
        if df is not None and not df.empty:
            print(f" {G}{len(df)} maç ✓{R}")
            ok += 1
        else:
            print(f" {Y}✗{R}")
            fail += 1

    print(f"\n  Fixtures indiriliyor...", end="", flush=True)
    try:
        fix = download_fixtures()
        if fix is not None and not fix.empty:
            print(f" {G}{len(fix)} fixture ✓{R}")
        else:
            print(f" {Y}✗{R}")
    except Exception as e:
        print(f" {Y}✗ ({e}){R}")

    print(f"\n  ✓ İndirilen: {ok}   ⊙ Atlandı: {skip}", end="")
    if fail: print(f"   ✗ Başarısız: {fail}")
    else: print()
    print("═"*58)


# ═══════════════════════════════════════════════════════════════
# TEST & ANALİZ MERKEZİ (Menü 7) — modules/analysis_menu.py
# ═══════════════════════════════════════════════════════════════






def _human_explain(fd_home: str, fd_away: str,
                    p1: float, px: float, p2: float,
                    label: str,
                    lam_h=None, lam_a=None,
                    lprm_result=None, h2h_pre=None,
                    h_st=None, a_st=None,
                    injuries=None, position=None) -> str:
    """Her maç tahminine doğal dil gerekçe üretir."""
    parts = []
    max_p = max(p1, px, p2)
    if p1 == max_p:
        desc = "güçlü favori" if p1 > 0.60 else "hafif favori"
        parts.append(f"{fd_home[:8]} ev {desc} (P1=%{p1*100:.0f})")
    elif p2 == max_p:
        parts.append(f"{fd_away[:8]} dep favorisi (P2=%{p2*100:.0f})")
    else:
        parts.append(f"Beraberlik baskın (PX=%{px*100:.0f})")

    if lam_h and lam_a:
        diff = round(lam_h - lam_a, 2)
        if diff > 0.30:
            parts.append(f"Ev gol beklentisi yüksek (Δ={diff:+.1f})")
        elif diff < -0.30:
            parts.append(f"Dep gol beklentisi yüksek (Δ={diff:+.1f})")

    if lprm_result:
        score  = lprm_result.get("lprm_score", 0)
        signal = lprm_result.get("main_signal", "")
        conf   = lprm_result.get("confidence", 0)
        if abs(score) > 0.15 and conf > 0.5:
            tag = "Ev" if "EV" in signal else ("Dep" if "DEP" in signal else None)
            if tag:
                parts.append(f"LPRM {tag} form üstün ({score:+.2f})")

    if h2h_pre and isinstance(h2h_pre, dict):
        n   = h2h_pre.get("n", h2h_pre.get("api_n", 0))
        hwr = h2h_pre.get("home_win_rate", h2h_pre.get("api_hwr", None))
        dr  = h2h_pre.get("draw_rate", h2h_pre.get("api_dr", None))
        if n and n >= 3:
            if hwr and hwr > 0.60:
                parts.append(f"H2H ev %{hwr*100:.0f} ({n} maç)")
            elif dr and dr > 0.40:
                parts.append(f"H2H X sık %{dr*100:.0f}")

    if h_st and a_st:
        h_pos = (h_st or {}).get("api_pos", (h_st or {}).get("pos", 0))
        a_pos = (a_st or {}).get("api_pos", (a_st or {}).get("pos", 0))
        if h_pos and a_pos and abs(h_pos - a_pos) >= 5:
            if h_pos < a_pos:
                parts.append(f"Sıralama: #{h_pos} vs #{a_pos}")
            else:
                parts.append(f"Dep sıralama üstün #{a_pos}")

    try:
        from config import HIGH_X_POSITIONS, BANKO_SAFE_POSITIONS
        if position in HIGH_X_POSITIONS:
            parts.append(f"#{position} X sık slot")
        elif position in BANKO_SAFE_POSITIONS:
            parts.append(f"#{position} güvenli slot")
    except Exception:
        pass

    if "BANKO" in label.upper():
        parts.append("→ BANKO")
    elif "KAOS" in label.upper():
        parts.append("→ KAOS")

    return " | ".join(parts) if parts else "—"




def _reset_system():
    """
    Hafıza + Excel sıfırlama.
    fd_cache/ (geçmiş veriler) KORUNUR.
    """
    W = 60
    SEP = "─" * W
    print(f"\n  \033[33m⚠  SİSTEM SIFIRLA  ⚠\033[0m")
    print(f"  {SEP}")
    print("  Silinecek dosyalar:")
    print("    st_memory.json       ← Öğrenme hafızası")
    print("    st_memory_backup.json← Hafıza yedeği")
    print("    st_predictions.json  ← Tahmin geçmişi")
    print("    st_arsiv.xlsx        ← Excel raporları")
    print(f"  {SEP}")
    print("  KORUNACAK:")
    print("    fd_cache/            ← Geçmiş sezon verileri")
    print(f"  {SEP}")
    print("  \033[31mBu işlem GERİ ALINAMAZ!\033[0m")
    print(f"  {SEP}")

    print("\n  Emin misiniz? Devam etmek için EVET yazın: ", end="", flush=True)
    try:
        ans = input().strip().upper()
    except (EOFError, KeyboardInterrupt):
        ans = ""

    if ans != "EVET":
        print("  İptal edildi — hiçbir şey silinmedi.")
        return

    # İkinci onay
    print("\n  SON UYARI: Hafıza tamamen silinecek!")
    print("  Onaylamak için tekrar EVET yazın: ", end="", flush=True)
    try:
        ans2 = input().strip().upper()
    except (EOFError, KeyboardInterrupt):
        ans2 = ""

    if ans2 != "EVET":
        print("  İptal edildi — hiçbir şey silinmedi.")
        return

    # Sil
    targets = [
        MEMORY_FILE,
        MEMORY_BACKUP,
        PRED_LOG_FILE,
        ARCHIVE_FILE,
    ]

    deleted = []
    not_found = []
    for fname in targets:
        if os.path.exists(fname):
            try:
                os.remove(fname)
                deleted.append(fname)
            except (OSError, IOError, ValueError, TypeError, KeyError, RuntimeError) as e:
                print(f"  ✗ {fname} silinemedi: {e}")
        else:
            not_found.append(fname)

    print(f"\n{'─'*60}")
    if deleted:
        print(f"  ✓ Silinen dosyalar:")
        for f in deleted:
            print(f"    {f}")
    if not_found:
        print(f"  ⊙ Zaten yoktu:")
        for f in not_found:
            print(f"    {f}")

    print(f"\n  Sistem sıfırlandı.")
    print(f"  fd_cache/ korundu — verileri yeniden indirmeye gerek yok.")
    print(f"  Bir sonraki Menü 1 çalıştırınca hafıza ve Excel sıfırdan oluşur.")
    print(f"{'─'*60}")


def _menu() -> dict:
    """
    Ana menü — renkli, temiz, alt menüler gizli.
    6 ve 7 seçilince kendi alt menüsü açılır.
    """
    # ── ANSI renk kodları ─────────────────────────────────────
    R  = "\033[0m"       # reset
    B  = "\033[1m"       # bold
    C  = "\033[36m"      # cyan  (başlık)
    G  = "\033[32m"      # green (✓ / seçenek)
    Y  = "\033[33m"      # yellow (durum / hafta)
    DM = "\033[2m"       # dim   (açıklama)
    W  = "\033[37m"      # white

    today_wd  = datetime.now().weekday()
    day_names = ["Pazartesi","Salı","Çarşamba","Perşembe","Cuma","Cumartesi","Pazar"]
    bugun     = day_names[today_wd]

    if today_wd == 4:
        takvim = f"{Y}📋 YENİ LİSTE günü  →  Menü 1{R}"
    elif today_wd == 1:
        takvim = f"{Y}🏆 SONUÇ günü  →  Menü 8{R}"
    elif today_wd in (5, 6, 0):
        takvim = f"{G}⚽ Maçlar devam ediyor{R}"
    else:
        takvim = f"{DM}Sonraki: Cuma (liste){R}"

    # Cache özeti
    cached = []
    if os.path.exists(FD_CACHE_DIR):
        for season in PAST_SEASONS:
            cnt = sum(1 for f in os.listdir(FD_CACHE_DIR)
                      if season in f and f.endswith(".pkl"))
            if cnt > 0:
                cached.append(f"{season}({cnt}L)")
    cur_ok   = os.path.exists(os.path.join(FD_CACHE_DIR, f"T1_{CURRENT_SEASON}.pkl")) \
               if os.path.exists(FD_CACHE_DIR) else False
    cur_icon = f"{G}✓{R}" if cur_ok else f"{Y}⚠{R}"
    past_str = ", ".join(cached) if cached else f"{Y}⚠ yok → Menü 6{R}"

    # Güncel hafta
    _guncel_hafta = ""
    try:
        import json as _jh
        _plf = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "st_predictions.json")
        if os.path.exists(_plf):
            _pd  = _jh.load(open(_plf, encoding="utf-8"))
            def _stw_key(wid):
                _wm2 = re.match(r'ST(\d+)-(\d+)', wid)
                return (int(_wm2.group(2)), int(_wm2.group(1))) if _wm2 else (0, 0)
            _stw = sorted([k for k in _pd if k.startswith("ST")],
                          key=_stw_key, reverse=True)
            if _stw:
                _lw  = _stw[0]
                _wm  = _pd[_lw].get("matches", [])
                _en  = sum(1 for m in _wm if m.get("actual"))
                _tot = len(_wm)
                _guncel_hafta = f"{Y}{_lw}{R}  {DM}({_en}/{_tot} sonuç){R}"
    except Exception:
        pass

    # ── Menü çiz ──────────────────────────────────────────────
    SEP = f"{C}{'─'*52}{R}"

    print()
    print(SEP)
    print(f"  {C}{B}SPOR TOTO  —  AUGUR ENGINE{R}")
    print()
    print(f"  {DM}{bugun}  {datetime.now().strftime('%d.%m.%Y  %H:%M')}{R}")
    print(f"  {takvim}")
    print(f"  Güncel:{cur_icon}  Geçmiş:{past_str}")
    if _guncel_hafta:
        print(f"  Hafta: {_guncel_hafta}")
    print(SEP)
    print(f"  {G}{B}1{R}  Haftalık Analiz    {DM}(Cuma){R}")
    print(f"  {G}{B}2{R}  Sonuçları Gir      {DM}(manuel){R}")
    print(f"  {G}{B}3{R}  Öğrenme Hafızası")
    print(f"  {G}{B}4{R}  Hızlı Mod          {DM}(10k sim){R}")
    print(f"  {G}{B}5{R}  ML Model Eğitimi   {DM}(Ağustos 2026){R}")
    print()
    print(f"  {Y}{B}6{R}  Güncelleme Merkezi")
    print(f"  {Y}{B}7{R}  Test & Analiz Merkezi")
    print()
    print(f"  {G}{B}8{R}  Sonuç Karşılaştır  {DM}(Salı){R}")
    print(f"  {G}{B}9{R}  Sıfırla")
    print(SEP)
    print(f"\n  {DM}Seçim (1-9, Enter=1):{R} ", end="", flush=True)

    sel = "1"
    try:
        line  = input()
        first = line.strip()[:1].upper()
        if first in ("1","2","3","4","5","6","7","8","9"):
            sel = first
    except (EOFError, KeyboardInterrupt):
        sel = "1"

    print(f"  {G}→ {sel}{R}")
    return {
        "sel":    sel,
        "manual": False,
        "file":   None,
        "image":  None,
        "budget": None,
        "sims":   10_000 if sel == "4" else None,
        "save":   False,
    }

_lprm_cache: dict = {}

def _auto_docx_update(mem=None) -> bool:
    """
    tools/ klasöründe SporToto-sonuçlar.docx'i işle:
      - Her zaman: parse et + maç sonuçlarını tahmin loguyla eşleştir
      - Sadece dosya değişmişse: pozisyon istatistiklerini ve
        position_bias_generated.py'yi güncelle
    Döner: True = stats güncellendi, False = değişiklik yok / hata
    """
    import json, sys as _sys
    from pathlib import Path

    tools_dir  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
    stats_json = os.path.join(tools_dir, "spor_toto_stats.json")

    # ── DOCX dosyasını bul + fazladan kopyaları temizle ────
    import unicodedata as _ud
    docx_path = None
    if os.path.isdir(tools_dir):
        candidates = []
        for fname in os.listdir(tools_dir):
            flower = _ud.normalize('NFC', fname).lower()
            if flower.endswith(".docx"):
                score = sum(1 for kw in ("sonu", "spor", "toto") if kw in flower)
                fpath = os.path.join(tools_dir, fname)
                candidates.append((score, os.path.getsize(fpath), fname, fpath))
        if candidates:
            candidates.sort(key=lambda x: (-x[0], -x[1]))
            docx_path = candidates[0][3]
            # Canonical dışındaki tüm .docx dosyalarını sil
            # (bozuk encoding isimli kopyalar, eski yedekler vb.)
            for _, _, extra_name, extra_path in candidates[1:]:
                try:
                    os.remove(extra_path)
                    print(f"  [DOCX] Fazladan kopya silindi: {extra_name}")
                except OSError:
                    pass

    if not docx_path:
        print("  [DOCX] tools/ klasöründe .docx bulunamadı — atlanıyor")
        return False

    # ── DOCX parse et (her zaman — sonuç sync için gerekli) ─
    try:
        if tools_dir not in _sys.path:
            _sys.path.insert(0, tools_dir)
        from parse_spor_toto import parse_file, compute_stats
        from bias_engine import derive_all, compute_diff

        print(f"\n  [DOCX] {os.path.basename(docx_path)} okunuyor...")
        weeks = parse_file(docx_path)
    except ImportError as e:
        pkg = "python-docx" if "docx" in str(e) else str(e)
        print(f"  [DOCX] Paket eksik: {pkg}  →  pip install {pkg}")
        return False
    except Exception as e:
        print(f"  [DOCX] Parse hatası: {e}")
        return False

    if not weeks:
        print("  ⚠ DOCX'ten hiç hafta parse edilemedi — tablo yapısını kontrol et")
        return False

    # ── Maç sonuçlarını tahmin loguyla eşleştir (her zaman) ─
    if mem is not None:
        synced = _sync_results_from_docx(weeks, mem)
        if synced:
            print(f"  [DOCX Sonuç] Toplam {synced} yeni sonuç işlendi")
        else:
            print("  [DOCX Sonuç] Yeni eşleşen sonuç yok")

    # ── İstatistik güncellemesi — sadece dosya değişmişse ───
    docx_mtime  = os.path.getmtime(docx_path)
    stats_mtime = os.path.getmtime(stats_json) if os.path.exists(stats_json) else 0

    if docx_mtime <= stats_mtime:
        print(f"  [DOCX] İstatistikler güncel ✓ (dosya değişmemiş)")
        return False

    # Dosya değişmiş → istatistikleri güncelle
    print("\n" + "═"*60)
    print("  DOCX DEĞİŞİKLİĞİ — İSTATİSTİKLER GÜNCELLENİYOR")
    print("═"*60)

    try:
        new_stats = compute_stats(weeks)
        raw_pos   = new_stats.get("position_distribution", {})
        new_stats["position_distribution"] = {str(k): v for k, v in raw_pos.items()}

        filt = new_stats.get("filtered", {})
        print(f"  {new_stats['total_weeks']} hafta | "
              f"Lig: {filt.get('league', 0)}  "
              f"Milli: {filt.get('milli', 0)}  "
              f"Kupa: {filt.get('kupa', 0)}")

        # Önceki kayıttan çok az hafta parse edildiyse güncelleme yapma
        old_stats_weeks = 0
        if os.path.exists(stats_json):
            try:
                _old = json.loads(Path(stats_json).read_text(encoding="utf-8"))
                old_stats_weeks = _old.get("total_weeks", 0)
            except Exception:
                pass
        if new_stats["total_weeks"] < max(1, old_stats_weeks // 2):
            print(f"  ⚠ Parse sonucu ({new_stats['total_weeks']} hafta) önceki kayıttan "
                  f"({old_stats_weeks} hafta) çok az — istatistik güncellemesi atlandı.")
            return False

        # Katsayı hesapla
        pos_stats = new_stats["position_distribution"]
        derived   = derive_all(pos_stats)
        cats      = derived["categories"]

        # stats.json güncelle (atomik)
        stats_tmp = stats_json + ".tmp"
        Path(stats_tmp).write_text(
            json.dumps(new_stats, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        os.replace(stats_tmp, stats_json)
        print("  spor_toto_stats.json güncellendi ✓")

        # position_bias_generated.py üret
        import importlib.util as _ilu
        _us_path = os.path.join(tools_dir, "update_stats.py")
        _spec    = _ilu.spec_from_file_location("_update_stats_mod", _us_path)
        _us_mod  = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_us_mod)
        _us_mod.write_generated(new_stats, derived)
        print("  position_bias_generated.py güncellendi ✓")

        ds = new_stats.get("devret_stats", {})
        print("\n" + "═"*60)
        print("  ✅ DOCX GÜNCELLEME TAMAMLANDI")
        print("═"*60)
        print(f"  BANKO güvenli pozisyonlar : {sorted(cats.get('banko_safe', []))}")
        print(f"  Yüksek X pozisyonları     : {sorted(cats.get('high_x', []))}")
        print(f"  Deplasman güçlü           : {sorted(cats.get('away_strong', []))}")
        print(f"  Devret X oranı            : %{ds.get('devret_x_rate', 0):.1f}")
        print(f"  Normal X oranı            : %{ds.get('normal_x_rate', 0):.1f}")
        print("═"*60 + "\n")
        return True

    except Exception as e:
        print(f"  [DOCX] İstatistik güncelleme başarısız: {e}")
        return False

def _run_elo_full_update():
    """Menü C — Tarihe Göre ELO Tam Güncelleme."""
    print("\n══════════════════════════════════════════════════════════")
    print("  ELO TAM GÜNCELLEME (ClubElo)")
    print("══════════════════════════════════════════════════════════")

    try:
        from tools.elo_fetcher import EloFetcher
    except ImportError:
        print("  ✗ elo_fetcher.py bulunamadı")
        input("\n  Enter ile devam...")
        return

    fetcher = EloFetcher(verbose=True)
    print(f"  {fetcher.status()}")

    print("\n  ⚠ Bu işlem internete bağlanır ve uzun sürebilir.")
    print("  training/ CSV'lerindeki tüm maç tarihleri indirilecek.")
    onay = input("\n  Devam? (E/h): ").strip().lower()
    if onay not in ("e", "evet", "y", "yes", ""):
        print("  İptal edildi.")
        input("\n  Enter ile devam...")
        return

    n = fetcher.fetch_full()
    print(f"\n  ✅ {n} yeni tarih eklendi → elo_history.json")
    print(f"  {fetcher.status()}")
    print("\n  Artık Menü B → ML Eğitimi yaparken ELO verisi kullanılır.")
    input("\n  Enter ile devam...")


def _run_ml_training(mem):
    """
    Menü B — ML Model Eğitimi.

    Kaynak 1: st_predictions.json (mevcut hafta verileri)
    Kaynak 2: training/ klasörü (3 sezon, ağırlıklı, 30 özellik)
    """
    import json, os
    from model.ml_engine import AugurML, FEATURE_NAMES, MIN_SAMPLES_GB

    print("\n══════════════════════════════════════════════════════════")
    print("  ML MODEL EĞİTİMİ")
    print("══════════════════════════════════════════════════════════")

    ml = AugurML()
    ml.load()
    print(ml.status())

    # ── Kaynak 1: st_predictions.json ────────────────────────
    _root = os.path.dirname(os.path.abspath(__file__))
    pred_file = os.path.join(_root, "st_predictions.json")
    X, y = [], []
    FTR  = {"H": 0, "D": 1, "A": 2, "1": 0, "X": 1, "2": 2, "0": 1}

    try:
        preds = json.load(open(pred_file, encoding="utf-8"))
        for wid, wd in preds.items():
            wno = int(wid.replace("ST","").split("-")[0]) if wid.startswith("ST") else 20
            for m in wd.get("matches", []):
                actual = m.get("actual")
                if not actual or actual not in FTR:
                    continue
                feat = AugurML.build_features(
                    m,
                    position=m.get("no", 8),
                    season_week=wno,
                )
                X.append(feat)
                y.append(FTR[actual])
        print(f"  Kaynak 1 (st_predictions): {len(X)} maç")
    except Exception as e:
        print(f"  ✗ st_predictions.json okunamadı: {e}")

    # ── Kaynak 2: training/ klasörü (ağırlıklı, 30 özellik) ──
    weights_list = []
    try:
        from tools.training_loader import TrainingLoader
        loader = TrainingLoader(verbose=True)
        X2, y2, w2 = loader.load()
        X.extend(X2)
        y.extend(y2)
        weights_list.extend(w2)
        print(f"  Kaynak 2 (training/): {len(X2):,} maç")
    except ImportError as _ie:
        print(f"  ✗ training_loader bulunamadı: {_ie}")
    except Exception as _e:
        print(f"  ✗ training/ yüklenemedi: {_e}")

    n_total = len(X)
    print(f"\n  Toplam veri: {n_total} maç")

    if n_total < MIN_SAMPLES_GB:
        print(f"  ⚠ Yetersiz veri ({n_total}/{MIN_SAMPLES_GB})")
        print(f"  Eğitim Ağustos 2026'da başlayabilir.")
        print(f"  Şu an LPRM aktif — sistem çalışıyor. ✅")
        input("\n  Enter ile devam...")
        return

    # ── Eğit ─────────────────────────────────────────────────
    print("\n  Eğitim başlıyor...")
    # st_predictions maçları için weight=1.0 ekle
    if weights_list and len(weights_list) < len(X):
        n_pred = len(X) - len(weights_list)
        weights_list = [1.0] * n_pred + weights_list
    elif not weights_list:
        weights_list = [1.0] * len(X)

    result = ml.train(X, y, sample_weights=weights_list, verbose=True)
    ml.save()

    print("\n  Sonuçlar:")
    for model in ["lr","gb","mlp","rf"]:
        acc = result.get(f"{model}_acc")
        if acc:
            print(f"    {model.upper()}: %{acc*100:.1f}")
        elif result.get(f"{model}_status"):
            print(f"    {model.upper()}: {result[f'{model}_status']}")

    print("\n  ✅ Model kaydedildi → ml_model.pkl")

    # ── Rezidüel ML eğitimi (yeterli veri varsa) ──────────────
    print("\n  [Rezidüel ML] Kontrol ediliyor...")
    try:
        from model.ml_engine import ResidualML, get_ml
        from tools.training_loader import FEATURE_NAMES
        res_ml  = ResidualML()
        base_ml = get_ml()

        pd_idx = FEATURE_NAMES.index("pos_diff_norm")
        lm_idx = FEATURE_NAMES.index("lm_h")
        sw_idx = FEATURE_NAMES.index("season_week")
        fd_idx = FEATURE_NAMES.index("form_diff")   # 28→15 refaktör: form_h_gf/form_a_gf → form_diff

        X_extra, bp_list, y_res = [], [], []
        for feat, lbl in zip(X, y):
            try:
                x_ex   = [
                    feat[pd_idx],
                    feat[fd_idx],          # form_diff doğrudan kullan
                    feat[pd_idx],
                    0.0, 0.0, 7.0, 7.0, 0.5,
                    feat[lm_idx],
                    feat[sw_idx] / 38.0,
                ]
                bp = base_ml.predict(feat)
                if bp:
                    X_extra.append(x_ex)
                    bp_list.append([bp["p1"], bp["px"], bp["p2"]])
                    y_res.append(lbl)
            except Exception:
                continue

        if len(X_extra) >= ResidualML.MIN_SAMPLES:
            scores = res_ml.train(X_extra, bp_list, y_res, verbose=True)
            res_ml.save()
            print("  ✅ Rezidüel model kaydedildi → residual_model.pkl")
        else:
            needed = ResidualML.MIN_SAMPLES - len(X_extra)
            print(f"  ⏳ Rezidüel: {len(X_extra)}/{ResidualML.MIN_SAMPLES} maç")
            print(f"     {needed} maç daha gerekiyor (Ağustos ~6. hafta)")
    except Exception as _re:
        print(f"  [Rezidüel] Atlandı: {_re}")

    input("\n  Enter ile devam...")

def main():
    # Argparse (Termux) VEYA interaktif menü (Pydroid3)
    # Argparse arg varsa onları kullan, yoksa menü aç
    import sys as _sys
    _now = datetime.now()   # FIX: _now must be defined before use at ~line 1492
    use_menu = len(_sys.argv) == 1   # argüman yoksa menü

    if use_menu:
        opts = _menu()
    else:
        parser = argparse.ArgumentParser(description="Spor Toto Monte Carlo Pipeline")
        parser.add_argument("--manual",  action="store_true")
        parser.add_argument("--file",    type=str, default=None)
        parser.add_argument("--image",   type=str, default=None)
        parser.add_argument("--budget",  type=int, default=None)
        parser.add_argument("--sims",    type=int, default=None)
        parser.add_argument("--save",    action="store_true")
        parser.add_argument("--results",  action="store_true")
        parser.add_argument("--memory",   action="store_true")
        parser.add_argument("--download", action="store_true")
        parser.add_argument("--cache",    action="store_true")
        parser.add_argument("--update",   action="store_true",
                            help="Guncel sezon cek + otomatik sonuc karsilastir")
        a = parser.parse_args()
        sel = "2" if a.results  else \
              "3" if a.memory   else \
              "6" if a.download else \
              "6" if a.cache    else \
              "8" if a.update   else "1"
        opts = {
            "sel": sel, "manual": a.manual, "file": a.file,
            "image": a.image, "budget": a.budget,
            "sims": a.sims, "save": a.save,
        }

    if opts["sims"]:
        CFG["simulations"] = opts["sims"]

    mem = get_memory()

    # ── Menü seçimlerine göre yönlendir ──────────────────────
    if opts["sel"] == "2":
        _entered_week = mem.enter_results()

        # ── Devret bilgisi sor ─────────────────────────────────────
        try:
            log = mem._load_pred_log()
            if _entered_week:
                last_wk = _entered_week
            else:
                def _wk_sort_key(k):
                    _wm = re.match(r'ST(\d+)-(\d+)', k)
                    return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)
                last_wk = sorted(log.keys(), key=_wk_sort_key)[-1] if log else ""
            if last_wk:
                print("\n  15 bilen var mıydı? ", end="")
                print("(sayı gir, 0=devretti, Enter=bilmiyorum): ", end="", flush=True)
                _bilen_inp = input().strip()
                if _bilen_inp.isdigit():
                    _bilen_15 = int(_bilen_inp)
                    mem.record_devret(last_wk, _bilen_15, _bilen_15 == 0)
                    if _bilen_15 == 0:
                        print("  📌 Devret kaydedildi → Sonraki hafta X bias aktif")
                    else:
                        print(f"  ✓ {_bilen_15} kişi 15 bildi → Normal hafta")
        except Exception:
            pass

        return

    if opts["sel"] == "3":
        mem.print_memory_summary()
        return

    # Menü 5 = ML Model Eğitimi (eskiden B)
    if opts["sel"] == "5" and opts.get("sims") is None:
        _run_ml_training(mem)
        return

    # Menü 6 = Güncelleme Merkezi
    if opts["sel"] == "6":
        _run_update_center()
        return

    # Menü 7 = Test & Analiz Merkezi
    if opts["sel"] == "7":
        _run_test_center(mem)
        return

    if opts["sel"] == "8":
        mem = get_memory()
        _auto_docx_update(mem)

        _api_matched = _auto_results_from_api(mem)
        if _api_matched == 0:
            _auto_results_from_csv(mem)
        try:
            from output.xlsx_export import refresh_memory_sheet
            log = mem._load_pred_log()
            for wk_id, wd in log.items():
                if any(m.get("actual") for m in wd.get("matches", [])):
                    refresh_memory_sheet(mem, wk_id, wd["matches"])
            print("  [Excel] st_arsiv.xlsx güncellendi")
        except Exception:
            pass
        return

    if opts["sel"] == "9":
        _reset_system()
        return

    # Geriye kalan eski menü yönlendirmeleri (argparse uyumluluğu)
    if opts["sel"] == "0":
        _run_backtest()
        return
    if opts["sel"] == "A":
        import importlib.util as _ilu
        _analiz_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "analiz.py"
        )
        if os.path.exists(_analiz_path):
            _spec = _ilu.spec_from_file_location("analiz", _analiz_path)
            _mod  = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            if hasattr(_mod, "main"):
                _mod.main()
        return
    if opts["sel"] == "B":
        _run_ml_training(mem)
        return
    if opts["sel"] == "C":
        _run_elo_full_update()
        return
    if opts["sel"] == "D":
        _run_scenario_analysis()
        return

    # Öğrenilmiş eşikleri uygula (sel 1 veya 5)
    banko_thr, double_thr = mem.get_adaptive_thresholds()
    old_banko  = CFG["banko_threshold"]
    old_double = CFG["double_threshold"]
    CFG["banko_threshold"]  = banko_thr
    CFG["double_threshold"] = double_thr
    if banko_thr != old_banko or double_thr != old_double:
        print(f"  [Öğrenme] Eşikler: BANKO>={banko_thr:.2f}  ÇİFT>={double_thr:.2f}")

    # Regime drift guard — son haftalardaki draw oranını CFG'ye geçir
    try:
        _wh = mem.mem.get("weekly_history", [])
        _recent = [h for h in _wh if h.get("status") == "completed"][-5:]
        if _recent:
            _draws = [h.get("actual_draws", 3) / h.get("total", 15) for h in _recent]
            CFG["recent_draw_rate"] = sum(_draws) / len(_draws)
    except Exception:
        pass

    # ── Sezon Fazı & Devret & Yeni Sezon Ayarları ─────────────
    try:
        from model.season_phase  import get_phase_adjustments, print_phase_hud
        from memory.devret_rule  import get_devret_adjustments, print_devret_status
        from memory.season_transition import is_new_season_early

        # Sezon fazı
        phase_adj = get_phase_adjustments()
        print_phase_hud()
        CFG["banko_threshold"]  = max(0.55, CFG["banko_threshold"]
                                      + phase_adj.get("banko_thr_delta", 0))
        CFG["recent_draw_rate"] = CFG.get("recent_draw_rate", 0.27) \
                                   + phase_adj.get("x_bias_delta", 0)
        CFG["kaos_spread"]      = CFG.get("kaos_spread", 0.10) \
                                   * phase_adj.get("kaos_spread_mult", 1.0)

        # Devret hafta
        # ST formatında hafta ID — güncel haftayı bul
        try:
            import json as _jdev
            from config import PRED_LOG_FILE as _plf_dev
            _pd_dev = _jdev.load(open(_plf_dev,encoding="utf-8")) if os.path.exists(_plf_dev) else {}
            def _wk_key(wid):
                _wm = re.match(r'ST(\d+)-(\d+)', wid)
                return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)
            _st_cur = sorted([k for k in _pd_dev if k.startswith("ST")],
                             key=_wk_key, reverse=True)
            _dev_wid = _st_cur[0] if _st_cur else _now.strftime("%G-W%V")
        except Exception:
            _dev_wid = _now.strftime("%G-W%V")
        devret_adj = get_devret_adjustments(mem, _dev_wid)
        print_devret_status(mem, _dev_wid)
        CFG["kaos_spread"]      *= devret_adj.get("kaos_spread_mult", 1.0)
        CFG["recent_draw_rate"] += devret_adj.get("x_bias_boost", 0)
        CFG["banko_threshold"]  += devret_adj.get("banko_thr_boost", 0)

        # Yeni sezon erken hafta uyarısı
        if is_new_season_early():
            print("\n  ⚠ YENİ SEZON — İlk 6-8 hafta: BANKO azalt, ÇİFT artır")
            CFG["banko_threshold"] += 0.05
            CFG["kaos_spread"]     *= 1.10
    except Exception:
        pass  # Modüller yoksa sessizce devam et


    if opts["file"]:
        print(f"\n[ADIM 1] Dosyadan okunuyor: {opts['file']}")
        raw_matches = _source_file(opts["file"])
        if not raw_matches:
            raw_matches = fetch_weekly_list(force_manual=True)
    elif opts["image"]:
        print(f"\n[ADIM 1] Resim OCR: {opts['image']}")
        raw_matches = _source_image_ocr(opts["image"])
        if not raw_matches:
            raw_matches = fetch_weekly_list(force_manual=True)
    else:
        # ── Hafta seçimi & otomatik kaynak ────────────────────────
        G = "\033[32m"; Y = "\033[33m"; C = "\033[36m"
        DM = "\033[2m"; R = "\033[0m"; B = "\033[1m"

        _base       = os.path.dirname(os.path.abspath(__file__))
        _mht_exists = any(
            os.path.exists(os.path.join(_base, n))
            for n in ["spor_toto.mht", "spor_toto.mhtml",
                      "Spor_Toto_Listeler.mht", "sportoto.mht"]
        )

        print()
        print(f"\n  {C}{B}── HAFTALIk LİSTE {'─'*26}{R}")
        if _mht_exists:
            print(f"  {G}{B}1{R}  MHT Dosyasından Oku  {DM}(spor_toto.mht){R}")
        else:
            print(f"  {Y}1{R}  MHT Dosyası          {DM}(bulunamadı){R}")
        print(f"  {G}{B}2{R}  Google Lens Yapıştır {DM}(Ctrl+V){R}")
        print(f"  {G}{B}3{R}  Otomatik Kaynak      {DM}(web + diğer){R}")
        print(f"  {C}{'─'*40}{R}")
        print(f"\n  {DM}Seçim (1-3, Enter=1):{R} ", end="", flush=True)

        try:
            _ch = input().strip()[:1] or "1"
        except (EOFError, KeyboardInterrupt):
            _ch = "1"

        if _ch == "1":
            if _mht_exists:
                print(f"\n[ADIM 1] MHT dosyasından okunuyor...")
                from input.parser import _source_mht
                raw_matches = _source_mht()
                if not raw_matches:
                    print(f"  {Y}MHT parse başarısız → manuel girişe geçiliyor{R}")
                    raw_matches = fetch_weekly_list(force_manual=True)
            else:
                print(f"\n  {Y}spor_toto.mht bulunamadı.{R}")
                print(f"  sportoto.gov.tr → ⋮ → Sayfayı kaydet → spor_toto.mht")
                print(f"  Dosyayı proje kök dizinine koy, tekrar dene.\n")
                raw_matches = fetch_weekly_list(force_manual=True)
        elif _ch == "2":
            print(f"\n[ADIM 1] Manuel giriş modu")
            raw_matches = fetch_weekly_list(force_manual=True)
        else:
            raw_matches = fetch_weekly_list(force_manual=opts["manual"])
    if not raw_matches:
        print("Maç listesi alınamadı.")
        sys.exit(1)

    # ── 2. FİKSTÜR CSV İNDİR (eşleştirme sonra yapılacak) ────
    print("\n[ADIM 2] Fikstur ve acilis oranlari indiriliyor...")
    fixtures_df = download_fixtures()

    # ── 3. LİG VERİSİ (güncel sezon) ─────────────────────────
    print("\n[ADIM 3] Football-data.co.uk — guncel sezon...")
    league_data = {}
    needed_leagues = set()

    for m in raw_matches:
        lg = guess_league(m["home"], m["away"])
        m["league"] = lg
        needed_leagues.add(lg)

    for code in needed_leagues:
        print(f"  → {code} ({LEAGUES.get(code, code)})")
        df = download_league(code, CURRENT_SEASON)
        if df is not None:
            # Güncel sezonu arşive ekle (birikimli CSV)
            accumulate_current_season(code, df)
            df = calc_xg(df)
            st, avg, standings = build_team_stats(df)
            league_data[code] = {
                "df":        df,
                "stats":     st,
                "avg":       avg,
                "standings": standings,
                "teams":     list(st.keys()),
            }

    # ── 3b. FD İSİMLERİ ÇÖZDÜKTEN SONRA FİKSTÜR ORAN EŞLEŞTİR
    # resolve_team ile football-data formatına çevirip maça ekle
    # Sonra merge_fixture_odds fd_home/fd_away ile direkt eşleştirir
    print("\n[ADIM 3b] Fikstur oranlari eslestirilyor (fd isimleri ile)...")
    for m in raw_matches:
        lg = m.get("league","")
        if lg in league_data:
            m["fd_home"] = resolve_team(m["home"], league_data[lg]["teams"])
            m["fd_away"] = resolve_team(m["away"], league_data[lg]["teams"])
        else:
            m["fd_home"] = m["home"]
            m["fd_away"] = m["away"]

    if fixtures_df is not None:
        raw_matches = merge_fixture_odds(raw_matches, fixtures_df, league_data)

    # ── 4. GEÇMİŞ SEZONLAR (oran DB için) ────────────────────
    print("\n[ADIM 4] Gecmis sezonlar (oran karsilastirmasi)...")
    past_data = download_past_seasons(list(needed_leagues))

    # ── 5. TARİHSEL ORAN VERİTABANI ──────────────────────────
    print("\n[ADIM 5] Tarihsel oran DB olusturuluyor...")
    odds_history = build_odds_history(league_data, past_data)

    # ── 5b. CLUBELO ───────────────────────────────────────────
    print("\n[ADIM 5b] ClubElo ELO verileri...")
    clubelo = load_clubelo()

    # xG verisi config.py'deki XG_BY_LEAGUE statik tablosundan
    # lambda_calc._get_xg_data() tarafından otomatik okunur
    if not clubelo:
        print("  ClubElo alinamadi — ic ELO kullanilacak")

    # ── 6. SİMÜLASYON ────────────────────────────────────────
    print(f"\n[ADIM 6] Simulasyon ({CFG['simulations']:,} tekrar)...\n")

    # Hafıza kısıtları — döngü dışında bir kez hesapla
    constraints = mem.get_active_constraints()

    # Momentum bilgisini göster
    momentum_str = mem.get_momentum_info()
    if momentum_str:
        print(f"  📈 Trend: {momentum_str} | "
              f"BANKO eşik: {constraints['banko_threshold']:.2f} | "
              f"Momentum: {constraints['momentum']:+.2f}")

    # Dinamik BANKO eşiğini suggest'e ilet
    _dyn_banko_thr = constraints["banko_threshold"]

    # ── Toplu Fixture ID çekimi (fixtures_batch) ──────────────────────────────
    # 15 ayrı istek yerine 1 batch istekte tüm fixture_id'leri al
    # Pro plan: 7500 istek/gün — batch kritik değil ama verimli
    _fixture_map: dict = {}      # {(fd_home, fd_away): fixture_id}
    _coverage_map: dict = {}     # {league_code: coverage_dict}
    _closing_odds_map: dict = {} # {fixture_id: {"1":x, "X":x, "2":x}}
    try:
        from data.api_football import APIFootball, LEAGUE_ID_MAP, SEASON_MAP
        _api_batch = APIFootball()
        if _api_batch.key:
            # Coverage bilgisi — lig başına bir kez
            _seen_ligs = set()
            for _bm in raw_matches:
                _blg = _bm.get("league", "")
                if _blg in LEAGUE_ID_MAP and _blg not in _seen_ligs:
                    _seen_ligs.add(_blg)
                    _lid = LEAGUE_ID_MAP[_blg]
                    _cov = _api_batch.check_coverage(_lid, SEASON_MAP.get(ST_SEASON_TAG, 2025))
                    if _cov:
                        _coverage_map[_blg] = _cov

            # Fixture ID'leri toplu çek (tarih bazlı)
            _date_str = _now.strftime("%Y-%m-%d")
            _all_fids = []
            for _bm in raw_matches:
                _blg = _bm.get("league", "")
                if _blg not in LEAGUE_ID_MAP:
                    continue
                _bfd_h = _bm.get("fd_home") or _bm.get("home", "")
                _bfd_a = _bm.get("fd_away") or _bm.get("away", "")
                _bdate = _bm.get("date", _date_str)
                _fid = _api_batch.find_fixture_id(
                    _blg, ST_SEASON_TAG, _bfd_h, _bfd_a, _bdate)
                if _fid:
                    _fixture_map[(_bfd_h, _bfd_a)] = _fid
                    _all_fids.append(_fid)

            # Kapanış oranlarını toplu çek (CLV için)
            if _all_fids:
                for _fid in _all_fids:
                    try:
                        _odds_data = _api_batch.odds_prematch(_fid)
                        if _odds_data.get("close"):
                            _closing_odds_map[_fid] = _odds_data["close"]
                    except Exception:
                        pass

            if _fixture_map:
                print(f"  🔗 {len(_fixture_map)}/15 fixture ID bulundu"
                      f" | Kapanış oranı: {len(_closing_odds_map)}")
    except Exception as _bex:
        logger.debug("Batch fixture çekimi atlandı: %s", _bex)

    results = []
    for m in raw_matches:
        lg   = m["league"]
        odds = m.get("odds", {})
        o1   = odds.get("1")
        ox   = odds.get("X")
        o2   = odds.get("2")

        if lg in league_data:
            ld         = league_data[lg]
            fd_home    = m.get("fd_home") or resolve_team(m["home"], ld["teams"])
            fd_away    = m.get("fd_away") or resolve_team(m["away"], ld["teams"])
            standings  = ld["standings"]

            # ── API-Football /standings ile zenginleştir ────────────
            # CSV standings gecikmeli olabilir → API daha güncel
            try:
                from data.api_football import (APIFootball, LEAGUE_ID_MAP,
                                               SEASON_MAP)
                _api_st = APIFootball()
                if _api_st.key and lg in LEAGUE_ID_MAP:
                    _lid = LEAGUE_ID_MAP[lg]
                    _sea = SEASON_MAP.get(ST_SEASON_TAG, 2025)
                    _api_table = _api_st.standings(_lid, _sea)
                    if _api_table:
                        for _entry in _api_table:
                            _tname = _entry.get("team", "")
                            if _tname and _tname in standings:
                                standings[_tname]["api_pos"]  = _entry["rank"]
                                standings[_tname]["api_form"] = _entry.get("form","")
                                standings[_tname]["api_pts"]  = _entry.get("points",0)
                                # API pos geçerli → CSV pos'u güncelle
                                standings[_tname]["pos"] = _entry["rank"]
            except Exception:
                pass   # API standings fallback

            # /teams/statistics -> ev/dep performans
            try:
                from tools.training_loader import TrainingLoader as _TL
                _tst = _TL.fetch_team_stats_api(
                    fd_home, fd_away, lg, ST_SEASON_TAG)
                for _sd, _fd in [("h",fd_home),("a",fd_away)]:
                    _s = standings.setdefault(_fd, {})
                    _ts2 = _tst.get(_sd, {})
                    if _ts2:
                        _s["home_win_rate"]    = _ts2.get("home_win_rate",0)
                        _s["away_win_rate"]    = _ts2.get("away_win_rate",0)
                        _s["btts_rate"]        = _ts2.get("btts_rate",0)
                        _s["clean_sheet_rate"] = _ts2.get("clean_sheet_rate",0)
            except Exception:
                pass
            n_teams    = len(standings) or 18
            # H2H önceden hesapla, lambda'ya da ver
            # H2H: API ile zenginlestir (2015+ tum maclar)
            _api_h2h_d = {}
            try:
                from tools.training_loader import TrainingLoader as _TL2
                _api_h2h_d = _TL2.fetch_h2h_api(
                    fd_home, fd_away, lg, ST_SEASON_TAG)
            except Exception:
                pass
            h2h_pre    = get_h2h_stats(fd_home, fd_away,
                                        ld["df"], last_n=5)
            if _api_h2h_d and isinstance(h2h_pre, dict):
                h2h_pre["api_hwr"] = _api_h2h_d.get("h2h_home_win_rate",0)
                h2h_pre["api_dr"]  = _api_h2h_d.get("h2h_draw_rate",0)
                h2h_pre["api_n"]   = _api_h2h_d.get("n",0)

            # ── LPRM v3 — Bağlamsal Güç Modeli ──────────────────
            # v2 → Spor Toto liste pozisyonu (gürültülü)
            # v3 → Lig sıralama bandı + H2H + güç farkı (daha temiz)
            lprm_result = None
            try:
                from model.lprm_v3 import get_lprm_v3_result

                # Maç tarihi
                _match_date = m.get("date", "")
                if not _match_date:
                    _match_date = _now.strftime("%Y-%m-%d")

                _v3 = get_lprm_v3_result(
                    home        = fd_home,
                    away        = fd_away,
                    league_code = lg,
                    season      = ST_SEASON_TAG,
                    match_date  = _match_date,
                    past_seasons= ["2425", "2324"],
                )

                if _v3 and _v3.get("lprm_score") is not None:
                    # v3 → v2 formatına adapt et (lambda_calc uyumlu)
                    _score   = _v3["lprm_score"]
                    _conf    = _v3.get("confidence", 0.5)
                    _detail  = _v3.get("detail", {})
                    _warns   = _detail.get("warnings", [])

                    # main_signal: v3'ten türet
                    if _score > 0.15:
                        _signal = "EV_GÜÇLÜ"
                    elif _score < -0.15:
                        _signal = "DEP_GÜÇLÜ"
                    else:
                        _signal = "NÖTR"

                    lprm_result = {
                        "lprm_score":   _score,
                        "lambda_adj_h": _v3["lambda_adj_h"],
                        "lambda_adj_a": _v3["lambda_adj_a"],
                        "main_signal":  _signal,
                        "warnings":     _warns,
                        "confidence":   _conf,
                    }
                    m["lprm"] = {
                        "score":    _score,
                        "signal":   _signal,
                        "warnings": _warns,
                        "conf":     round(_conf, 2),
                        "ver":      "v3",
                    }
            except Exception as _lprm_e:
                # v3 başarısız → v2 fallback
                try:
                    from model.lprm import LPRMEngine
                    _lprm_key = f"_lprm_{lg}"
                    if _lprm_key not in _lprm_cache:
                        _lprm_cache[_lprm_key] = LPRMEngine(ld["df"], min_n=4)
                    lprm_eng = _lprm_cache[_lprm_key]
                    h_st  = standings.get(fd_home, {})
                    a_st  = standings.get(fd_away, {})
                    h_pos = h_st.get("pos", n_teams // 2)
                    a_pos = a_st.get("pos", n_teams // 2)
                    h_pts = h_st.get("pts", 30)
                    lprm_result = lprm_eng.analyze(
                        home=fd_home, away=fd_away, odds_h=o1,
                        home_pos=h_pos, away_pos=a_pos,
                        n_teams=n_teams, home_pts=h_pts,
                        home_xpts=h_pts*0.92, week=m.get("week_no",25),
                    )
                    if lprm_result:
                        m["lprm"] = {
                            "score":    lprm_result["lprm_score"],
                            "signal":   lprm_result["main_signal"],
                            "warnings": lprm_result["warnings"],
                            "ver":      "v2_fallback",
                        }
                except Exception:
                    pass

            # ── Bağlam değişkenleri — Katman 7 + Katman 8 için ──
            _pos_no      = m.get("no", 8)
            _season_week = m.get("week_no", 25)
            _devret_on   = False
            try:
                _devret_on = bool(devret_adj.get("devret_haftasi", False))
            except Exception:
                pass

            # ELO farkı — clubelo varsa hesapla
            _elo_diff = 0.0
            try:
                _eh = get_clubelo(fd_home, clubelo)
                _ea = get_clubelo(fd_away, clubelo)
                if _eh != 1500.0 or _ea != 1500.0:
                    _elo_diff = (_eh - _ea) / 400.0
            except Exception:
                pass

            # Lig draw rate
            _lg_draw = 0.265
            try:
                _lg_draw = ld.get("draw_rate", 0.265)
            except Exception:
                pass

            # Fixture ID — önce batch map'ten, yoksa tekil çek
            _fixture_id = _fixture_map.get((fd_home, fd_away))
            if _fixture_id is None:
                try:
                    from data.api_football import APIFootball
                    _api_fi = APIFootball()
                    if _api_fi.key:
                        _date_str = m.get("date", _now.strftime("%Y-%m-%d"))
                        _fixture_id = _api_fi.find_fixture_id(
                            lg, ST_SEASON_TAG, fd_home, fd_away, _date_str)
                        if _fixture_id:
                            _fixture_map[(fd_home, fd_away)] = _fixture_id
                except Exception:
                    pass

            lam_h, lam_a = calc_lambda(
                fd_home, fd_away,
                ld["stats"], ld["avg"],
                clubelo, h2h_pre,
                league_code      = lg,
                lprm_result      = lprm_result,
                position         = _pos_no,
                season_week      = _season_week,
                devret           = _devret_on,
                league_draw_rate = _lg_draw,
                elo_diff         = _elo_diff,
                fixture_id       = _fixture_id,
            )
            matched    = f"{fd_home} / {fd_away}"
        else:
            lam_h, lam_a = 1.30, 1.10
            fd_home = fd_away = ""
            standings = {}
            n_teams   = 18
            matched   = "(varsayılan λ)"
            h2h_pre   = None
            lprm_result = None

        p1, px, p2, ci_width = monte_carlo_with_ci(lam_h, lam_a)
        imp = implied_probs(o1, ox, o2)

        # Açılış/Kapanış oran delta (piyasa hareketi sinyali)
        odds_delta = 1.0
        _o1_open = m.get("odds_open", {}).get("1")
        if _o1_open and o1:
            try:
                odds_delta = float(_o1_open) / float(o1)
            except (ValueError, ZeroDivisionError):
                pass

        # Dinamik blend: delta sinyali dahil
        odds_quality = 1.0 if (o1 is not None) else 0.0
        fp1, fpx, fp2 = blend_probs((p1, px, p2), imp, odds_quality, odds_delta)

        # Platt Kalibrasyon — Brier geçmişinden overconfidence düzelt
        try:
            from model.monte_carlo import calibrate_from_history
            _wh     = mem.mem.get("weekly_history", [])
            _briers = [h["brier"] for h in _wh
                       if h.get("brier") and h.get("status") == "completed"]
            _avg_b  = sum(_briers) / len(_briers) if _briers else None
            fp1, fpx, fp2 = calibrate_from_history(fp1, fpx, fp2, _avg_b, league_code=lg)  # Fix 4
        except Exception:
            pass

        # GELİŞTİRME 2: Oran yoksa CI cezası → daha geniş seçim
        if o1 is None:
            ci_width = ci_width * (1.0 + constraints.get("ci_penalty", 0.15))

        # Tarihsel oran kalibrasyonu (%12 ağırlık)
        hist = lookup_odds_history(o1, ox, o2, odds_history)
        if hist:
            hw = 0.12
            fp1 = fp1*(1-hw) + hist[0]*hw
            fpx = fpx*(1-hw) + hist[1]*hw
            fp2 = fp2*(1-hw) + hist[2]*hw
            t   = fp1 + fpx + fp2
            fp1, fpx, fp2 = fp1/t, fpx/t, fp2/t

        # Takım hafızası sapma düzeltmesi
        fp1, fpx, fp2 = mem.apply_team_bias(
            fd_home, fd_away, fp1, fpx, fp2
        )

        # GELİŞTİRME 3: Güçlü takım bias'ı (>%15 sapma varsa)
        fp1, fpx, fp2 = mem.get_team_strong_bias(
            fd_home, fd_away, fp1, fpx, fp2
        )

        # Bağlam düzeltmesi
        fp1, fpx, fp2 = context_adjust(
            fp1, fpx, fp2,
            fd_home, fd_away,
            standings, n_teams
        )

        # Value bet tespiti — suggest'ten ÖNCE hesapla
        val = value_check((fp1, fpx, fp2), imp, min_edge=0.06)

        # Entropy hesapla
        entropy = compute_entropy(fp1, fpx, fp2)

        # KAOS → X tercihi aktifse value_info'ya X zorla
        if constraints["kaos_prefer_x"] and entropy > 1.00:
            # X en az %25 ise ÇİFT'e ekle
            if fpx >= 0.25:
                val = dict(val) if val else {}
                val["has_value"]  = True
                val["outcome"]    = "X"
                val["edge"]       = 0.09  # zorla tetikle

        # Suggest — CI + value + draw boost parametreleriyle
        # LPRM draw sinyali
        _lprm_draw = False
        if lprm_result:
            # v2 formatında layers.odds.signal, v3 formatında main_signal
            _l2 = lprm_result.get("layers", {}).get("odds", {})
            if _l2.get("signal") in ("kilitleme", "draw_magnet"):
                _lprm_draw = True
            if lprm_result.get("main_signal") == "DEP_GÜÇLÜ":
                _lprm_draw = True  # v3: deplasman güçlü → beraberlik eğilimi
            if lprm_result.get("lprm_score", 0) < -0.15:
                _lprm_draw = True  # her iki format: negatif skor → dep/draw

        # Lambda farkı (denge sinyali)
        _lam_diff = abs(lam_h - lam_a) if lam_h and lam_a else None

        label, mul, is_kaos = suggest(fp1, fpx, fp2,
                                      value_info=val,
                                      ci_width=ci_width,
                                      banko_threshold=_dyn_banko_thr,
                                      entropy=entropy,
                                      lprm_draw_signal=_lprm_draw,
                                      position=m.get("no"),
                                      lambda_diff=_lam_diff)

        # ── CLV Kaydı ─────────────────────────────────────────────────────
        # Açılış oranı şimdi, kapanış oranı batch'ten (varsa)
        # Sonuç Menü 2'de girilince update_outcome() ile tamamlanır
        if _fixture_id and o1 is not None:
            try:
                from memory.clv_tracker import get_clv_tracker
                _sel_for_clv = label.split()[-1] if label else "?"
                _close = _closing_odds_map.get(_fixture_id, {})
                _close_o1 = _close.get("1") or o1   # kapanış yoksa açılış
                get_clv_tracker().record(
                    week_id    = week_id if "week_id" in locals() else "",
                    match_no   = m.get("no", 0),
                    match_name = f"{m.get('home','')} - {m.get('away','')}",
                    selection  = _sel_for_clv,
                    model_p    = fp1 if _sel_for_clv == "1" else
                                 (fpx if _sel_for_clv == "X" else fp2),
                    opening_odds = float(o1),
                    closing_odds = float(_close_o1),
                    league       = lg,
                )
            except Exception:
                pass

        # API /predictions disagreement → KAOS_API sinyali
        if _fixture_id:
            try:
                from model.suggest import disagreement_check
                _dsig = disagreement_check(fp1, fpx, fp2, _fixture_id)
                if _dsig == "KAOS_API" and not is_kaos:
                    label = "KAOS  1X2"; mul = 3; is_kaos = True
                    m["api_disagree"] = True
            except Exception:
                pass

        try:
            m["explain"] = _human_explain(
                fd_home, fd_away, fp1, fpx, fp2, label,
                lam_h=lam_h, lam_a=lam_a,
                lprm_result=lprm_result,
                h2h_pre=h2h_pre,
                h_st=standings.get(fd_home,{}),
                a_st=standings.get(fd_away,{}),
                position=m.get("no"),
            )
        except Exception:
            m["explain"] = ""

        # GELİŞTİRME 1b: Bağlam BANKO kısıtı
        # Hafıza bu bağlamda %45 altındaysa BANKO → TEK
        # NOT: h_info/a_info henüz tanımlı değil, standings'den direkt bak
        _h = standings.get(fd_home, {})
        _a = standings.get(fd_away, {})
        ctx_temp = ""
        if _h and _a:
            N = n_teams
            if _h.get("rank",99)/N <= 0.25 and _a.get("rank",99)/N <= 0.25:
                ctx_temp = "ZIRVE"
            elif _h.get("rank",99)/N >= 0.75 or _a.get("rank",99)/N >= 0.75:
                ctx_temp = "DUSME"
            else:
                ctx_temp = "NONE"

        if label.startswith("BANKO") and ctx_temp in constraints["no_banko_ctx"]:
            best = max({"1":fp1,"X":fpx,"2":fp2}, key=lambda k:{"1":fp1,"X":fpx,"2":fp2}[k])
            label    = f"TEK   {best}"
            mul      = 1
            is_kaos  = False

        # Bağlam etiketi
        h_info  = standings.get(fd_home, {})
        a_info  = standings.get(fd_away, {})
        ctx_tag = ""
        if h_info and a_info:
            N = n_teams
            _hr = h_info.get("rank", 99)
            _ar = a_info.get("rank", 99)
            if _hr / N <= 0.25 and _ar / N <= 0.25:
                ctx_tag = "[ZIRVE]"
            elif _hr / N >= 0.75 or _ar / N >= 0.75:
                ctx_tag = "[DUSME]"

        # H2H son 5 maç (lambda'da zaten kullanıldı, gösterim için de sakla)
        h2h_stats = h2h_pre

        # Profil istatistiği
        profile_info = None
        o1r = m.get("odds",{}).get("1")
        oxr = m.get("odds",{}).get("X")
        o2r = m.get("odds",{}).get("2")
        if o1r and h_info and a_info:
            profile_info = lookup_profile(
                o1r, oxr, o2r, "ev",
                h_info.get("rank_pct", 0.5),
                a_info.get("rank_pct", 0.5),
                odds_history
            )

        # Seri bilgisi
        streak_h   = mem.get_streak_info(fd_home)
        streak_a   = mem.get_streak_info(fd_away)
        streak_tag = ""
        if streak_h: streak_tag += streak_h
        if streak_a: streak_tag += ("/" if streak_h else "") + streak_a

        results.append({
            "no":       m["no"],
            "mac":      f"{m['home'][:14]}-{m['away'][:14]}",
            "lH":       round(lam_h, 2),
            "lA":       round(lam_a, 2),
            "P1":       round(fp1 * 100, 1),
            "PX":       round(fpx * 100, 1),
            "P2":       round(fp2 * 100, 1),
            "oneri":    label,
            "mul":      mul,
            "fd_match": matched,
            "ctx":      ctx_tag,
            "streak":   streak_tag,
            "is_kaos":  is_kaos,
            "profile":  profile_info,
            "value":    val,
            "entropy":  entropy,
            "ci_width": round(ci_width, 4),
            "h2h":      h2h_stats,
            "lprm":     m.get("lprm"),
        })


    # ── 4. ÇIKTI ─────────────────────────────────────────────
    total_cols, cost = print_results(results)

    # ── 5. BÜTÇE + KUPON PLANI ───────────────────────────────
    print("\n" + "═"*70)
    print("  BÜTÇE PLANI")
    print("═"*70)
    print(f"\n  Ham toplam: {total_cols:,} kolon = {cost:,} TL")
    print(f"\n  Bütçenizi girin (TL, Enter = 100): ", end="", flush=True)
    try:
        raw_b = input().strip()
        raw_b = re.sub(r'[Tt][Ll]', '', raw_b).strip()
        user_budget = int(raw_b) if raw_b.isdigit() and int(raw_b) > 0 else 100
    except (OSError, IOError, ValueError, TypeError, KeyError):
        user_budget = 100

    # Ham kolon sayısını hesapla (optimize edilmemiş)
    raw_cols = 1
    for r in results: raw_cols *= r["mul"]
    raw_cost = raw_cols * CFG["unit_price"]

    # Bütçe kademelerini akıllıca belirle
    # A = kullanıcı bütçesi
    # B = kuponu mantıklı tutacak minimum (ham'ın ~%1'i)
    # C = tam kapsama (~%3)
    smart_b = max(user_budget * 2, int(raw_cost * 0.003 / 10) * 10)
    smart_c = max(user_budget * 5, int(raw_cost * 0.010 / 10) * 10)

    budgets_abc = {
        "A": user_budget,
        "B": smart_b,
        "C": smart_c,
    }

    # Her bütçe için optimizasyon hesapla
    abc = {}
    for letter, budget in budgets_abc.items():
        opt, steps = budget_optimize(results, budget)
        cols = 1
        for r in opt: cols *= r["mul"]
        abc[letter] = {
            "results": opt,
            "cols":    cols,
            "cost":    cols * CFG["unit_price"],
            "budget":  budget,
            "steps":   steps,
        }

    # ── Özet satırı ──
    W = 70
    MAX_COLS = CFG["max_cols_per_coupon"]
    print(f"\n{'─'*W}")
    print(f"  {'SEÇ':<4}  {'KOLON':>7}  {'MALİYET':>10}  {'DURUM'}")
    print(f"{'─'*W}")
    for letter, d in abc.items():
        cols = d["cols"]
        cost = d["cost"]
        if cols > MAX_COLS:
            ok = f"✗ Limit aşıldı ({cols:,} > {MAX_COLS:,})"
        else:
            ok = "✓ Sığıyor"
        print(f"  [{letter}]   {cols:>7,} kolon  {cost:>9,} TL  {ok}")
    print(f"{'─'*W}")
    print(f"  (Spor Toto limiti: max {MAX_COLS:,} kolon = {MAX_COLS*10:,} TL)")

    # ── Her seçenek için detay tablosu ──
    for letter, d in abc.items():
        opt    = d["results"]
        cols   = d["cols"]
        cost_b = d["cost"]
        budget = d["budget"]

        print(f"\n  ┌── KUPON {letter}  ({budget:,} TL hedef → {cols} kolon = {cost_b:,} TL) ─")

        for r in opt:
            lbl    = r["oneri"]
            ctx    = r.get("ctx","")
            marker = "★" if lbl.startswith("BANKO") else \
                     "▸" if lbl.startswith("TEK")   else \
                     "◈" if lbl.startswith("CIFT")  else "○"
            risk     = r.get("_risk","")
            forced   = r.get("_forced_banko", False)
            risk_tag = {"SURE":"🔒","LIKELY":"","UNCERTAIN":"⚠","CHAOTIC":"🌀"}.get(risk,"")
            if forced and lbl.startswith("BANKO"):
                risk_tag = "⚠"  # zorla BANKO
            print(f"  │ {r['no']:>2}. {r['mac']:<28} {marker} {lbl:<12}"
                  + (f" {risk_tag}" if risk_tag else "")
                  + (f" {ctx}" if ctx else ""))

        print(f"  └─ Toplam: {cols} kolon × 10 TL = {cost_b:,} TL")

    # ── A/B/C yan yana karşılaştırma (kısa) ──
    print(f"\n{'═'*W}")
    print(f"  {'#':<4} {'MAÇ':<24}   A({budgets_abc['A']}TL)    B({budgets_abc['B']}TL)    C({budgets_abc['C']}TL)")
    print(f"{'─'*W}")
    for i, r in enumerate(results):
        vals = []
        for letter in ["A","B","C"]:
            opt_r = next((x for x in abc[letter]["results"] if x["no"]==r["no"]), r)
            lbl = opt_r["oneri"].replace("BANKO","BNK").replace("CIFT ","CFT").replace("KAOS ","KAO").replace("TEK  ","TEK")
            vals.append(f"{lbl[:8]:<8}")
        print(f"  {r['no']:>2}. {r['mac'][:24]:<24}  {'  '.join(vals)}")
    print(f"{'─'*W}")
    for letter in ["A","B","C"]:
        d = abc[letter]
        print(f"  {letter}: {d['cols']:>4} kolon = {d['cost']:>6,} TL", end="   ")
    print()
    print(f"{'═'*W}")

    # ── Seçim ──
    print(f"\n  Hangi kuponu oynuyorsunuz? (A/B/C, Enter=A): ", end="", flush=True)
    try:
        choice = input().strip().upper()[:1]
        if choice not in ("A","B","C"):
            choice = "A"
    except (OSError, IOError, ValueError, TypeError, KeyError):
        choice = "A"

    chosen = abc[choice]
    print(f"\n  → Kupon {choice} seçildi: "
          f"{chosen['cols']} kolon = {chosen['cost']:,} TL")

    # ── Senaryo kupon seçeneği ────────────────────────────────
    from coupon.optimizer import generate_scenario_coupons, print_scenario_coupons
    print(f"\n  Senaryo kuponları ister misiniz? (KAOS maçları farklı kuponlara bölünür)")
    print(f"  Kaç kupon? (2/3/4, Enter=hayır): ", end="", flush=True)
    try:
        n_inp = input().strip()
        n_coupons = int(n_inp) if n_inp in ("2","3","4") else 0
    except (OSError, IOError, ValueError, TypeError):
        n_coupons = 0

    if n_coupons >= 2:
        scenario_coupons = generate_scenario_coupons(
            results, n_coupons=n_coupons, max_cols_each=32
        )
        print_scenario_coupons(scenario_coupons, chosen["results"])
        # EV analizi — her kupon için
        try:
            from coupon.optimizer import evaluate_coupon
            print(f"\n  ── SENARYO KUPON ANALİZİ ────────────────────────")
            for sc in scenario_coupons:
                ev = evaluate_coupon(sc["matches"])
                print(f"  Kupon {sc['id']} ({sc['cols']} kolon): "
                      f"beklenen={ev['ev_proxy']:.1f} | "
                      f"12+=%{ev['p_12plus']*100:.1f} | "
                      f"15/15=%{ev['hit_prob']*100:.3f}")
        except (OSError, ImportError, TypeError, RuntimeError, ValueError):
            pass
    else:
        # Kupon EV simülasyonu
        try:
            from coupon.optimizer import evaluate_coupon
            ev = evaluate_coupon(chosen["results"])
            print(f"\n  ── KUPON ANALİZİ (10K simülasyon) ───────────────")
            print(f"  Beklenen doğru sayısı : {ev['ev_proxy']:.1f} / {len(chosen['results'])}")
            print(f"  12+ doğru olasılığı   : %{ev['p_12plus']*100:.1f}")
            print(f"  13+ doğru olasılığı   : %{sum(v for k,v in ev['dist'].items() if k>=13)*100:.1f}")
            print(f"  15/15 olasılığı       : %{ev['hit_prob']*100:.3f}")
            dist_str = "  Dağılım: " + " | ".join(
                f"{k}✓=%{v*100:.1f}" for k, v in sorted(ev["dist"].items(), reverse=True)
                if k >= 10
            )
            print(dist_str)
        except (OSError, ImportError, TypeError, RuntimeError, ValueError):
            pass

        # 2500+ ise böl
        if chosen["cols"] > CFG["max_cols_per_coupon"]:
            coupons = split_coupons(chosen["results"])
            if coupons:
                print_coupons(coupons)
        else:
            print(f"\n  Tek kupon — 2,500 kolon sınırı içinde ✓")

    # ── 7. FD EŞLEŞTİRME RAPORU ─────────────────────────────
    print("\n  ── TAKIM EŞLEŞTİRME RAPORU ──────────────────────")
    for r in results:
        print(f"  #{r['no']:>2} {r['mac']:<30} → {r['fd_match']}")

    # ── 6. JSON KAYDET ────────────────────────────────────────
    if opts.get("save"):
        out = {
            "generated": datetime.now().isoformat(),
            "simulations": CFG["simulations"],
            "total_columns": total_cols,
            "total_cost_tl": cost,
            "results": results,
            "raw_list": raw_matches,
        }
        fname = f"st_results_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n  Sonuçlar kaydedildi: {fname}")

    print("\n" + "═" * 70)
    print("  Pipeline tamamlandı.")
    print("═" * 70)

    # Tahminleri hafızaya kaydet
    # week_id — liste başlığındaki tarihten çıkar (en güvenilir)
    from datetime import timedelta
    # NOTE: _now is defined at the top of main() — do not re-assign here

    def _week_from_header(matches: list):
        """'8 MAYIS - 12 MAYIS 2026' gibi metinden ISO hafta çıkar — başlangıç tarihi."""
        AY = {"ocak":1,"subat":2,"mart":3,"nisan":4,"mayis":5,
              "haziran":6,"temmuz":7,"agustos":8,"eylul":9,
              "ekim":10,"kasim":11,"aralik":12}
        import re as _re
        from datetime import date as _date
        def _tr_lower(s):
            # Sadece Türkçeye özgü büyük harfleri dönüştür, sonra normal lower()
            return s.replace("İ","i").replace("Ğ","ğ").replace("Ü","ü")\
                    .replace("Ş","ş").replace("Ö","ö").replace("Ç","ç").lower()
        for rm in matches:
            header = rm.get("week_header","") or rm.get("header","") or ""
            if not header: continue
            yr_m = _re.search(r'\b(202\d)\b', header)
            if not yr_m: continue
            yr = int(yr_m.group(1))
            m = _re.search(r'(\d{1,2})\s+([A-Za-zĞğÜüŞşİıÖöÇç]+)', header)
            if m:
                day = int(m.group(1))
                ay_str = _tr_lower(m.group(2))
                ay_no = AY.get(ay_str)
                if ay_no:
                    try:
                        return _date(yr, ay_no, day).strftime("%G-W%V")
                    except Exception:
                        pass
        return None

    # Önce maç tarihlerinden dene
    _week_from_list = None
    for rm in raw_matches:
        _d = rm.get("date", "")
        if _d:
            try:
                from datetime import datetime as _dt
                for _fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
                    try:
                        _parsed = _dt.strptime(_d, _fmt)
                        _week_from_list = _parsed.strftime("%G-W%V")
                        break
                    except ValueError:
                        continue
                if _week_from_list: break
            except Exception:
                pass

    # Sonra hafta başlığından dene
    if not _week_from_list:
        _week_from_list = _week_from_header(raw_matches)

    if _week_from_list:
        week_id = _week_from_list
    elif _now.weekday() == 1 and _now.hour < 14:  # Salı öğleden önce
        _ref = _now - timedelta(days=4)
        week_id = _ref.strftime("%G-W%V")
    else:
        week_id = _now.strftime("%G-W%V")

    # ── Resmi Spor Toto hafta numarası ──────────────────────────
    # Önceki haftayı bul → otomatik +1 öner
    try:
        from config import ST_SEASON_TAG as _st_season
    except ImportError:
        _st_season = "2526"

    _existing_log = mem._load_pred_log()
    _st_nums = []
    for _wk in _existing_log.keys():
        import re as _re2
        _m = _re2.match(r"ST(\d+)-", _wk)
        if _m:
            _st_nums.append(int(_m.group(1)))

    _st_suggest = (max(_st_nums) + 1) if _st_nums else 41

    print(f"\n  Resmi Spor Toto hafta numarası (Enter={_st_suggest}): ", end="", flush=True)
    try:
        _st_input = input().strip()
        _st_num = int(_st_input) if _st_input else _st_suggest
    except Exception:
        _st_num = _st_suggest

    week_id = f"ST{_st_num}-{_st_season}"
    print(f"  → {week_id} olarak kaydedilecek")

    # Güvenlik: mevcut hafta var mı kontrol et
    _existing = mem._load_pred_log()
    if week_id in _existing and _existing[week_id].get("matches"):
        _existing_cnt = sum(1 for m in _existing[week_id]["matches"] if m.get("actual"))
        if _existing_cnt > 0:
            print(f"\n  ⚠ {week_id} zaten {_existing_cnt} sonuç içeriyor!")
            print(f"  Üzerine yazmak istiyor musunuz? (E/H, Enter=H): ", end="", flush=True)
            try:
                _ans = input().strip().upper()
            except Exception:
                _ans = "H"
            if _ans != "E":
                print(f"  İptal edildi — hafta_id değiştirin.")
                return

    print(f"\n  [Hafta] {week_id} olarak kaydediliyor...")
    mem.log_predictions(week_id, results, raw_matches)

    # xlsx raporu oluştur
    xlsx_path = export_xlsx(results, abc, week_id, mem)
    if xlsx_path:
        print(f"\n  Rapor kaydedildi: {xlsx_path}")


# ═══════════════════════════════════════════════════════════════
# ÖĞRENME SİSTEMİ — STMemory
# ═══════════════════════════════════════════════════════════════
MEMORY_FILE    = "st_memory.json"
MEMORY_BACKUP  = "st_memory_backup.json"
PRED_LOG_FILE  = "st_predictions.json"
MIN_SAMPLES    = 10
MEMORY_VERSION = 3
FTR_MAP = {"1":"H","X":"D","2":"A","H":"H","D":"D","A":"A","0":"D"}


if __name__ == "__main__":
    # Ana döngü — her işlem sonrası menüye döner
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("\n\n  Çıkılıyor...")
            break
        except SystemExit:
            pass
        except (OSError, IOError, ValueError, TypeError, KeyError, RuntimeError) as e:
            print(f"\n  [HATA] {e}")

        # İşlem bitti, menüye dön mü?
        print("\n" + "─"*40)
        print("  M = Menüye dön  |  Q = Çıkış")
        print("  Seçim: ", end="", flush=True)
        try:
            ans = input().strip().upper()[:1]
        except (EOFError, KeyboardInterrupt):
            ans = "Q"

        if ans == "Q":
            print("  İyi şanslar!")
            break
        # M veya Enter → döngü başa döner, main() tekrar çağrılır
