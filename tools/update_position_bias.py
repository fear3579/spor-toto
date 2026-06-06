"""
tools/update_position_bias.py — Pozisyon Bias Güncelle
=======================================================
sportoto_data/matches.csv'den 4 sezon pozisyon istatistiklerini hesaplar
ve position_bias_generated.py'yi günceller.

Kullanım:
  python tools/update_position_bias.py           # tüm sezonlar
  python tools/update_position_bias.py --season 2324  # tek sezon
  python tools/update_position_bias.py --dry-run      # sadece göster

Menü 6→9 ile de çalışır (main.py entegre).
"""

import os, json, csv, argparse
from collections import defaultdict
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH    = os.path.join(BASE_DIR, "sportoto_data", "matches.csv")
OUTPUT_FILE = os.path.join(BASE_DIR, "model", "position_bias_generated.py")
STATS_FILE  = os.path.join(BASE_DIR, "sportoto_data", "position_stats.json")


def load_matches(season_filter: str = None) -> list:
    """matches.csv'den lig maçlarını yükle (milli ve kupa hariç)."""
    if not os.path.exists(CSV_PATH):
        print(f"  ✗ {CSV_PATH} bulunamadı — önce Menü 6→7 ile veri indir")
        return []

    matches = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Milli maç filtresi
            if row.get("is_national", "").lower() in ("true", "1", "yes"):
                continue
            # Sonuç yoksa atla
            result = row.get("result", "").strip()
            if result not in ("1", "X", "2"):
                continue
            # Sezon filtresi
            if season_filter and row.get("season") != season_filter:
                continue
            # Pozisyon 1-15 arası
            try:
                pos = int(row.get("pos", 0))
            except (ValueError, TypeError):
                continue
            if not 1 <= pos <= 15:
                continue

            matches.append({
                "pos":    pos,
                "result": result,
                "season": row.get("season", ""),
                "week":   row.get("week_no", ""),
                "home":   row.get("home", ""),
                "away":   row.get("away", ""),
            })
    return matches


def compute_position_stats(matches: list) -> dict:
    """
    Pozisyon bazında 1/X/2 dağılımını hesapla.
    Döner: {pos: {"n": int, "p1": float, "px": float, "p2": float, ...}}
    """
    counts = defaultdict(lambda: {"n": 0, "1": 0, "X": 0, "2": 0})

    for m in matches:
        pos = m["pos"]
        counts[pos]["n"] += 1
        counts[pos][m["result"]] += 1

    stats = {}
    for pos in range(1, 16):
        c = counts[pos]
        n = c["n"]
        if n == 0:
            stats[pos] = {"n": 0, "p1": 0.45, "px": 0.27, "p2": 0.28,
                          "banko_safe": False, "draw_thr_adj": 0.0}
            continue

        p1 = c["1"] / n
        px = c["X"] / n
        p2 = c["2"] / n

        # BANKO güvenli: ev kazanma > %55 ve X < %20
        banko_safe = p1 > 0.55 and px < 0.20

        # Draw threshold ayarı
        # X > %40 → eşiği düşür (X kolaylaştır)
        # X < %20 → eşiği yükselt (X zorlaştır)
        if px > 0.40:
            draw_thr_adj = -0.04
        elif px > 0.32:
            draw_thr_adj = -0.02
        elif px < 0.18:
            draw_thr_adj = +0.04
        elif px < 0.22:
            draw_thr_adj = +0.02
        else:
            draw_thr_adj = 0.0

        stats[pos] = {
            "n":            n,
            "p1":           round(p1, 4),
            "px":           round(px, 4),
            "p2":           round(p2, 4),
            "banko_safe":   banko_safe,
            "draw_thr_adj": draw_thr_adj,
        }
    return stats


def compute_lambda_bias(stats: dict) -> dict:
    """
    Pozisyon bazında lambda çarpanı hesapla.
    Sistematik ev/dep farkını yakalar.
    """
    # Genel ortalama
    total_n = sum(s["n"] for s in stats.values() if s["n"] > 0)
    if total_n == 0:
        return {}

    avg_p1 = sum(s["p1"] * s["n"] for s in stats.values()) / total_n
    avg_p2 = sum(s["p2"] * s["n"] for s in stats.values()) / total_n

    bias = {}
    for pos, s in stats.items():
        if s["n"] < 10:   # Yetersiz veri → nötr
            bias[pos] = {"home": 1.0, "away": 1.0}
            continue
        # Pozisyonun genel ortalamasından sapması
        home_bias = s["p1"] / avg_p1 if avg_p1 > 0 else 1.0
        away_bias = s["p2"] / avg_p2 if avg_p2 > 0 else 1.0
        # ±20% ile sınırla
        bias[pos] = {
            "home": round(max(0.80, min(1.20, home_bias)), 4),
            "away": round(max(0.80, min(1.20, away_bias)), 4),
        }
    return bias


