"""
HAFTALIK İSTATİSTİK GÜNCELLEYICI
==================================
Kullanım:
    python update_stats.py <docx_yolu>
    python update_stats.py <docx_yolu> --dry-run    (yazmadan önizle)
    python update_stats.py <docx_yolu> --force       (diff yoksa bile yaz)

Yaptığı işlemler:
    1. DOCX'i parse eder (milli+kupa filtrelenmiş, saf lig maçları)
    2. Eski spor_toto_stats.json ile karşılaştırır (diff)
    3. bias_engine ile yeni katsayıları hesaplar
    4. season_end/position_bias_generated.py dosyasını yazar
    5. spor_toto_stats.json günceller

Pydroid3 kullanımı:
    - Dosyayı her hafta yeni sonuçlar eklenince çalıştır
    - Değişiklikler otomatik olarak position_bias'a yansır
"""

from __future__ import annotations

import sys
import json
import datetime
from pathlib import Path

# Proje kök yolunu ekle
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from parse_spor_toto import parse_file, compute_stats  # tools/ klasöründe olmalı
from bias_engine import derive_all, compute_diff, generate_pos_note


# ─── Yollar ──────────────────────────────────────────────────────────────────

STATS_JSON  = ROOT / "spor_toto_stats.json"
GENERATED_PY = ROOT.parent / "model" / "position_bias_generated.py"


# ─── Yardımcılar ─────────────────────────────────────────────────────────────

def load_old_stats() -> dict | None:
    if STATS_JSON.exists():
        return json.loads(STATS_JSON.read_text(encoding="utf-8"))
    return None


def save_stats(stats: dict) -> None:
    STATS_JSON.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _set_repr(s: list[int]) -> str:
    return "{" + ", ".join(str(x) for x in sorted(s)) + "}"


def _bias_repr(bias: dict) -> str:
    lines = []
    for pos in sorted(bias.keys()):
        inner = ", ".join(f'"{k}": {v:+.3f}' for k, v in sorted(bias[pos].items()))
        lines.append(f"    {pos}: {{{inner}}},")
    return "\n".join(lines)


def _thr_repr(thr: dict) -> str:
    lines = []
    for pos in sorted(thr.keys()):
        lines.append(f"    {pos}: {thr[pos]:+.3f},")
    return "\n".join(lines)


def _stats_repr(pos_stats: dict, cats: dict) -> str:
    lines = []
    for p_str in [str(i) for i in range(1, 16)]:
        if p_str not in pos_stats:
            continue
        s = pos_stats[p_str]
        pos = int(p_str)
        note = generate_pos_note(pos, s, cats)
        if pos in cats["banko_safe"]:
            bias_str = '"1"'
        elif pos in cats["high_x"]:
            bias_str = '"X"'
        elif pos in cats["away_strong"]:
            bias_str = '"2"'
        else:
            bias_str = '"1"'
        lines.append(
            f'    {pos}: {{"home": {s["home"]}, "draw": {s["draw"]}, '
            f'"away": {s["away"]}, "bias": {bias_str}, '
            f'"note": "{note}"}},'
        )
    return "\n".join(lines)


# ─── Generated Dosya Yazar ────────────────────────────────────────────────────

