"""
Spor Toto Sonuçlar Parser
SporToto-sonuçlar.docx → JSON istatistikleri
"""

import re
import json
from collections import defaultdict
from pathlib import Path

# ─── Filtreler ────────────────────────────────────────────────────────────────

# Milli maç: Her iki takım da ülke ismiyse → milli maç → ÇIKAR
NATIONAL_TEAMS = {
    "Almanya","Andorra","Arnavutluk","Avusturya","Azerbaycan",
    "Belarus","Belçika","Bolivya","Bosna Hersek","Bulgaristan",
    "Danimarka","Ermenistan","Finlandiya","Fransa","Galler",
    "Gürcistan","HIrvatistan","Hrvatistan","Hollanda",
    "İngiltere","İrlanda","İskoçya","İspanya","İsveç","İsviçre","İtalya","İzlanda",
    "K Makedonya Cum.","K. Makedonya Cum.","Kazakistan","Kolombiya","Kosova",
    "Kuzey İrlanda","Letonya","Lihtenştayn","Litvanya","Lüksemburg",
    "Macaristan","Malta","Norveç","Peru","Polonya","Portekiz",
    "Romanya","San Marino","SIrbistan","Sırbistan","Slovakya","Slovenya",
    "Türkiye","Ukrayna","Venezuela","Yunanistan","Çekya",
}

# Kupa maçı: Bu takımlardan biri varsa → kupa → ÇIKAR
EXOTIC_CUP_TEAMS = {
    "Auckland City","Al Hilal","Mamel Sundow","Wydad","Esperance Tunis",
    "Urawa Red","Ulsan Hora-I","Botafogo RJ","Flamengo","Fluminense",
    "River Plate","CF Monterrey","CF Pachuca","Inter Miami CF",
    "Los Angeles FC","Seattle Sounders","Palmeiras SP","Boca Juniors",
    "El Ahly (MISIR)",
}

# Sisteme olmayan lig tespiti: bilinen lig bölgeleri dışındaki ligler → "unknown"
# Sistemdeki ligler: T1(Türkiye), E0(İngiltere), SP1(İspanya), I1(İtalya),
#   D1(Almanya), F1(Fransa), N1(Hollanda), B1(Belçika), P1(Portekiz),
#   G1(Yunanistan), SC0(İskoçya)
# Bu takım/lig parçacıkları bilinmeyen ligleri gösterir
_UNKNOWN_LEAGUE_SIGNALS = {
    # Asya
    "gyeongnam", "hwaseong", "cheonan", "suwon", "yongin", "ulsan",
    "jeonbuk", "seongnam", "daejeon", "incheon", "gangwon",
    "binh duong", "hoang anh", "becamex",
    # İzlanda (Sisteme dahil değil)
    "reykjavik", "afturelding", "njardvik", "volsungur", "vestri",
    "fylkir", "throttur", "grotta", "grindavik", "kopavogs",
    "aegir", "leiknir", "njardvik",
    # Danimarka küçük ligler (Fremad Amager, Brabrand vb. D1 değil)
    "fremad amager", "brabrand", "roskilde", "skive", "ishoj",
    # Finlandiya
    "haka", "japs",
    # Litvanya
    "ekranas", "neptunas klaipeda",
    # Güney Amerika (Kupa dışı)
    "nacional", "penarol", "olimpia", "cerro porteño",
}


def _is_unknown_league(home: str, away: str) -> bool:
    """
    Sistemdeki 11 ligde oynamayan takımları tespit eder.
    Pozisyon bias istatistiğini kirletmelerini önler.
    """
    combined = (home + " " + away).lower()
    return any(sig in combined for sig in _UNKNOWN_LEAGUE_SIGNALS)


def classify_match(home: str, away: str) -> str:
    """
    Maç türünü belirler.
    Returns: "league" | "milli" | "kupa" | "unknown_league"
    """
    h, a = home.strip(), away.strip()
    if h in NATIONAL_TEAMS and a in NATIONAL_TEAMS:
        return "milli"
    if h in EXOTIC_CUP_TEAMS or a in EXOTIC_CUP_TEAMS:
        return "kupa"
    if _is_unknown_league(h, a):
        return "unknown_league"
    return "league"


# ─── Parser ──────────────────────────────────────────────────────────────────

