# -*- coding: utf-8 -*-
"""
tools/migrate_team_pos_to_memory.py
------------------------------------
spor_toto_stats.json → st_memory.json köprüsü.

Kırık zinciri tamamlar:
  spor_toto_stats.json (team_position_stats, devret_stats, phase_distribution)
      ↓
  st_memory.json (chronic_profiles[team]["team_position_stats"])
                 (position_distribution)
                 (devret_stats)
                 (phase_distribution)

Kullanım:
  python tools/migrate_team_pos_to_memory.py          # tek seferlik
  python tools/migrate_team_pos_to_memory.py --force  # üzerine yaz

update_stats.py sonunda otomatik çağrılır.
"""

import json
import os
import sys
import re

# ── Dosya yolları ─────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.dirname(_HERE)            # SPOR TOTO/
STATS_JSON  = os.path.join(_HERE,  "spor_toto_stats.json")
MEMORY_JSON = os.path.join(_ROOT,  "st_memory.json")
MEMORY_BAK  = os.path.join(_ROOT,  "st_memory_backup.json")


def _norm_team(name: str) -> str:
    """Takım adını normalize et (büyük harf, Türkçe dönüşüm)."""
    name = str(name).upper().strip()
    for k, v in [("Ğ","G"),("Ş","S"),("İ","I"),("Ü","U"),("Ö","O"),("Ç","C"),
                  ("ğ","g"),("ş","s"),("ı","i"),("ü","u"),("ö","o"),("ç","c")]:
        name = name.replace(k, v)
    return re.sub(r"\s+", " ", name).strip()


def migrate(force: bool = False) -> dict:
    """
    Ana migration fonksiyonu.

    Returns:
        {"teams_updated": int, "positions_updated": int, "status": str}
    """
    # ── Kaynak: spor_toto_stats.json ─────────────────────────────────────────
    if not os.path.exists(STATS_JSON):
        return {"teams_updated": 0, "status": "stats_not_found"}

    with open(STATS_JSON, encoding="utf-8") as f:
        stats = json.load(f)

    team_pos_src    = stats.get("team_position_stats", {})
    pos_dist_src    = stats.get("position_distribution", {})
    devret_src      = stats.get("devret_stats", {})
    phase_src       = stats.get("phase_distribution", {})

    if not team_pos_src and not pos_dist_src:
        return {"teams_updated": 0, "status": "no_data_in_stats"}

    # ── Hedef: st_memory.json ─────────────────────────────────────────────────
    if not os.path.exists(MEMORY_JSON):
        return {"teams_updated": 0, "status": "memory_not_found"}

    with open(MEMORY_JSON, encoding="utf-8") as f:
        memory = json.load(f)

    # Backup
    import shutil
    shutil.copy2(MEMORY_JSON, MEMORY_BAK)

    # ── 1. chronic_profiles → team_position_stats ─────────────────────────────
    if "chronic_profiles" not in memory:
        memory["chronic_profiles"] = {}

    teams_updated = 0
    for team_raw, pos_data in team_pos_src.items():
        if not pos_data:
            continue  # Boş takımları atla

        team_norm = _norm_team(team_raw)

        # Profil yoksa oluştur
        if team_norm not in memory["chronic_profiles"]:
            memory["chronic_profiles"][team_norm] = {
                "odds_performance":  {},
                "tactical_ghosting": {},
                "team_position_stats": {},
                "streak_history":    [],
                "_decay_alpha":      0.85,
                "_sample_count":     0,
                "_last_updated":     "",
            }

        # team_position_stats'ı güncelle
        existing = memory["chronic_profiles"][team_norm].get("team_position_stats", {})

        # force=False: sadece eksik pozisyonları ekle
        # force=True:  tüm pozisyonları üzerine yaz
        for pos_str, pos_stats in pos_data.items():
            if force or pos_str not in existing:
                existing[pos_str] = {
                    "win":    pos_stats.get("win",   0.0),
                    "draw":   pos_stats.get("draw",  0.0),
                    "loss":   pos_stats.get("loss",  0.0),
                    "sample": pos_stats.get("sample", 0),
                }

        memory["chronic_profiles"][team_norm]["team_position_stats"] = existing
        teams_updated += 1

    # ── 2. position_distribution (top-level) ─────────────────────────────────
    if force or "position_distribution" not in memory:
        memory["position_distribution"] = pos_dist_src

    # ── 3. devret_stats (top-level) ──────────────────────────────────────────
    if force or "devret_stats" not in memory:
        memory["devret_stats"] = devret_src

    # ── 4. phase_distribution (top-level) ────────────────────────────────────
    if force or "phase_distribution" not in memory:
        memory["phase_distribution"] = phase_src

    # ── Kaydet ───────────────────────────────────────────────────────────────
    tmp_path = MEMORY_JSON + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, MEMORY_JSON)

    return {
        "teams_updated":     teams_updated,
        "positions_updated": len(pos_dist_src),
        "devret_synced":     bool(devret_src),
        "phase_synced":      bool(phase_src),
        "status":            "ok",
    }


def print_report(result: dict) -> None:
    if result["status"] == "ok":
        print(f"  ✅ {result['teams_updated']} takım → chronic_profiles")
        print(f"  ✅ {result['positions_updated']} pozisyon dağılımı")
        print(f"  ✅ devret_stats: {'✓' if result['devret_synced'] else '-'}")
        print(f"  ✅ phase_distribution: {'✓' if result['phase_synced'] else '-'}")
    else:
        print(f"  ⚠ Migration atlandı: {result['status']}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    print(f"\nst_memory migration {'(force)' if force else ''}...")
    result = migrate(force=force)
    print_report(result)
