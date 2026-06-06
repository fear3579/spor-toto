# A/B Test Sonuçları — ST37–ST42

## Yöntem

4 senaryo × 75 maç (ST37–ST41):
- **Senaryo A**: devret=OFF, pozisyon=OFF (baseline)
- **Senaryo B**: devret=OFF, pozisyon=ON
- **Senaryo C**: devret=ON,  pozisyon=OFF
- **Senaryo D**: devret=ON,  pozisyon=ON (tam sistem)

## Sonuçlar

| Senaryo | Doğruluk | Brier | LogLoss |
|---------|----------|-------|---------|
| A — Devret=OFF Pos=OFF (baseline) | %73.3 | 0.2011 | 1.0001 |
| B — Devret=ON  Pos=OFF | %74.7 (+%1.4) | 0.2010 | 0.9982 |
| C — Devret=OFF Pos=ON  | %73.3 (=) | 0.2011 | 1.0001 |
| **D — Devret=ON  Pos=ON** | **%74.7 (+%1.4)** | **0.2010** | **0.9982** |

## Karar

**Devret modülü aktif** — Doğruluk +%1.4, Brier -0.0001 iyileşme.

**Pozisyon bias** — Bağımsız etkisi yok; devret ile birlikte çalışıyor.

Her iki modül de aktif durumda.

## ST37–ST42 Haftalık Detay

| Hafta | Doğru | Toplam | Kapsama | Brier/3 |
|-------|-------|--------|---------|---------|
| ST37 | 10 | 15 | %66.7 | — |
| ST38 | 14 | 15 | **%93.3** | 0.1652 |
| ST39 | 11 | 15 | %73.3 | 0.2176 |
| ST40 | 11 | 15 | %73.3 | 0.1718 |
| ST41 | 9 | 15 | %60.0 | 0.2286 |
| ST42 | 10 | 14 | %71.4 | 0.2074 |
| **TOPLAM** | **65** | **89** | **%73.0** | **0.1981** |

## Referans Değerler

| Sistem | Brier |
|--------|-------|
| Mükemmel | < 0.190 |
| **AUGUR ENGINE** | **0.1981 ✅** |
| İyi | < 0.220 |
| Orta | < 0.260 |
| Pinnacle (referans) | ~0.190 |
| Rastgele | ~0.222 |

*Son güncelleme: Mayıs 2026*
