# Spor Toto — AUGUR ENGINE

## Kurulum
```bash
pip install requests beautifulsoup4 lxml pandas numpy openpyxl scikit-learn
```

## Çalıştırma
```bash
python main.py
```

## Klasör Yapısı
```
st_project/
│
├── main.py              ← Giriş noktası, 14 menü (1-9, A-D)
├── config.py            ← Tüm sabitler, lig ID haritası
│                           ST_SEASON_TAG ve ST_WEEK_OFFSET OTOMATİK türetilir.
├── analiz.py            ← 4 metrik + Brier/3 analizi
│
├── input/
│   ├── parser.py        ← OCR parse, liste çekme (4 kaynak)
│   └── team_resolver.py ← Fuzzy isim eşleştirme
│
├── data/
│   ├── downloader.py    ← CSV indirme, cache, fixtures
│   ├── api_football.py  ← API-Football v3 istemcisi (18 metod, K9)
│   ├── odds_history.py  ← OranDB + ProfilDB (3-boyutlu)
│   └── sofascore.py     ← Yedek kaynak
│
├── model/
│   ├── lambda_calc.py   ← K1-K9 lambda motoru (9 katman)
│   ├── lprm_v3.py       ← LPRM v3 (aktif, SP1 whitelist)
│   ├── lprm.py          ← LPRM v2 (fallback)
│   ├── lprm_standings.py← LPRM puan tablosu yardımcısı
│   ├── ml_engine.py     ← AugurML (15 feature, 4'lü ensemble) + ResidualML
│   ├── monte_carlo.py   ← Simülasyon + Dixon-Coles
│   ├── suggest.py       ← BANKO/TEK/ÇİFT/KAOS karar katmanı
│   ├── bias_engine.py   ← Bias hesaplama motoru
│   ├── position_bias.py           ← Pozisyon katsayısı yükleyici
│   ├── position_bias_generated.py ← update_stats.py çıktısı (otomatik)
│   ├── team_stats.py    ← Ev/dep istatistik, rolling form
│   └── season_phase.py  ← Sezon fazı: banko/kaos otomatik ayarı
│
├── modules/             ← Ana modül parçaları (main.py'den ayrıştırıldı)
│   ├── analysis_menu.py ← Backtest, LPRM raporu, A/B test, senaryo analizi
│   ├── cache_ops.py     ← Cache yönetimi (temizle, indir, durum)
│   └── results_sync.py  ← CSV/API/DOCX sonuç eşleştirme
│
├── coupon/
│   └── optimizer.py     ← Bütçe opt, kupon bölme (A/B/C)
│
├── output/
│   ├── display.py       ← Terminal çıktısı + human-like açıklama
│   └── xlsx_export.py   ← 3 sayfalık Excel raporu
│
├── memory/
│   ├── st_memory.py        ← STMemory (7 katman, kalıcı öğrenme)
│   ├── devret_rule.py      ← Devret haftası kuralı
│   ├── season_transition.py← Sezon geçiş otomasyonu
│   ├── clv_tracker.py      ← Kapanış çizgisi değeri (CLV) takibi
│   ├── model_health.py     ← Model sağlık paneli
│   └── performance_xray.py ← Derinlemesine performans analizi
│
├── tools/
│   ├── training_loader.py           ← 15 feature ML veri yükleyici (3 sezon)
│   ├── update_stats.py              ← Haftalık DOCX → istatistik güncelleme
│   ├── elo_fetcher.py               ← ClubElo indirici
│   ├── ab_test.py                   ← A/B test çerçevesi
│   ├── run_ab_test.py               ← A/B test çalıştırıcı
│   ├── parse_spor_toto.py           ← ST DOCX parse aracı
│   ├── poisson_calibrator.py        ← Poisson kalibrasyon
│   ├── setup_training.py            ← Eğitim kurulum scripti
│   └── migrate_team_pos_to_memory.py← İstatistik → memory göçü
│
├── analysis/
│   ├── lprm_report.py      ← LPRM on/off karşılaştırma raporu
│   └── ab_test_sonuclari.md← A/B test sonuçları (ST37-42 arşiv)
│
└── fd_cache/            ← Otomatik oluşur, CSV cache
```

