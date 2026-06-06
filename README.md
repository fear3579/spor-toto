# Spor Toto — AUGUR ENGINE

## Kurulum
```bash
pip install requests beautifulsoup4 lxml pandas numpy openpyxl
```

## Çalıştırma
```bash
python main.py
```

## Klasör Yapısı
```
st_project/
│
├── main.py              ← Giriş noktası, menü, pipeline
├── config.py            ← Tüm sabitler, URL'ler, CFG
│                           ST_SEASON_TAG ve ST_WEEK_OFFSET artık
│                           CURRENT_SEASON'dan OTOMATİK türetilir.
│                           Elle güncelleme gerekmez.
│
├── input/
│   ├── parser.py        ← OCR parse, liste çekme (4 kaynak)
│   └── team_resolver.py ← Fuzzy isim eşleştirme
│
├── data/
│   ├── downloader.py    ← CSV indirme, cache, fixtures
│   └── odds_history.py  ← OranDB + ProfilDB (3-boyutlu)
│
├── model/
│   ├── team_stats.py    ← Ev/dep ayrı istatistik, rolling form
│   ├── lambda_calc.py   ← 7-katmanlı λ hesabı:
│   │                       Katman 1-3: stats + form + ClubElo
│   │                       Katman 4:   Sezon fazı (start/middle/end)
│   │                       Katman 5:   Devret haftası bias
│   │                       Katman 6:   LPRM v2 (taktik hafıza)
│   │                       Katman 7:   Pozisyon bias (model/position_bias.py)
│   ├── position_bias.py           ← Pozisyon katsayısı yükleyici
│   ├── position_bias_generated.py ← update_stats.py çıktısı (otomatik)
│   │                                 686 saf lig maçı / 51 hafta
│   │                                 Elle düzenleme: YAPMA
│   ├── monte_carlo.py   ← Simülasyon, blend, bağlam düzeltme
│   ├── suggest.py       ← BANKO/TEK/ÇİFT/KAOS karar katmanı
│   ├── lprm.py          ← LPRM v2 — 4 katmanlı pozisyon tekrar modeli
│   └── season_phase.py  ← Sezon fazı: banko/kaos otomatik ayarı
│
│   ⚠ Not: Pozisyon katsayıları config.py'de DEĞİL, position_bias.py
│     ve position_bias_generated.py üzerinden yönetilir. Bu daha
│     modüler ve otomatik güncellenebilir bir tasarımdır.
│
├── coupon/
│   └── optimizer.py     ← Bütçe opt, kupon bölme (A/B/C)
│
├── output/
│   ├── display.py       ← Terminal çıktısı, profil satırları
│   └── xlsx_export.py   ← 3 sayfalık Excel raporu
│
├── memory/
│   ├── st_memory.py        ← STMemory (7 katman, kalıcı öğrenme)
│   ├── devret_rule.py      ← Devret haftası kuralı
│   └── season_transition.py← Sezon geçiş otomasyonu
│
├── tools/
│   ├── update_stats.py              ← Haftalık DOCX → istatistik güncelleme
│   ├── migrate_team_pos_to_memory.py← spor_toto_stats.json → st_memory.json
│   ├── ab_test.py                   ← A/B test çerçevesi
│   └── run_ab_test.py               ← A/B test çalıştırıcı (Menü dışı)
│
├── analysis/
│   ├── lprm_report.py      ← LPRM karşılaştırma raporu
│   └── ab_test_sonuclari.md← A/B test sonuçları (ST37-41 arşiv)
│
└── fd_cache/            ← Otomatik oluşur, CSV cache
    ├── T1_2526.pkl
    ├── fixtures.pkl
    └── ...
```

## Haftalık Kullanım
| Gün | Yapılacak | Menü |
|-----|-----------|------|
| Cuma | Yeni liste → Analiz | 1 |
| Cumartesi-Pazartesi | Maçlar oynanıyor | — |
| Salı | Sonuçlar → Öğren | 8 |

## Yeni Sezon Geçişi (1 Ağustos)
Çoğu adım artık otomatik. Sıra şu şekilde:

| Adım | Otomatik mı? | Yapılacak |
|------|-------------|-----------|
| CURRENT_SEASON güncellemesi | ✅ OTOMATİK | `_current_season()` Ağustos'ta 2627'ye geçer |
| ST_SEASON_TAG güncellemesi | ✅ OTOMATİK | `_st_season_tag()` CURRENT_SEASON'dan türetir |
| ST_WEEK_OFFSET güncellemesi | ⚠ YARI-OTOMATİK | `config.py → _ST_SEASON_CONFIG["2627"]` doğrula |
| Küme düşen takım arşivi | ✅ OTOMATİK | `season_transition.run_auto_transition(mem)` |
| Yükselen takım hibrit ısıtma | ✅ OTOMATİK | `season_transition.run_auto_transition(mem)` |
| Cache temizleme | ✅ OTOMATİK | `run_auto_transition(mem)` → fd_cache/ temizler |
| Geçmiş sezon CSV indirme | ⏸ MANUEL | Menü 6 → 2627 sezonunu indir |
| Süper Lig XG tablosu | ⏸ MANUEL | `config.py → T1_XG` güncelle (transfer dönemi) |
| Memory sıfırlama kararı | ⚠ KARAR | `season_transition.get_memory_reset_recommendation(mem)` |

**Tek komutla durum raporu:**
```python
from memory.season_transition import run_auto_transition, print_auto_transition_report
report = run_auto_transition(mem, cache_dir="fd_cache")
print_auto_transition_report(report)
```

## A/B Test Sonuçları (ST37–ST41, 75 maç)

| Senaryo | Doğruluk | Brier | LogLoss |
|---------|----------|-------|---------|
| Devret=OFF Pos=OFF (baseline) | %73.3 | 0.2011 | 1.0001 |
| Devret=ON  Pos=OFF | %74.7 (+%1.4) | 0.2010 | 0.9982 |
| Devret=OFF Pos=ON  | %73.3 (=) | 0.2011 | 1.0001 |
| **Devret=ON  Pos=ON** | **%74.7 (+%1.4)** | **0.2010** | **0.9982** |

Her iki modül de aktif — detay için `analysis/ab_test_sonuclari.md`.

## Hafıza Dosyaları (silinmez!)
- `st_memory.json`        → Ana öğrenme hafızası
- `st_memory_backup.json` → Otomatik yedek
- `st_predictions.json`   → Haftalık tahmin logu


## Yeni Özellikler (Mayıs 2026)

### Menü Güncellemeleri
```
B  ML Model Eğitimi     (AugurML 28 feature + ResidualML)
C  ELO Tam Güncelleme   (Tarihe göre ClubElo)
```

### API-Football Entegrasyonu (data/api_football.py)
- `/fixtures` → Menü 8 otomatik sonuç senkronizasyonu
- `/injuries` → Lambda Katman 9 (sakat/ceza düzeltmesi)
- `/standings` → Güncel lig tablosu (pos_diff_norm)
- `/predictions` → KAOS_API disagreement detector

### ML Mimarisi
- AugurML: 28 feature, LR+GB+MLP ensemble
- ResidualML: delta öğrenme (Ağustos 2026'da aktif)
- ClubElo ELO entegrasyonu (612 tarih)

### Lambda Katmanları (K1-K9)
1. Poisson baz
2. H2H
3. ClubElo ELO
4. Form faktörü
5. xG/xGA
6. LPRM (SP1 whitelist)
7. Pozisyon bias
8. ML ensemble
9. Sakatlık/Ceza (API-Football)

### Sezon Geçişi (Ağustos 2026)
```
python memory/season_transition.py --run
```