def generate_python_file(stats: dict, bias: dict, total_matches: int,
                          season_filter: str = None) -> str:
    """position_bias_generated.py içeriğini üret."""
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    sfilt = season_filter or "tüm sezonlar"

    lines = [
        '"""',
        'position_bias_generated.py — OTOMATİK ÜRETİLDİ',
        f'Kaynak : sportoto_data/matches.csv',
        f'Üretim : {now}',
        f'Kapsam : {sfilt}  |  {total_matches} lig maçı',
        '',
        'Bu dosyayı elle düzenlemeyin.',
        'Güncellemek için: python tools/update_position_bias.py',
        '"""',
        '',
        'from __future__ import annotations',
        '',
        '# ── Pozisyon İstatistikleri ─────────────────────────────────────────────',
        '# pos → {n, p1, px, p2, banko_safe, draw_thr_adj}',
        'POSITION_STATS: dict[int, dict] = {',
    ]

    for pos in range(1, 16):
        s = stats[pos]
        lines.append(
            f'    {pos:>2}: {{"n": {s["n"]:>4}, '
            f'"p1": {s["p1"]:.4f}, "px": {s["px"]:.4f}, "p2": {s["p2"]:.4f}, '
            f'"banko_safe": {str(s["banko_safe"]):<5}, '
            f'"draw_thr_adj": {s["draw_thr_adj"]:+.2f}}},'
        )

    lines += [
        '}',
        '',
        '# ── Lambda Bias ─────────────────────────────────────────────────────────',
        '# pos → {home, away}  — genel ortalamadan sapma çarpanı',
        'POSITION_LAMBDA_BIAS: dict[int, dict] = {',
    ]

    for pos in range(1, 16):
        b = bias.get(pos, {"home": 1.0, "away": 1.0})
        lines.append(
            f'    {pos:>2}: {{"home": {b["home"]:.4f}, "away": {b["away"]:.4f}}},'
        )

    lines += [
        '}',
        '',
        '# ── Yardımcı fonksiyonlar ───────────────────────────────────────────────',
        '',
        'BANKO_SAFE_POSITIONS: set[int] = {',
        '    pos for pos, s in POSITION_STATS.items() if s["banko_safe"]',
        '}',
        '',
        'HIGH_DRAW_POSITIONS: set[int] = {',
        '    pos for pos, s in POSITION_STATS.items() if s["px"] > 0.35',
        '}',
        '',
        '',
        'def get_draw_thr_adjust(position: int) -> float:',
        '    """Pozisyon için draw threshold delta döner."""',
        '    return POSITION_STATS.get(position, {}).get("draw_thr_adj", 0.0)',
        '',
        '',
        'def get_lambda_bias(position: int) -> dict:',
        '    """Pozisyon için home/away lambda çarpanı döner."""',
        '    return POSITION_LAMBDA_BIAS.get(position, {"home": 1.0, "away": 1.0})',
        '',
        '',
        'def get_position_probs(position: int) -> tuple[float, float, float]:',
        '    """Pozisyon için tarihsel (p1, px, p2) döner."""',
        '    s = POSITION_STATS.get(position, {})',
        '    return s.get("p1", 0.45), s.get("px", 0.27), s.get("p2", 0.28)',
    ]

    return '\n'.join(lines) + '\n'


def print_summary(stats: dict, matches: list):
    """Terminal özet tablosu."""
    print(f"\n  {'─'*62}")
    print(f"  {'Pos':>3}  {'N':>5}  {'Ev%':>6}  {'X%':>6}  {'Dep%':>6}  {'BANKO':>6}  {'X-Adj':>6}")
    print(f"  {'─'*62}")
    for pos in range(1, 16):
        s = stats[pos]
        if s["n"] == 0:
            print(f"  {pos:>3}  {'---':>5}")
            continue
        banko = "✓" if s["banko_safe"] else ""
        adj   = f"{s['draw_thr_adj']:+.2f}"
        print(f"  {pos:>3}  {s['n']:>5}  "
              f"{s['p1']*100:>5.1f}%  {s['px']*100:>5.1f}%  {s['p2']*100:>5.1f}%"
              f"  {banko:>6}  {adj:>6}")
    print(f"  {'─'*62}")

    # Özet
    total = len(matches)
    p1_all = sum(1 for m in matches if m["result"] == "1") / total
    px_all = sum(1 for m in matches if m["result"] == "X") / total
    p2_all = sum(1 for m in matches if m["result"] == "2") / total
    print(f"  {'GENEL':>3}  {total:>5}  "
          f"{p1_all*100:>5.1f}%  {px_all*100:>5.1f}%  {p2_all*100:>5.1f}%")

    banko_positions = [p for p, s in stats.items() if s["banko_safe"]]
    high_draw_pos   = [p for p, s in stats.items() if s["px"] > 0.35]
    print(f"\n  BANKO Güvenli Pozisyonlar : {banko_positions}")
    print(f"  Yüksek X Pozisyonları     : {high_draw_pos}")


def run(season_filter: str = None, dry_run: bool = False) -> bool:
    """Ana çalışma fonksiyonu. True döner = başarılı."""
    print(f"\n  Pozisyon Bias Güncelleme")
    print(f"  {'─'*50}")
    print(f"  Kaynak : {CSV_PATH}")
    if season_filter:
        print(f"  Sezon  : {season_filter}")

    matches = load_matches(season_filter)
    if not matches:
        return False

    print(f"  Yüklenen: {len(matches)} lig maçı")

    stats = compute_position_stats(matches)
    bias  = compute_lambda_bias(stats)
    print_summary(stats, matches)

    if dry_run:
        print(f"\n  [DRY-RUN] Dosya yazılmadı.")
        return True

    # JSON stats kaydet
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated": datetime.now().isoformat(),
            "total_matches": len(matches),
            "season_filter": season_filter,
            "stats": {str(k): v for k, v in stats.items()},
            "bias":  {str(k): v for k, v in bias.items()},
        }, f, ensure_ascii=False, indent=2)

    # Python dosyası yaz
    py_content = generate_python_file(stats, bias, len(matches), season_filter)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(py_content)

    print(f"\n  ✅ Güncellendi:")
    print(f"     {OUTPUT_FILE}")
    print(f"     {STATS_FILE}")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season",  help="2223 / 2324 / 2425 / 2526")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(season_filter=args.season, dry_run=args.dry_run)