## Menüler
```
╔════════════════════════════════════════════╗
║  1  Haftalık Analiz  (Cuma — liste gelince) ║
║  2  Sonuçları Gir  (manuel + devret soru)   ║
║  3  Öğrenme Hafızası Özeti                  ║
║  4  Cache Sil  (verileri yeniden indir)     ║
║  5  ML Model Eğitimi  (4'lü + Platt)        ║
║  6  Güncelleme Merkezi  (CSV, ELO, bias)    ║
║  7  Test & Analiz Merkezi  (backtest, A/B)  ║
║  8  Güncel Sezon + Sonuç  (Salı + API)      ║
║  9  Sıfırla  (Hafıza + Excel)               ║
║  A  Performans Analizi  (4 metrik + Brier)  ║
║  B  ML Model Eğitimi  (argparse modu)       ║
║  C  ELO Tam Güncelleme  (ClubElo cache)    ║
║  D  Senaryo Analizi  (What-If)             ║
╚════════════════════════════════════════════╝
```

## Haftalık Kullanım
| Gün | Yapılacak | Menü |
|-----|-----------|------|
| Cuma | Yeni liste → Analiz | 1 |
| Cumartesi-Pazartesi | Maçlar oynanıyor | — |
| Salı | Sonuçlar → Öğren | 8 |

## Lambda Katmanları (K1-K9)
| Katman | İşlev |
|--------|-------|
| K1 | Poisson baz (Dixon-Coles istatistik) |
| K1b | xG API override (%40 ağırlık) |
| K2 | H2H düzeltmesi (2015'e kadar) |
| K3 | ClubElo farkı (612 tarih cache) |
| K4 | Form faktörü (son 5 maç) |
| K5 | xG/xGA ağırlığı |
| K6 | LPRM v3 (SP1 whitelist, v2 fallback) |
| K7 | Pozisyon bias (DOCX 54 hafta analizi) |
| K8 | ML ensemble (15 feature, 4 model) |
| K9 | Sakatlık/Ceza (API-Football /injuries) |

## ML Mimarisi
- **AugurML**: 15 feature, LR×0.15 + GB×0.45 + MLP×0.20 + RF×0.20
- **Platt kalibrasyonu**: %30 blend
- **ResidualML**: delta öğrenme (R²>0.01 şartı, Ağustos 2026'da aktif)
- **Eğitim**: Menü 5 veya B → `ml_model.pkl`

## Yeni Sezon Geçişi (1 Ağustos)

| Adım | Otomatik mı? | Yapılacak |
|------|-------------|-----------|
| CURRENT_SEASON güncellemesi | ✅ OTOMATİK | `_current_season()` Ağustos'ta 2627'ye geçer |
| ST_SEASON_TAG güncellemesi | ✅ OTOMATİK | `_st_season_tag()` CURRENT_SEASON'dan türetir |
| ST_WEEK_OFFSET güncellemesi | ⚠ YARI-OTOMATİK | `config.py → _ST_SEASON_CONFIG["2627"]` doğrula |
| Küme düşen/yükselen arşivi | ✅ OTOMATİK | `season_transition.run_auto_transition(mem)` |
| Cache temizleme | ✅ OTOMATİK | `run_auto_transition(mem)` → fd_cache/ temizler |
| Geçmiş sezon CSV indirme | ⏸ MANUEL | Menü 6 → Geçmiş Sezon İndir |
| Süper Lig XG tablosu | ⏸ MANUEL | `config.py → T1_XG` güncelle (transfer dönemi) |
| Memory sıfırlama kararı | ⚠ KARAR | `season_transition.get_memory_reset_recommendation(mem)` |

```python
from memory.season_transition import run_auto_transition, print_auto_transition_report
report = run_auto_transition(mem, cache_dir="fd_cache")
print_auto_transition_report(report)
```

## A/B Test Sonuçları (ST37–ST42, 89 maç)

| Senaryo | Doğruluk | Brier | LogLoss |
|---------|----------|-------|---------|
| Devret=OFF Pos=OFF (baseline) | %73.3 | 0.2011 | 1.0001 |
| Devret=ON  Pos=OFF | %74.7 (+%1.4) | 0.2010 | 0.9982 |
| Devret=OFF Pos=ON  | %73.3 (=) | 0.2011 | 1.0001 |
| **Devret=ON  Pos=ON** | **%74.7 (+%1.4)** | **0.2010** | **0.9982** |

Her iki modül de aktif — detay için `analysis/ab_test_sonuclari.md`.

## Performans (ST37–ST42)
| Metrik | Değer |
|--------|-------|
| Kupon Kapsama | %73.0 |
| Saf Argmax | %55.4 |
| Top-2 Hit | %79.7 |
| Brier/3 | 0.1981 ✅ |

## Hafıza Dosyaları (silinmez!)
- `st_memory.json`        → Ana öğrenme hafızası
- `st_memory_backup.json` → Otomatik yedek
- `st_predictions.json`   → Haftalık tahmin logu