def parse_file(filepath: str) -> list[dict]:
    """
    Tablo bazlı hafta gruplandırma (v2).
    Maç tablosu + Ödül tablosu = 1 hafta.
    Hafta tarih paragrafı aranmaz.
    """
    from docx import Document

    doc   = Document(filepath)
    weeks = []
    cur   = None

    for tbl in doc.tables:
        rows = tbl.rows
        if not rows:
            continue
        r0 = [c.text.strip() for c in rows[0].cells]

        # Ödül tablosu → hafta kapat
        if r0 and r0[0] in ("Maç Sayısı", "Maç\nSayısı"):
            if cur and cur.get("matches"):
                for row in rows:
                    cells = [c.text.strip() for c in row.cells]
                    if not cells: continue
                    if "15 Bilen" in cells[0]:
                        val = cells[1] if len(cells) > 1 else ""
                        if "Devretti" in val:
                            cur["devret"] = True
                        else:
                            m2 = re.search(r"\d+", val)
                            if m2: cur["winner_15"] = int(m2.group())
                weeks.append(cur)
                cur = None
            continue

        # Maç tablosu → hafta aç
        # Başlık hücresinde "No", "Tarih", "Karşılaşma" veya "Maç" varsa maç tablosudur.
        r0_lower = " ".join(c.lower() for c in r0)
        is_match = any(kw in r0_lower for kw in ("no", "tarih", "karşılaşma", "karsilasma", "maç", "mac"))
        if not is_match:
            continue

        cur = {"date_start": "", "date_end": "",
               "matches": [], "devret": False, "winner_15": 0}

        for row in rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            if not cells or not cells[0]: continue

            try:   pos = int(cells[0])
            except ValueError: continue
            if not (1 <= pos <= 15): continue

            # tarih
            if not cur["date_start"]:
                for cv in cells[1:3]:
                    dt = re.search(r"\d{2}\.\d{2}\.\d{4}", cv)
                    if dt:
                        cur["date_start"] = dt.group()
                        break

            # sütun düzeni
            if len(cells) >= 5:
                mac, dur, sonuc = cells[2], cells[3], cells[4]
            elif len(cells) == 4:
                mac, dur, sonuc = cells[1], cells[2], cells[3]
            else:
                continue

            if sonuc == "0": sonuc = "X"  # Spor Toto geleneksel kupon: 0 = X
            if sonuc not in ("1", "X", "2"): continue
            # "Bitti" = maç tamamlandı. "Nötr"/"Iptal" gibi durumlar da kabul edilir
            # çünkü sonuç ("1"/"X"/"2") zaten doluysa maç oynanmış demektir.
            # Boş dur hücresi veya "Devam" içeriyorsa atla.
            dur_low = dur.lower()
            if dur and "devam" in dur_low:
                continue

            parts = re.split(r"\s*-\s*", mac, maxsplit=1)
            home  = parts[0].strip() if parts else mac
            away  = parts[1].strip() if len(parts) > 1 else ""

            if pos not in {x["pos"] for x in cur["matches"]}:
                cur["matches"].append({
                    "pos": pos, "home": home, "away": away,
                    "result": sonuc, "type": classify_match(home, away),
                })

    if cur and cur.get("matches"):
        weeks.append(cur)

    return weeks



# ─── İstatistik Hesabı ────────────────────────────────────────────────────────

