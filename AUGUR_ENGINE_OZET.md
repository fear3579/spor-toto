# AUGUR ENGINE — Proje Tam Özeti
## Spor Toto Tahmin Sistemi | Mayıs 2026

---

## İçindekiler

1. [Sistem Mimarisi](#1-sistem-mimarisi)
2. [Veri Kaynakları](#2-veri-kaynakları)
3. [Lambda Mimarisi K1-K9](#3-lambda-mimarisi-k1-k9)
4. [ML Sistemi](#4-ml-sistemi)
5. [LPRM v3](#5-lprm-v3)
6. [Monte Carlo](#6-monte-carlo)
7. [API-Football Entegrasyonu](#7-api-football-entegrasyonu)
8. [Suggest & Öneri Sistemi](#8-suggest--öneri-sistemi)
9. [Hafıza Sistemi](#9-hafıza-sistemi)
10. [Menüler](#10-menüler)
11. [Display & Human-Like Açıklama](#11-display--human-like-açıklama)
12. [Performans Metrikleri](#12-performans-metrikleri)
13. [Ağustos 2026 Planı](#13-ağustos-2026-planı)

---

## 1. Sistem Mimarisi

```
SPOR TOTO/ (268 dosya)
├── main.py                  ← Ana pipeline, 14 menü (0-9, A-D)
├── config.py                ← Tüm parametreler, lig ID haritası
├── analiz.py                ← 4 metrik + Brier/3 analizi
├── .env                     ← API_FOOTBALL_KEY (güvenli)
│
├── data/
│   ├── api_football.py      ← API-Football v3 istemcisi (18 metod)
│   ├── downloader.py        ← CSV indirici (football-data.co.uk)
│   └── sofascore.py         ← Yedek kaynak
│
├── model/
│   ├── lambda_calc.py       ← K1-K9 lambda motoru
│   ├── lprm.py              ← LPRM v2 (fallback)
│   ├── lprm_v3.py           ← LPRM v3 (aktif, main.py bağlı)
│   ├── ml_engine.py         ← AugurML + ResidualML
│   ├── monte_carlo.py       ← Simülasyon + Dixon-Coles
│   ├── suggest.py           ← Öneri motoru + KAOS_API
│   ├── position_bias.py     ← Pozisyon katsayıları (DOCX bazlı)
│   └── team_stats.py        ← Takım istatistik hesabı
│
├── memory/
│   ├── st_memory.py         ← Hafıza sistemi + devret tespiti
│   ├── devret_rule.py       ← Devret kuralları ve boost değerleri
│   └── season_transition.py ← Ağustos sezon geçiş scripti
│
├── tools/
│   ├── training_loader.py   ← 15 feature ML veri yükleyici
│   ├── ab_test.py           ← A/B test çekirdek
│   ├── run_ab_test.py       ← 4 senaryo (devret×pozisyon)
│   └── elo_fetcher.py       ← ClubElo indirici
│
├── modules/
│   └── analysis_menu.py     ← Backtest / LPRM / A/B menü
│
├── output/
│   └── display.py           ← Maç çıktısı + Human-Like açıklama
│
├── training/                ← 33 CSV (2324 / 2425 / 2526)
└── fd_cache/                ← İndirilen veri cache'i
```

**Bağımlılıklar:**

```
Python 3.11+
scikit-learn   → ML modeller + Platt kalibrasyonu
numpy / pandas → Veri işleme
scipy          → Optimizasyon (Dixon-Coles MLE)
requests       → API-Football HTTP
openpyxl       → Excel rapor
```

---

## 2. Veri Kaynakları

### football-data.co.uk (CSV)

```
11 lig × 3 sezon = 33 CSV dosyası
Toplam: 10,110 maç eğitim verisi

Lig listesi:
  T1   → Türkiye Süper Lig
  E0   → İngiltere Premier League
  SP1  → İspanya La Liga
  I1   → İtalya Serie A
  D1   → Almanya Bundesliga
  F1   → Fransa Ligue 1
  N1   → Hollanda Eredivisie
  B1   → Belçika Pro League
  P1   → Portekiz Primeira Liga
  G1   → Yunanistan Super League
  SC0  → İskoçya Premiership

Sezon ağırlıkları:
  2526 (güncel) × 1.0
  2425           × 0.7
  2324           × 0.4
```

### ClubElo (ELO Derecelendirmesi)

```
612 tarih cache (2023-07-28 → 2026-05-04)
ELO farkı → pos_diff_norm feature (Top-5 GB özelliği)
Menü C ile haftalık güncelleme
_load_elo_history() → tools/elo_history.json
```

### SporToto-sonuçlar.docx

```
54 hafta analizi, 731 lig maçı
Pozisyon bias katsayıları:
  BANKO güvenli: {1, 2, 5, 11, 12, 13, 14}
  Yüksek X:      {3, 8, 15}
  Dep güçlü:     {4}
  Devret X oranı: %30.3 (Normal: %18.5)
```

### API-Football v3

```
Base: https://v3.football.api-sports.io
API_KEY: .env → API_FOOTBALL_KEY
Cache: fd_cache/api_football/ (TTL bazlı)
Free plan: 100 istek/gün
Haftalık kullanım: ~86 istek (yeterli ✅)
```

---

## 3. Lambda Mimarisi K1-K9

Lambda sistemi Poisson baz tahmini üzerine 9 düzeltici katman uygular.
Her katman `lam_h` ve `lam_a` değerlerini günceller.

### K1 — Temel Dixon-Coles İstatistik

```python
# Takım ATT/DEF güçleri × lig ortalaması × ev avantajı
lam_h = att_h × def_a × lg_avg × ha   # ha = 1.08
lam_a = att_a × def_h × lg_avg
```

### K1b — xG API Override

```python
# API /fixture_statistics xG varsa → %40 ağırlık
if api_xg_available:
    lam_h = lam_h × 0.60 + api_xg_h × 0.40
else:
    lam_h = lam_h × 0.80 + xg_table × 0.20
```

### K2 — H2H Düzeltmesi

```
Son 5 H2H maç → ağırlıklı sonuç
API /head_to_head ile 2015'e kadar derinleştirildi
lam_h ve lam_a % bazlı düzeltme
```

### K3 — ClubElo Farkı

```python
elo_diff = (elo_h - elo_a) / 400.0
# ELO üstünlüğü → lambda bias
# 612 tarih cache'li
```

### K4 — Form Faktörü

```
Son 5 maçın GF/GA ortalaması
form_h_gf, form_h_ga feature bazlı
```

### K5 — xG/xGA Ağırlığı

```
Takım hücum/savunma kalitesi
Dixon-Coles × xG çarpanı
Sezon bazlı xG tablosu
```

### K6 — LPRM v3

```
LPRM_WHITELIST = {"SP1"}  ← backteste göre ayarlandı
Diğer liglerde: lambda'ya dokunmaz
SP1'de: lambda_adj_h/a ±%12 max
v2 fallback: hata durumunda devreye girer
```

### K7 — Pozisyon Bias

```python
# DOCX 54 hafta (731 maç) analizi
POS_BIAS = {
    3:  {"draw": -0.037},    # X yüksek
    8:  {"draw": -0.030},    # X yüksek
    15: {"draw": -0.020},    # X/1 eşit
    4:  {"lam_a": +0.030},   # Dep güçlü
    12: {"lam_h": +0.040, "draw": +0.023},  # BANKO
    14: {"lam_h": +0.060, "draw": +0.023},  # En güvenli
    ...
}
# suggest.py draw_thr'da da uygulanır
```

### K8 — ML Ensemble (AugurML)

```
LR×0.15 + GB×0.45 + MLP×0.20 + RF×0.20
+ Platt kalibrasyonu (%30 blend)
15 feature → P(1/X/2)
```

### K9 — Sakatlık/Ceza (API)

```python
# /injuries (haftalık) + /sidelined (sezon boyu)
POSITION_WEIGHT = {
    "FW": 0.08,   # Forvet → en kritik
    "CAM": 0.06,  # Hücum orta
    "CM": 0.03,   # Orta saha
    "GK": 0.05,   # Kaleci
    "CB": 0.02,   # Defans
}
impact = min(0.20, sum(weights))
lam_h *= (1.0 - impact)   # max -%20
```

**Lambda Final Sınır:**
```python
return max(lam_h, 0.15), max(lam_a, 0.15)
```

---

## 4. ML Sistemi

### AugurML — 4'lü Ensemble

#### 15 Feature Listesi (Haziran 2026: 28→15, korelasyonlu gruplar birleştirildi)

| Grup | Feature'lar |
|------|------------|
| Oran sinyali (4) | p1_pin, px_pin, p2_pin, odds_spread |
| Lambda (3) | lam_h, lam_a, lam_diff |
| Gol oranı (1) | over25_prob |
| Form (1) | form_diff |
| Line movement (2) | lm_h, lm_d |
| Bağlam (3) | season_week, is_home_fav, draw_rate_lig |
| Pozisyon (1) | pos_diff_norm |

#### Modeller

```
LR — Logistik Regresyon
  CV doğruluk: %54.4
  Multinomial, lbfgs solver, max_iter=500
  Güçlü: doğrusal ilişkiler

GB — Gradient Boosting
  CV doğruluk: %53.4
  60 ağaç, max_depth=3, learning_rate=0.12, subsample=0.80 (Android RAM uyumlu)
  Top-5 feature: p1_pin, p2_pin, odds_spread, lam_diff, pos_diff_norm

MLP — Yapay Sinir Ağı (YSA)
  CV doğruluk: %54.3
  Mimari: 15→32→16→3 (ReLU, Adam)
  early_stopping=True, validation_fraction=0.15

RF — Random Forest (YENİ)
  100 ağaç, max_depth=6, balanced sınıf ağırlığı
  min_samples_leaf=5, n_jobs=1 (Android uyumlu)
```

#### Ensemble Blend

```python
WEIGHTS = {"lr": 0.15, "gb": 0.45, "mlp": 0.20, "rf": 0.20}

# Platt Kalibrasyonu
for model in [gb, lr, mlp, rf]:
    cal = CalibratedClassifierCV(model, method="sigmoid", cv="prefit")
    cal.fit(X_arr, y_arr)

# Final blend
p1 = 0.70 × ham_p1 + 0.30 × kalibre_p1
# Brier iyileştirmesi: ~-0.003
```

#### Eğitim Sistemi

```
Menü B → Eğitim akışı:
  1. st_predictions.json (89 maç ST tahminleri)
  2. training/ CSV (10,021 maç, 11 lig, 3 sezon)
  3. NaN temizleme (4 satır atlandı)
  4. GB → LR → MLP → RF eğitimi
  5. Platt kalibrasyonu
  6. ml_model.pkl kaydı
  7. ResidualML kontrolü
```

### ResidualML (Ağustos Aktif)

```
Fikir: Oranların fiyatlamadığı bilgiyi öğren
Hedef: actual_1 - base_p1 (delta regresyon)

X: Odds-dışı özellikler
  elo_diff_norm, form_delta, pos_diff
  injury_h, injury_a, rest_days_h/a
  h2h_win_rate, market_move, season_week_norm

3× GradientBoostingRegressor (P1, PX, P2)
BLEND_LAMBDA = 0.30 (delta katkı ağırlığı)
MAX_DELTA    = 0.15 (±%15 klip)

Şu an: R²=-0.02 → devre dışı (R²>0.01 şartı)
Ağustos: Injuries/form verisiyle aktif
```

---

## 5. LPRM v3

### Nasıl Çalışıyor

```python
get_lprm_v3_result(
    home, away, league_code, season,
    match_date=None, past_seasons=["2425","2324"]
)
```

### 4 Sinyal

```
1. Bağlamsal Form (ev)
   Son N maçın ağırlıklı puan ortalaması
   Ev/dep ayrımı, yakın maçlar daha ağır

2. Bağlamsal Form (dep)
   Aynı yöntem, deplasman performansı

3. H2H Skoru
   Geçmiş H2H → ağırlıklı sonuç
   Yakın tarih > eski tarih
   API H2H ile 2015'e kadar

4. Güç Farkı
   Lig sıralama bandı: ÜST / ORTA / ALT
   Sıra farkı → güç sinyali
```

### Ağırlık Matrisi

```python
def _get_weights(n_current):
    if n_current >= MIN_MATCHES:
        return {"form": 0.40, "h2h": 0.30, "power": 0.30}
    else:
        return {"form": 0.30, "h2h": 0.20, "power": 0.50}
```

### Çıktı

```python
{
    "lprm_score":   float,    # -1..+1 (pozitif=ev üstün)
    "lambda_adj_h": float,    # 1.0 ± %12
    "lambda_adj_a": float,
    "confidence":   float,    # 0..1
    "detail":       dict,
}
```

### Backtest Sonuçları

```
Tüm liglerle LPRM:
  T1:  Brier +0.0039 ❌ Zararlı
  E0:  Brier +0.0024 ❌ Zararlı
  D1:  Brier +0.0038 ❌ Zararlı
  SP1: Brier +0.0016 ⚪ Nötr → Whitelist'e alındı
  I1:  Brier +0.0034 ❌ Zararlı
  F1:  Brier +0.0023 ❌ Zararlı

Karar: LPRM_WHITELIST = {"SP1"}
v2 Fallback: LPRM v3 hata verirse v2 devreye girer
```

---

## 6. Monte Carlo

### Fonksiyonlar

```python
poisson_analytical(lam_h, lam_a, league_code)
    # Dixon-Coles τ düzeltmesi
    # Lig bazlı rho (D1=-0.11, I1=-0.15, T1=-0.13)
    # → (p1, px, p2)

monte_carlo_with_ci(lam_h, lam_a, n=10000)
    # %95 güven aralıkları
    # ci_width: belirsizlik ölçüsü

monte_carlo_batch(scenarios)
    # Çoklu senaryo karşılaştırma

shin_implied_probs(odds_h, odds_d, odds_a)
    # Kitap marjı düzeltmesi

kelly_fraction(prob, odds)
    # Optimal bahis boyutu

compute_entropy(p1, px, p2)
    # Belirsizlik ölçümü (0..ln3)
```

### Dixon-Coles Düzeltmesi

```python
# Düşük skorlu maçlarda Poisson'dan sapma düzeltmesi
DIXON_COLES_RHO = {
    "T1": -0.13, "E0": -0.12, "SP1": -0.14,
    "I1": -0.15, "D1": -0.11, "F1": -0.13,
    "N1": -0.10, "B1": -0.12, "P1": -0.13,
}
# τ(0,0), τ(1,0), τ(0,1), τ(1,1) düzeltmesi
```

---

## 7. API-Football Entegrasyonu

### APIFootball Sınıfı (18 Metod)

```python
# Temel endpoint'ler
.fixtures(league_id, season, date, status)
.injuries(fixture_id)
.sidelined(team_id)           # YENİ — uzun süreli sakat
.standings(league_id, season)
.predictions(fixture_id)
.leagues(country)

# Gelişmiş endpoint'ler
.team_statistics(team_id, league_id, season)
.fixture_statistics(fixture_id)
.head_to_head(team1_id, team2_id, last_n=10)
.fixture_events(fixture_id)   # YENİ — gol/kırmızı kart

# Yardımcı
.find_fixture_id(league_code, season, home, away, date)
.get_team_id(team_name, league_id, season)
.status()
```

### Cache Sistemi

```
TTL (Time-To-Live):
  fixtures:    2 saat
  injuries:    6 saat
  standings:   24 saat
  leagues:     168 saat (1 hafta)
  predictions: 4 saat

Konum: fd_cache/api_football/
Anahtar: MD5(endpoint + params)
```

### Menü Entegrasyonu

```
Menü 1 (Haftalık Analiz):
  /standings      → güncel lig sırası → pos_diff_norm
  /teams/stat     → home_win_rate, btts_rate
  /head_to_head   → H2H 2015+ derinleştir
  /fixture_stat   → xG API override (K1b)
  /injuries       → haftalık sakat
  /sidelined      → sezon boyu sakat (K9)
  /predictions    → KAOS_API disagreement

Menü 8 (Salı Güncelleme):
  /fixtures       → otomatik sonuç senkronizasyonu
  /fixture_events → kırmızı kart kaydı
```

### Haftalık İstek Bütçesi

```
/fixtures:           30 istek (15 maç × 2 tarih)
/injuries:           15 istek (15 fixture)
/sidelined:          22 istek (11 lig × 2 takım)
/standings:          11 istek (11 lig)
/predictions:        15 istek (15 maç)
/teams/statistics:   11 istek (11 lig)
/fixture_statistics: 15 istek
/fixture_events:     15 istek (Menü 8)
────────────────────────────────────
Toplam: ~134 istek/hafta
Free plan: 100/gün ✅ yeterli
```

---

## 8. Suggest & Öneri Sistemi

### Öneri Sınıfları

```
BANKO: güven > 0.700, entropy < 0.75
       Pozisyon {1,2,5,11,12,13,14}

TEK:   tek kesin seçim

ÇİFT:  ikili güvence (1X, 2X, 1X2)

KAOS:  entropy > 0.88 veya KAOS_API
       3 seçenek → maximum kapsama
```

### draw_thr Düzeltmeleri

```python
base = 0.29
# Pozisyon bazlı (K7):
draw_thr += get_draw_thr_adjust(position)
# Rejim guard:
if recent_draw_rate > 0.32: draw_thr -= 0.02
if recent_draw_rate < 0.22: draw_thr -= 0.02
# Devret haftası:
if is_devret_week: draw_thr -= 0.03  # X kolaylaşır
```

### KAOS_API Disagreement Detector

```python
def disagreement_check(p1, px, p2, fixture_id):
    api_pred = api.predictions(fixture_id)
    max_diff = max(|p1-api_p1|, |px-api_px|, |p2-api_p2|)
    if max_diff > 0.20: return "KAOS_API"
    if max_diff > 0.10: return "WARN"
    return "OK"

# KAOS_API → öneri KAOS 1X2'ye dönüşür
```

---

## 9. Hafıza Sistemi

### st_memory.py

```python
# Adaptif eşikler
get_adaptive_thresholds()     → BANKO/ÇİFT eşiği

# Devret tespiti
is_devret_week(week_id)       → bool
record_devret(week_id, bilen_15, devret_etti)
get_devret_status()           → {devret_haftasi, beklenen_x}

# Menü 2 — sonuç girişi sonrası soru:
# "15 bilen var mıydı? (sayı/Enter): "
```

### devret_rule.py

```python
get_devret_adjustment(mem):
    if devret_haftasi:
        return {
            "x_bias_boost":     +0.05,   # recent_draw_rate artar
            "kaos_spread_mult":  1.30,   # KAOS eşiği genişler
            "banko_thr_add":    +0.03,   # BANKO daha az
            "beklenen_x":        15.8,   # devret X beklentisi
        }
    # Devret X oranı: %30.3 (Normal: %18.5)
```

### season_transition.py

```bash
# Ağustos başında çalıştır:
python memory/season_transition.py          # dry run
python memory/season_transition.py --run    # gerçek geçiş

# Otomatik:
  ST_SEASON_TAG: "2526" → "2627"
  ST_WEEK_OFFSET: 36 → 42
  Küme düşenler → T1_XG'den kaldırılır
  Promosyon gelenler → T1_XG'ye eklenir
```

---

## 10. Menüler

```
╔════════════════════════════════════════════╗
║  1  Haftalık Analiz  (Cuma — liste gelince) ║
║  2  Sonuçları Gir  (manuel + devret soru)   ║
║  3  Öğrenme Hafızası Özeti                  ║
║  4  Cache Sil  (verileri yeniden indir)     ║
║  5  Hızlı Mod  (10k simülasyon)             ║
║  6  Geçmiş Sezonları İndir  (oran DB)       ║
║  7  Cache Durumu Göster                     ║
║  8  Güncel Sezon + Sonuç  (Salı + API)      ║
║  9  Sıfırla  (Hafıza + Excel)               ║
║  0  Backtest  (1.Tek 2.Toplu 3.LPRM 4.A/B) ║
║  A  Performans Analizi  (4 metrik + Brier)  ║
║  B  ML Model Eğitimi  (4'lü + Platt + RF)  ║
║  C  ELO Tam Güncelleme  (ClubElo cache)    ║
║  D  Senaryo Analizi  (What-If)  ← YENİ    ║
╚════════════════════════════════════════════╝
```

### Menü D — Senaryo Analizi

```
Senaryo Karşılaştırması:
  BAZ (mevcut)        1=54% X=27% 2=19% λH=1.52 λA=1.18
  Ev yıldız eksik     1=48% X=29% 2=23%  (-%12 gol)
  Dep yıldız eksik    1=59% X=25% 2=16%  (-%12 gol)
  Tarafsız saha       1=50% X=28% 2=22%  (ev avan. yok)
  Devret haftası      1=48% X=35% 2=17%  (X +%30)

En Olası Skorlar:
  1-0 (1)  %14.2  ███████
  1-1 (X)  %11.8  █████
  0-0 (X)   %9.3  ████
  2-1 (1)   %8.7  ████
  ...
```

### Menü 0 — Backtest Modları

```
Mod 1: Tek Lig/Sezon Backtest
Mod 2: Toplu (5584 maç, tüm ligler, tüm sezonlar)
Mod 3: LPRM Raporu (ON/OFF Brier karşılaştırması)
Mod 4: A/B Test
  Senaryo A: devret=OFF, pozisyon=OFF (baseline)
  Senaryo B: devret=OFF, pozisyon=ON
  Senaryo C: devret=ON,  pozisyon=OFF
  Senaryo D: devret=ON,  pozisyon=ON (tam sistem)
```

---

## 11. Display & Human-Like Açıklama

### Maç Çıktısı

```
 #5  MANCHESTER CITY  vs  ASTON VILLA    CIFT 1X   2  🎯H=0.71 🟢EV
     └─ Man City hafif favori (P1=%52) | Ev gol bek. yüksek (Δ=+0.42) |
        LPRM Ev üstün (+0.18) | H2H ev %67 (9 maç) | #5 güvenli slot
```

### _human_explain() Fonksiyonu

```python
# Her maç için otomatik gerekçe üretir
_human_explain(
    fd_home, fd_away, p1, px, p2, label,
    lam_h, lam_a,           # lambda farkı yorumu
    lprm_result,            # LPRM sinyali
    h2h_pre,                # H2H istatistikleri
    h_st, a_st,             # standings bilgisi
    position,               # pozisyon notu
)
# → "GS güçlü favori | Ev gol bek. yüksek | LPRM Ev +0.21 | ÇİFT"
```

### Göstergeler

```
💎 Value edge    → model prob > implied prob
🎯 Düşük entropy → güvenilir tahmin (H<0.80)
⚡ Yüksek entropy → belirsiz maç (H>1.05)
🟢EV             → LPRM güçlü ev sinyali
🔴DEP            → LPRM güçlü dep sinyali
H2H: 5W3D2L      → H2H özeti (son 10 maç)
📊 Profil        → geçmiş maç olasılık profili
```

---

## 12. Performans Metrikleri

### ST37-ST42 Haftalık Sonuçlar

| Hafta | Doğru | Toplam | Kapsama | Brier/3 |
|-------|-------|--------|---------|---------|
| ST37 | 10 | 15 | %66.7 | — |
| ST38 | 14 | 15 | **%93.3** | 0.1652 |
| ST39 | 11 | 15 | %73.3 | 0.2176 |
| ST40 | 11 | 15 | %73.3 | 0.1718 |
| ST41 | 9 | 15 | %60.0 | 0.2286 |
| ST42 | 10 | 14 | %71.4 | 0.2074 |
| **TOPLAM** | **65** | **89** | **%73.0** | **0.1981** |

### 4 Metrik

```
Kupon Kapsama: %73.0  → actual ∈ pred seti
Saf Argmax:    %55.4  → max(P1,PX,P2) == actual
Top-2 Hit:     %79.7  → actual ∈ top-2 olasılık
TEK Doğruluk:  %57.1  → sadece TEK öneriler
```

### Brier Referansları

```
Mükemmel:  < 0.190
İyi:       < 0.220  ← Sistemimiz: 0.1981 ✅
Orta:      < 0.260
Referans:  Pinnacle ~0.190
Rastgele:  ~0.222
Naive:     ~0.250
```

### Toplu Backtest (5584 maç)

```
Toplam doğruluk: %50.9  Brier: 0.2011 ✅

En iyi:
  Süper Lig 24/25:   %57.6  Brier=0.1854
  Premier League 23/24: %56.8  Brier=0.1910

Zayıf:
  Bundesliga 24/25:  %45.4  Brier=0.2146
  Ligue 1 23/24:     %45.4  Brier=0.2168
```

---

## 13. Ağustos 2026 Planı

### Otomatik (1 Ağustos)

```python
# config.py _current_season() otomatik:
ST_SEASON_TAG = "2627"  # 2526'dan geçiş
# Sezon ağırlıkları kayar:
# 2526 → 0.70, 2425 → 0.35, 2324 → 0.10
```

### Elle Yapılacaklar (İlk Hafta)

```bash
# 1. Küme düşen/promosyon kesinleştir
# memory/season_transition.py içini güncelle:
RELEGATED_2526 = ["...", "...", "..."]
PROMOTED_2627  = ["...", "...", "..."]

# 2. Geçiş scriptini çalıştır
python memory/season_transition.py --run

# 3. Menü 4 → Cache sil
# 4. Menü 6 → Geçmiş sezonları indir
# 5. Menü C → ELO tam güncelle
# 6. Menü B → Yeniden eğit (4'lü ensemble + RF + Platt)
```

### Seçenek B Kararı (Ağustos ortası)

```
Koşul: Pro API ($19/ay) alınırsa

enrich_training.py (yazılacak):
  10,000 maç × /fixture_statistics → xG
  10,000 maç × /teams/statistics → btts, win_rate
  20,000 API isteği → 3 günde tamamlanır
  Sonuç: 15 → 24+ feature

Beklenen iyileşme:
  Brier: 0.1981 → ~0.1910
  Kupon: %73 → ~%75.5

Karar: Ağustos'ta değerlendir
```

### Sonra (Ağustos sonu)

```
ResidualML aktif (300+ maç → R² pozitif)
LPRM whitelist genişlet (T1/E0 A/B test)
Hibrit ensemble: 4 model + ResidualML delta
API /players/statistics → player rating feature
```

---

## Ek: Teknoloji Kararları

### Neden Bu Modeller?

| Model | Neden? | Alternatif | Neden Değil? |
|-------|--------|-----------|-------------|
| GB | Tabular veri için güçlü, feature importance | XGBoost/LightGBM | C derleme gerektirir, Android'de zor |
| LR | Yorumlanabilir, hızlı | SVM | Büyük veri yavaş |
| MLP 32-16 | Doğrusal olmayan örüntü | LSTM/Transformer | Video/dizi verisi yok, RAM sınırlı |
| RF | GB'den farklı bias, çeşitlilik | ExtraTrees | Benzer, RF yeterli |
| Poisson | Gol sayısı doğal dağılımı | Weibull | Futbol standardı |
| Dixon-Coles | Düşük skor düzeltmesi | Frank copula | Çok karmaşık |

### Neden Eklemedik?

```
❌ GNN/Graph Neural Network
   Video verisi, grafik yapısı gerektirir
   Android'de çalışmaz

❌ LSTM/Transformer
   Dizi verisi gerektirir (maç dizisi farklı)
   RAM tüketimi Android için fazla

❌ Optik Takip / Video Analizi
   Kamera girişi yok
   Gerçek zamanlı işlem kapasitesi yok

❌ Deep Learning xG Modeli
   Pas/şut pozisyonu verisi yok
   API verisi formasyona göre değil pozisyona göre
```

---

*Son güncelleme: 27 Mayıs 2026*
*Platform: Android / Pydroid3 + Termux*
*Geliştirici: Solo (Emrah)*