def write_generated(stats: dict, derived: dict) -> None:
    """
    season_end/position_bias_generated.py dosyasını yazar.
    Bu dosya position_bias.py tarafından otomatik yüklenir.
    """
    now         = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    pos_stats   = stats["position_distribution"]
    cats        = derived["categories"]
    bias        = derived["lambda_bias"]
    thr         = derived["draw_thr"]
    base        = derived["baseline"]
    filt        = stats.get("filtered", {})
    n_weeks     = stats.get("total_weeks", "?")
    n_league    = filt.get("league", "?")
    devret      = stats.get("devret_stats", {})

    content = f'''\
# AUTO-GENERATED — Elle düzenleme yapma
# Oluşturuldu  : {now}
# Kaynak        : {n_weeks} hafta, {n_league} saf lig maçı (milli+kupa filtrelenmiş)
# Komut         : python update_stats.py <docx_yolu>
#
# Baseline: Ev=%{base["home"]:.1f}  X=%{base["draw"]:.1f}  Dep=%{base["away"]:.1f}
# Devret X oranı: %{devret.get("devret_x_rate", 0):.1f}  |  Normal: %{devret.get("normal_x_rate", 0):.1f}
from __future__ import annotations


POSITION_STATS: dict = {{
{_stats_repr(pos_stats, cats)}
}}

POSITION_LAMBDA_BIAS: dict[int, dict[str, float]] = {{
{_bias_repr(bias)}
}}

POSITION_DRAW_THR_ADJUST: dict[int, float] = {{
{_thr_repr(thr)}
}}

BANKO_SAFE_POSITIONS: set[int] = {_set_repr(cats["banko_safe"])}

HIGH_X_POSITIONS: set[int] = {_set_repr(cats["high_x"])}

AWAY_STRONG_POSITIONS: set[int] = {_set_repr(cats["away_strong"])}
'''

    GENERATED_PY.write_text(content, encoding="utf-8")


# ─── Diff Raporu ─────────────────────────────────────────────────────────────

def print_diff_report(diffs: list[dict]) -> None:
    if not diffs:
        print("\n  ✅ Değişiklik yok — katsayılar stabil")
        return

    field_emoji = {"home": "🏠", "draw": "〰️", "away": "✈️"}
    print(f"\n  {'Pos':<5} {'Alan':<6} {'Eski':>7} {'Yeni':>7} {'Δ':>7}")
    print(f"  {'─'*36}")
    for d in diffs:
        emoji  = field_emoji.get(d["field"], "  ")
        sign   = "+" if d["delta"] > 0 else ""
        flag   = "  ⚠ STRATEJİ DEĞİŞTİ" if abs(d["delta"]) >= 7 else ""
        print(f"  #{d['pos']:<4} {emoji}{d['field']:<5} {d['old']:>6.1f}% {d['new']:>6.1f}% "
              f"  {sign}{d['delta']:.1f}pp{flag}")


def print_bias_report(derived: dict, stats: dict) -> None:
    cats   = derived["categories"]
    bias   = derived["lambda_bias"]
    thr    = derived["draw_thr"]
    base   = derived["baseline"]
    pos_s  = stats["position_distribution"]

    print(f"\n  Baseline: Ev={base['home']:.1f}%  X={base['draw']:.1f}%  Dep={base['away']:.1f}%")
    print(f"\n  📊 HESAPLANAN KATSAYILAR")
    print(f"  {'─'*62}")

    for pos in range(1, 16):
        # pos_s anahtarları str olabilir (normalize edilmiş) veya int
        s = pos_s.get(str(pos)) or pos_s.get(pos)
        if s is None:
            continue
        n      = s.get("total", 0)
        lb     = bias.get(pos, {})
        dt     = thr.get(pos, 0.0)
        cat    = ""
        if pos in cats["banko_safe"]:    cat = "✅ BANKO"
        elif pos in cats["high_x"]:      cat = "🔴 HIGH_X"
        elif pos in cats["away_strong"]: cat = "⚠ DEP"
        lb_str = "  ".join(f"{k}:{v:+.3f}" for k, v in lb.items()) if lb else "—"
        dt_str = f"{dt:+.3f}" if dt else "—"
        print(f"  #{pos:<2}  X={s['draw']:>5.1f}%  Ev={s['home']:>5.1f}%  "
              f"[n={n:>3}]  λ={lb_str:<22}  thr={dt_str:<7}  {cat}")


# ─── Ana Fonksiyon ────────────────────────────────────────────────────────────