def compute_stats(weeks: list[dict]) -> dict:
    """Tüm istatistikleri hesaplar."""

    # Pozisyon bazlı sayaçlar
    pos_counts = defaultdict(lambda: {"1": 0, "X": 0, "2": 0, "total": 0})

    # Devret hafta istatistikleri
    devret_x_counts    = []   # devret haftalarındaki X sayıları
    normal_x_counts    = []   # normal haftaların X sayıları

    # Devret sonrası hafta istatistikleri
    post_devret_x_counts = []

    # Sezon fazı sayaçları
    phase_counts = {
        "start":  {"1": 0, "X": 0, "2": 0, "total": 0, "weeks": 0, "devret": 0},
        "middle": {"1": 0, "X": 0, "2": 0, "total": 0, "weeks": 0, "devret": 0},
        "end":    {"1": 0, "X": 0, "2": 0, "total": 0, "weeks": 0, "devret": 0},
    }
    MONTH_PHASE = {5:"start",6:"start",7:"middle",8:"middle",
                   9:"end",10:"end",11:"end",12:"end",
                   1:"end",2:"end",3:"end",4:"end"}

    # Takım pozisyon istatistikleri (Süper Lig takımları)
    SL_TEAMS = {
        "Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor",
        "Başakşehir", "Konyaspor", "Alanyaspor", "Antalyaspor",
        "Kayserispor", "Kasımpaşa", "Rizespor", "Sivasspor",
        "Hatayspor", "Samsunspor", "Eyüpspor", "Bodrum",
        "Adana Demirspor", "Gaziantep", "Göztepe", "Karagümrük",
    }
    team_pos_stats = defaultdict(lambda: defaultdict(lambda: {"1": 0, "X": 0, "2": 0, "total": 0}))

    # Haftalık devret zinciri takibi
    prev_devret = False

    for week in weeks:
        if not week["matches"]:
            continue

        # Ayı çıkar
        try:
            month = int(week["date_start"].split(".")[1])
        except Exception:
            month = 5
        phase = MONTH_PHASE.get(month, "end")

        # Lig maçlarını filtrele — sadece sistemdeki 11 lig
        league_matches   = [m for m in week["matches"] if m["type"] == "league"]
        milli_count      = sum(1 for m in week["matches"] if m["type"] == "milli")
        kupa_count       = sum(1 for m in week["matches"] if m["type"] == "kupa")
        unknown_count    = sum(1 for m in week["matches"] if m["type"] == "unknown_league")

        # Devret için tüm maçların X sayısı (hafta bazlı istatistik)
        x_count = sum(1 for m in week["matches"] if m["result"] == "X")
        # Lig-only X (daha saf devret istatistiği)
        x_count_league = sum(1 for m in league_matches if m["result"] == "X")
        is_devret = week["devret"]

        if prev_devret:
            post_devret_x_counts.append(x_count_league)
        elif is_devret:
            devret_x_counts.append(x_count_league)
        else:
            normal_x_counts.append(x_count_league)

        # Faz istatistikleri — sadece lig maçlarıyla
        pc = phase_counts[phase]
        pc["weeks"] += 1
        if is_devret:
            pc["devret"] += 1

        for match in league_matches:   # ← SADECE LİG MAÇLARI
            r   = match["result"]
            pos = match["pos"]
            if 1 <= pos <= 15:
                pos_counts[pos][r]       += 1
                pos_counts[pos]["total"] += 1
            pc[r]        += 1
            pc["total"]  += 1

            # Takım pozisyon takibi (sadece lig)
            home_key = _normalize_team(match["home"])
            if home_key:
                s = team_pos_stats[home_key][pos]
                s[r]       += 1
                s["total"] += 1

        # Filtre sayaçlarını birleştir
        # (hesap sonunda özet için)
        week["_filter"] = {
            "league":  len(league_matches),
            "milli":   milli_count,
            "kupa":    kupa_count,
            "unknown": unknown_count,
        }

        prev_devret = is_devret

    # ── Filtre sayacı ──
    filter_counts = {"league": 0, "milli": 0, "kupa": 0}

    # ── Pozisyon dağılımı yüzdeleri ──
    pos_dist = {}
    for pos in range(1, 16):
        c = pos_counts[pos]
        t = c["total"] or 1
        pos_dist[pos] = {
            "home":  round(c["1"] / t * 100, 1),
            "draw":  round(c["X"] / t * 100, 1),
            "away":  round(c["2"] / t * 100, 1),
            "total": c["total"],
        }

    # ── Devret istatistikleri ──
    def avg(lst): return round(sum(lst)/len(lst), 1) if lst else 0
    def rate(lst, total_per_week=15):
        if not lst: return 0
        return round(sum(lst) / (len(lst) * total_per_week) * 100, 1)

    devret_stats = {
        "devret_weeks":         len(devret_x_counts),
        "normal_weeks":         len(normal_x_counts),
        "devret_avg_x":         avg(devret_x_counts),
        "normal_avg_x":         avg(normal_x_counts),
        "post_devret_avg_x":    avg(post_devret_x_counts),
        "devret_x_rate":        rate(devret_x_counts),
        "normal_x_rate":        rate(normal_x_counts),
        "post_devret_x_rate":   rate(post_devret_x_counts),
        "devret_x_distribution": devret_x_counts,
        "post_devret_winners":  [w["winner_15"] for w in weeks
                                 if not w["devret"] and _prev_devret_check(weeks, w)],
    }

    # ── Sezon fazı yüzdeleri ──
    phase_dist = {}
    for phase_key, pc in phase_counts.items():
        t = pc["total"] or 1
        phase_dist[phase_key] = {
            "home":        round(pc["1"] / t * 100, 1),
            "draw":        round(pc["X"] / t * 100, 1),
            "away":        round(pc["2"] / t * 100, 1),
            "weeks":       pc["weeks"],
            "devret_weeks": pc["devret"],
            "total_matches": pc["total"],
        }

    # ── Takım pozisyon yüzdeleri (min 3 maç) ──
    team_pos_dist = {}
    for team, pos_data in team_pos_stats.items():
        team_pos_dist[team] = {}
        for pos, c in pos_data.items():
            if c["total"] >= 3:
                t = c["total"]
                team_pos_dist[team][pos] = {
                    "win":    round(c["1"] / t * 100, 1),
                    "draw":   round(c["X"] / t * 100, 1),
                    "loss":   round(c["2"] / t * 100, 1),
                    "sample": t,
                }

    total_league   = sum(w.get("_filter", {}).get("league",  0) for w in weeks)
    total_milli    = sum(w.get("_filter", {}).get("milli",   0) for w in weeks)
    total_kupa     = sum(w.get("_filter", {}).get("kupa",    0) for w in weeks)
    total_unknown  = sum(w.get("_filter", {}).get("unknown", 0) for w in weeks)

    return {
        "total_weeks":   len(weeks),
        "total_matches": sum(len(w["matches"]) for w in weeks),
        "filtered": {
            "league":  total_league,
            "milli":   total_milli,
            "kupa":    total_kupa,
            "unknown": total_unknown,
        },
        "position_distribution": pos_dist,
        "devret_stats":  devret_stats,
        "phase_distribution": phase_dist,
        "team_position_stats": team_pos_dist,
    }