def main() -> None:
    args     = sys.argv[1:]
    dry_run  = "--dry-run" in args
    force    = "--force"   in args
    docx_args = [a for a in args if not a.startswith("--")]

    if not docx_args:
        print("Kullanım: python update_stats.py <docx_yolu> [--dry-run] [--force]")
        sys.exit(1)

    docx_path = Path(docx_args[0])
    if not docx_path.exists():
        print(f"HATA: Dosya bulunamadı: {docx_path}")
        sys.exit(1)

    # 1. Parse
    print(f"\n{'='*60}")
    print(f"  AUGUR ENGINE — Haftalık İstatistik Güncelleyici")
    print(f"{'='*60}")
    print(f"\n[1] DOCX parse ediliyor: {docx_path.name}")
    weeks     = parse_file(str(docx_path))
    new_stats = compute_stats(weeks)

    # Normalize: pos_dist anahtarlarını her zaman STR yap
    # (compute_stats int döner, json.load str döner — tek format kullanalım)
    raw_pos = new_stats.get("position_distribution", {})
    new_stats["position_distribution"] = {str(k): v for k, v in raw_pos.items()}

    filt = new_stats.get("filtered", {})
    print(f"    {new_stats['total_weeks']} hafta | "
          f"Lig: {filt.get('league',0)}  Milli: {filt.get('milli',0)}  Kupa: {filt.get('kupa',0)}")

    # 2. Diff
    print(f"\n[2] Eski istatistiklerle karşılaştırılıyor...")
    old_stats = load_old_stats()
    diffs     = compute_diff(old_stats, new_stats, threshold=3.0)

    if old_stats:
        old_w = old_stats.get("total_weeks", 0)
        new_w = new_stats.get("total_weeks", 0)
        print(f"    Önceki: {old_w} hafta → Şimdi: {new_w} hafta "
              f"(+{new_w - old_w} yeni hafta)")
    else:
        print("    (İlk çalıştırma — karşılaştırma yok)")

    print_diff_report(diffs)

    # 3. Bias hesapla
    print(f"\n[3] Katsayılar hesaplanıyor (bias_engine)...")
    pos_stats = new_stats["position_distribution"]
    derived   = derive_all(pos_stats)
    print_bias_report(derived, new_stats)

    # 4. Yaz / Önizle
    if dry_run:
        print(f"\n[4] DRY-RUN — dosyalar yazılmadı")
        print(f"    Yazdırılacak: {GENERATED_PY.name}")
        print(f"    Yazdırılacak: {STATS_JSON.name}")
        return

    if not diffs and not force and old_stats:
        print(f"\n[4] Değişiklik yok — yazma atlandı (--force ile zorla)")
        return

    print(f"\n[4] Dosyalar yazılıyor...")
    save_stats(new_stats)
    write_generated(new_stats, derived)
    print(f"    ✅ {STATS_JSON.name}")
    print(f"    ✅ {GENERATED_PY.name}")

    # 5. Özet
    cats = derived["categories"]
    ds   = new_stats.get("devret_stats", {})
    print(f"\n{'='*60}")
    print(f"  GÜNCELLEME ÖZETI")
    print(f"{'='*60}")
    print(f"  BANKO güvenli pozisyonlar : {cats['banko_safe']}")
    print(f"  Yüksek X pozisyonları     : {cats['high_x']}")
    print(f"  Deplasman güçlü           : {cats['away_strong']}")
    print(f"  Devret X oranı            : %{ds.get('devret_x_rate', 0):.1f}")
    print(f"  Normal X oranı            : %{ds.get('normal_x_rate', 0):.1f}")
    print(f"\n  position_bias_generated.py → position_bias.py otomatik yüklendi")
    print(f"  Bir sonraki güncelleme   : Yeni hafta sonuçları gelince")
    print(f"{'='*60}\n")

    # ── st_memory.json senkronizasyonu ─────────────────────────────
    try:
        from tools.migrate_team_pos_to_memory import migrate, print_report
        print("  st_memory.json senkronize ediliyor...")
        result = migrate(force=True)
        print_report(result)
    except Exception as _e:
        print(f"  [!] st_memory senkron atlandı: {_e}")


if __name__ == "__main__":
    main()