def _normalize_team(name: str) -> str | None:
    """Takım ismini normalize eder."""
    name = name.strip()
    SL_KEYWORDS = {
        "galatasaray": "GALATASARAY",
        "fenerbahçe":  "FENERBAHCE",
        "fenerbahce":  "FENERBAHCE",
        "beşiktaş":    "BESIKTAS",
        "besiktas":    "BESIKTAS",
        "trabzonspor": "TRABZONSPOR",
        "başakşehir":  "BASAKSEHIR",
        "basaksehir":  "BASAKSEHIR",
        "konyaspor":   "KONYASPOR",
        "alanyaspor":  "ALANYASPOR",
        "antalyaspor": "ANTALYASPOR",
        "kayserispor": "KAYSERISPOR",
        "kasımpaşa":   "KASIMPASA",
        "kasimpasa":   "KASIMPASA",
        "rizespor":    "RIZESPOR",
        "samsunspor":  "SAMSUNSPOR",
        "eyüpspor":    "EYUPSPOR",
        "eyupspor":    "EYUPSPOR",
        "bodrum":      "BODRUM",
        "adana":       "ADANA_DEMIRSPOR",
        "gaziantep":   "GAZIANTEP",
        "göztepe":     "GOZTEPE",
        "goztepe":     "GOZTEPE",
        "hatayspor":   "HATAYSPOR",
        "sivasspor":   "SIVASSPOR",
    }
    lower = name.lower()
    for key, val in SL_KEYWORDS.items():
        if key in lower:
            return val
    return None


def _prev_devret_check(weeks, week):
    """Bu haftadan önceki hafta devret miydi?"""
    idx = weeks.index(week)
    if idx == 0:
        return False
    return weeks[idx - 1]["devret"]


# ─── Rapor Çıktısı ───────────────────────────────────────────────────────────

def print_report(stats: dict) -> None:
    f = stats.get("filtered", {})
    print(f"\n{'='*65}")
    print(f"  SPOR TOTO ANALİZ RAPORU (Milli/Kupa Filtrelenmiş)")
    print(f"  {stats['total_weeks']} hafta | Toplam: {stats['total_matches']} maç")
    print(f"  ✅ Lig: {f.get('league',0)}  🚫 Milli: {f.get('milli',0)}  🚫 Kupa: {f.get('kupa',0)}")
    print(f"{'='*65}")

    # Pozisyon dağılımı
    print(f"\n📍 POZİSYON BAZLI SONUÇ DAĞILIMI")
    print(f"  {'Pos':>3}  {'Ev%':>6}  {'X%':>6}  {'Dep%':>6}  {'Maç':>5}  Not")
    print(f"  {'─'*55}")
    pos = stats["position_distribution"]
    notes = {
        3:  "⚠ EN FAZLA X",
        4:  "⚠ Dep güçlü",
        9:  "✓ Güvenli BANKO",
        12: "✓ En güvenli BANKO",
        14: "✓ X neredeyse yok",
        15: "⚠ X ile 1 eşit",
        6:  "X oranı yüksek",
        8:  "X oranı yüksek",
    }
    for p in range(1, 16):
        d = pos[p]
        note = notes.get(p, "")
        flag = ""
        if d["draw"] >= 35:   flag = "🔴"
        elif d["draw"] >= 28: flag = "🟡"
        elif d["home"] >= 52: flag = "🟢"
        print(f"  #{p:>2}  {d['home']:>5.1f}%  {d['draw']:>5.1f}%  {d['away']:>5.1f}%"
              f"  {d['total']:>4}  {flag} {note}")

    # Devret istatistikleri
    ds = stats["devret_stats"]
    print(f"\n🔄 DEVRET HAFTA ANALİZİ")
    print(f"  Devret haftaları     : {ds['devret_weeks']}")
    print(f"  Normal haftalar      : {ds['normal_weeks']}")
    print(f"  Devret ort.X/hafta   : {ds['devret_avg_x']}")
    print(f"  Normal  ort.X/hafta  : {ds['normal_avg_x']}")
    print(f"  DevretSonrası ort.X  : {ds['post_devret_avg_x']}")
    print(f"  Devret X oranı       : %{ds['devret_x_rate']}")
    print(f"  Normal X oranı       : %{ds['normal_x_rate']}")
    if ds["devret_x_distribution"]:
        print(f"  Devret haftaları X dağılımı: {ds['devret_x_distribution']}")

    # Sezon fazı
    print(f"\n📅 SEZON FAZI ANALİZİ")
    phase_labels = {"start": "🟢 Başı (May-Haz)", "middle": "🟡 Ortası (Tem-Ağu)", "end": "🔴 Sonu (Eyl-Ara)"}
    pd = stats["phase_distribution"]
    for pk, label in phase_labels.items():
        d = pd.get(pk, {})
        if not d or d.get("weeks", 0) == 0:
            continue
        devret_info = f"Devret: {d.get('devret_weeks',0)}/{d.get('weeks',0)}"
        print(f"  {label}")
        print(f"    Ev:%{d['home']:.1f}  X:%{d['draw']:.1f}  Dep:%{d['away']:.1f}"
              f"  |  {d['weeks']} hafta  |  {devret_info}")

    # Takım pozisyon analizi
    tp = stats["team_position_stats"]
    if tp:
        print(f"\n⚽ TAKIM POZİSYON ANALİZİ (min 3 maç)")
        priority = ["GALATASARAY","FENERBAHCE","BESIKTAS","TRABZONSPOR",
                    "BASAKSEHIR","SAMSUNSPOR","KONYASPOR","ALANYASPOR"]
        for team in priority:
            data = tp.get(team)
            if not data:
                continue
            print(f"\n  {team}")
            for p in sorted(data.keys()):
                d = data[p]
                signal = ""
                if d["win"] >= 80:  signal = "→ BANKO 1 ✅"
                elif d["win"] >= 60 and d["draw"] >= 25: signal = "→ ÇİFT 1X"
                elif d["win"] <= 40 and d["draw"] >= 40: signal = "→ KAOS 1X2"
                elif d["draw"] >= 50: signal = "→ ÇİFT 1X (X ağırlıklı)"
                print(f"    #{p}: W%{d['win']:.0f} D%{d['draw']:.0f} L%{d['loss']:.0f}"
                      f" ({d['sample']} maç) {signal}")


# ─── Çalıştır ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    filepath = sys.argv[1] if len(sys.argv) > 1 else "../../attached_assets/SporToto-sonuçlar_1778258863265.docx"

    print(f"Dosya okunuyor: {filepath}")
    weeks = parse_file(filepath)
    print(f"Parse edilen hafta sayısı: {len(weeks)}")

    stats = compute_stats(weeks)

    # JSON kaydet
    out_path = Path(__file__).parent / "spor_toto_stats.json"
    out_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\nJSON kaydedildi: {out_path}")

    # Terminal raporu
    print_report(stats)
