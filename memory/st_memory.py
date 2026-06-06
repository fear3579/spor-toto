# -*- coding: utf-8 -*-
from config import *
from input.team_resolver import _normalize
import sys, re, io, os, json, math, time, warnings
from datetime import datetime
from difflib import SequenceMatcher
import requests
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")

class STMemory:
    """
    Kalıcı uzun vadeli öğrenme hafızası.

    Dosyalar:
      st_memory.json         — Ana hafıza (asla silinmez)
      st_memory_backup.json  — Otomatik yedek (her kayıtta güncellenir)
      st_predictions.json    — Haftalık tahmin logu

    Katmanlar:
      1. Adaptif eşikler      — BANKO/ÇİFT eşikleri doğruluğa göre ayarlanır
      2. Takım hafızası       — Model sapması takımlar için düzeltilir
      3. Bağlam hafızası      — Zirve/Düşme/Denk bağlamları doğruluğu takip edilir
      4. Profil hafızası      — Oran × Sıra kombinasyonları tarihsel olasılık tutar
      5. Hata desenleri       — Sistem nerede yanılıyor, hangi durumda
      6. Human-Like seriler   — Takım form serileri
      7. Sürpriz hafızası     — Yüksek güvende yanılmalar

    Uzun vadeli davranış:
      - Veriler HİÇBİR ZAMAN silinmez (sadece birikimlir)
      - Yedek dosyaya her kayıtta yazılır
      - Yeterli veri birikince (30+ maç) eşik optimizasyonu başlar
      - Profil tabanlı düzeltmeler 5+ örnek sonrası devreye girer
    """

    def __init__(self):
        self.mem = self._load()

    # ═══════════════════════════════════════════════════════
    # YÜKLEME / KAYDETME
    # ═══════════════════════════════════════════════════════

    def _default(self) -> dict:
        return {
            "version":         MEMORY_VERSION,
            "created":         datetime.now().isoformat(),
            "last_updated":    None,
            "total_weeks":     0,
            "total_preds":     0,
            "correct":         0,

            # ── Katman 1: Adaptif eşikler ─────────────────
            "adaptive": {
                "banko_threshold":  0.65,
                "double_threshold": 0.40,
                "tek_threshold":    0.50,
                "kaos_spread":      0.10,
                "context_boosts": {
                    "ZIRVE":      0.04,
                    "DUSME":      0.035,
                    "DUSME_BOTH": 0.025,
                    "DENK":       0.02,
                    "UCURUM":    -0.02,
                },
                "history": [],   # [{week, acc, threshold, change}]
            },

            # ── Katman 2: Takım hafızası ──────────────────
            # {norm_isim: {H,D,A,pred_H,pred_D,pred_A,correct,total,
            #              name, home_H,home_D,home_A,away_H,away_D,away_A}}
            "teams": {},

            # ── Katman 3: Bağlam hafızası ─────────────────
            "context_acc": {
                "ZIRVE":      {"correct": 0, "total": 0},
                "DUSME":      {"correct": 0, "total": 0},
                "DUSME_BOTH": {"correct": 0, "total": 0},
                "DENK":       {"correct": 0, "total": 0},
                "NONE":       {"correct": 0, "total": 0},
            },

            # ── Katman 4: Profil hafızası ─────────────────
            # {profil_key: {H,D,A,n, model_H_avg, model_D_avg, model_A_avg}}
            # Örn: "cok_favori_ev_zirve_dusme"
            "profiles": {},

            # ── Katman 5: Hata desenleri ──────────────────
            # Model belirli koşullarda sistematik hata yapıyor mu?
            "error_patterns": {
                # {pattern: {wrong:n, total:n, typical_error: "model 1 dedi D oldu"}}
                # Örn: "banko_ev_cok_favori": favori evde BANKO deyip beraberlik
                "banko_fail_home_fav":  {"wrong":0,"total":0},
                "banko_fail_away_fav":  {"wrong":0,"total":0},
                "kaos_actual_draw":     {"wrong":0,"total":0},
                "high_conf_draw_miss":  {"wrong":0,"total":0},
            },

            # ── Katman 6: Seri takibi ─────────────────────
            "streaks": {},

            # ── Katman 7: Sürpriz hafızası ────────────────
            # Sınırsız — silinmez, sezon bazında gruplanır
            "surprises": {},   # {sezon: [{week,mac,pred,actual,conf,profile}]}

            # ── Oran bin kalibrasyonu ─────────────────────
            "odds_bins": {},

            # ── Haftalık özet geçmişi ─────────────────────
            "weekly_history": [],  # [{week, correct, total, acc, thresholds}]
            "chronic_profiles": {},  # takım DNA — lprm_v2 tarafından güncellenir

            # ── Sezon özeti ───────────────────────────────
            "season_summary": {},  # {sezon: {correct, total, acc}}
        }

    def _load(self) -> dict:
        default = self._default()

        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)

                # Versiyon kontrolü + migrate
                saved_ver = saved.get("version", 1)
                # String versiyonları int'e çevir ("2.0" → 2, "2" → 2)
                if isinstance(saved_ver, str):
                    try:
                        saved_ver = int(float(saved_ver))
                    except (ValueError, TypeError):
                        saved_ver = 1
                if saved_ver < MEMORY_VERSION:
                    saved = self._migrate(saved, saved_ver)

                # Deep merge: yeni anahtarlar kaybedilmez
                def _deep_merge(base, update):
                    for k, v in update.items():
                        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                            _deep_merge(base[k], v)
                        else:
                            base[k] = v
                _deep_merge(default, saved)
                return default

            except (OSError, IOError, ValueError, TypeError, KeyError) as e:
                print(f"  [Hafıza] Yüklenemedi: {e} — Yedekten deneniyor...")
                # Yedekten yükle
                if os.path.exists(MEMORY_BACKUP):
                    try:
                        with open(MEMORY_BACKUP, "r", encoding="utf-8") as f:
                            saved = json.load(f)
                        print(f"  [Hafıza] Yedekten yüklendi ✓")
                        return saved
                    except (OSError, IOError, ValueError, TypeError, KeyError):
                        pass
                print(f"  [Hafıza] Yeni hafıza oluşturuluyor.")

        return default

    def _migrate(self, saved: dict, from_ver: int) -> dict:
        """Eski hafıza versiyonunu yeni formata çevir."""
        print(f"  [Hafıza] v{from_ver} → v{MEMORY_VERSION} güncelleniyor...")
        # v1→v2: surprises list→dict
        if from_ver < 3 and isinstance(saved.get("surprises"), list):
            old_surprises = saved["surprises"]
            saved["surprises"] = {}
            if old_surprises:
                saved["surprises"]["eski"] = old_surprises
        # Profil yoksa ekle
        if "profiles" not in saved:
            saved["profiles"] = {}
        # Hata desenleri yoksa ekle
        if "error_patterns" not in saved:
            saved["error_patterns"] = {
                "banko_fail_home_fav": {"wrong":0,"total":0},
                "banko_fail_away_fav": {"wrong":0,"total":0},
                "kaos_actual_draw":    {"wrong":0,"total":0},
                "high_conf_draw_miss": {"wrong":0,"total":0},
            }
        # weekly_history yoksa ekle
        if "weekly_history" not in saved:
            saved["weekly_history"] = []
        if "season_summary" not in saved:
            saved["season_summary"] = {}
        saved["version"] = MEMORY_VERSION
        return saved

    def save(self):
        """
        Ana hafızayı kaydet + çift katmanlı atomik yedek.

        Yedek stratejisi:
          1. st_memory_backup.json — her kayıtta atomik güncelleme
          2. st_memory_daily.json  — günde 1 kez güncellenen snapshot
             (backup da bozulsa diye ikinci güvence)
        """
        import shutil
        self.mem["last_updated"] = datetime.now().isoformat()

        # ── 1. Anlık yedek: mevcut dosyanın atomik kopyası ──────────
        if os.path.exists(MEMORY_FILE):
            try:
                backup_tmp = MEMORY_BACKUP + ".tmp"
                shutil.copy2(MEMORY_FILE, backup_tmp)
                os.replace(backup_tmp, MEMORY_BACKUP)
            except (OSError, IOError) as e:
                print(f"  [Hafıza] Anlık yedek yazılamadı: {e}")

        # ── 2. Günlük snapshot — 20 saatte 1 kez ────────────────────
        daily_path = MEMORY_FILE.replace(".json", "_daily.json")
        try:
            needs_daily = True
            if os.path.exists(daily_path):
                age_h = (time.time() - os.path.getmtime(daily_path)) / 3600
                needs_daily = age_h >= 20
            if needs_daily and os.path.exists(MEMORY_FILE):
                daily_tmp = daily_path + ".tmp"
                shutil.copy2(MEMORY_FILE, daily_tmp)
                os.replace(daily_tmp, daily_path)
        except (OSError, IOError):
            pass

        # ── 3. Ana dosya — atomik yazım ─────────────────────────────
        try:
            tmp_file = MEMORY_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.mem, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, MEMORY_FILE)
        except (OSError, IOError, ValueError, TypeError) as e:
            print(f"  [Hafıza] Kaydedilemedi: {e}")

    # ═══════════════════════════════════════════════════════
    # ÖĞRENME — ANA FONKSİYON
    # ═══════════════════════════════════════════════════════

    def _learn_from_week(self, week_id: str, matches: list):
        """
        Bir haftanın maçlarından öğren.
        Her maç sadece BİR KEZ sayılır — kısmi giriş desteklenir.
        """
        year = datetime.now().year
        season_code = f"{str(year-1)[2:]}{str(year)[2:]}" \
            if datetime.now().month < 8 else \
            f"{str(year)[2:]}{str(year+1)[2:]}"

        # Daha önce öğrenilmiş maçları takip et
        learned_key = f"learned_{week_id}"
        if "learned_matches" not in self.mem:
            self.mem["learned_matches"] = {}
        already_learned = set(self.mem["learned_matches"].get(learned_key, []))

        week_correct      = 0
        week_total        = 0
        week_brier_sum    = 0.0
        week_brier_n      = 0
        week_logloss_sum  = 0.0
        week_logloss_n    = 0

        for m in matches:
            if not m.get("actual"):
                continue

            # Daha önce öğrenildiyse atla
            match_id = f"{m['no']}_{m.get('mac','')}"
            if match_id in already_learned:
                week_correct += int(self._is_correct(m))
                week_total   += 1
                continue

            actual   = m["actual"]
            pred_raw = m.get("pred", "?")
            ctx      = m.get("ctx","").replace("[","").replace("]","")
            odds     = m.get("odds", {})
            o1       = odds.get("1")
            ox       = odds.get("X")
            o2       = odds.get("2")
            p1       = m.get("P1", 0) / 100
            px       = m.get("PX", 0) / 100
            p2       = m.get("P2", 0) / 100
            max_p    = max(p1, px, p2)

            # actual → H/D/A normalize (1/X/2/0 formatlarını da kabul et)
            _norm_act = {"1":"H","X":"D","2":"A","0":"D"}
            actual = _norm_act.get(actual, actual)

            # Doğruluk hesabı
            pred_ftr = FTR_MAP.get(pred_raw)
            if pred_ftr:
                correct = (pred_ftr == actual)
            else:
                # Çoklu seçim: 1X, 2X, 1X2, 12
                choices = [FTR_MAP.get(c) for c in pred_raw if c in FTR_MAP]
                correct = actual in choices if choices else False

            week_total   += 1
            week_correct += int(correct)
            self.mem["total_preds"] += 1
            self.mem["correct"]     += int(correct)

            # ── Brier Skoru ───────────────────────────────────
            # Brier = Σ(p_i - o_i)² / n_outcomes
            # o_i = 1 gerçekleşen sonuç için, 0 diğerleri için
            if p1 + px + p2 > 0:
                o_h = 1.0 if actual == "H" else 0.0
                o_d = 1.0 if actual == "D" else 0.0
                o_a = 1.0 if actual == "A" else 0.0
                brier_m = ((p1-o_h)**2 + (px-o_d)**2 + (p2-o_a)**2) / 3.0
                week_brier_sum += brier_m
                week_brier_n   += 1

                # Log-Loss (cross-entropy) — epsilon ile sıfır kaçınma
                import math
                eps = 1e-9
                p_actual = p1 if actual=="H" else (px if actual=="D" else p2)
                logloss_m = -math.log(max(p_actual, eps))
                week_logloss_sum += logloss_m
                week_logloss_n   += 1

            # Bu maç öğrenildi olarak işaretle
            already_learned.add(match_id)

            # ── K1: Bağlam ────────────────────────────────
            ctx_key = ctx if ctx in self.mem["context_acc"] else "NONE"
            self.mem["context_acc"][ctx_key]["total"]   += 1
            self.mem["context_acc"][ctx_key]["correct"] += int(correct)

            # ── K2: Takım hafızası ────────────────────────
            self._update_team(m.get("home",""), "home", actual, pred_raw)
            self._update_team(m.get("away",""), "away", actual, pred_raw)

            # ── K3: Oran bin ──────────────────────────────
            if all(x is not None for x in [o1, ox, o2]):
                self._update_odds_bin(o1, ox, o2, actual, p1, px, p2)

            # ── K4: Profil hafızası ───────────────────────
            if all(x is not None for x in [o1, ox, o2]):
                prf_label = m.get("profile_label","")
                if prf_label:
                    self._update_profile(prf_label, actual, p1, px, p2)

            # ── K5: Hata desenleri ────────────────────────
            self._update_error_patterns(
                pred_raw, actual, correct, max_p, o1, ctx
            )

            # ── K6: Seri ─────────────────────────────────
            self._update_streak(m.get("home",""), "home", actual)
            self._update_streak(m.get("away",""), "away", actual)

            # ── K7: Sürpriz hafızası ─────────────────────
            if not correct and max_p >= 0.65:
                if season_code not in self.mem["surprises"]:
                    self.mem["surprises"][season_code] = []
                self.mem["surprises"][season_code].append({
                    "week":       week_id,
                    "mac":        m.get("mac",""),
                    "pred":       pred_raw,
                    "actual":     actual,
                    "confidence": round(max_p*100, 1),
                    "odds":       f"{o1}/{ox}/{o2}" if o1 else "-",
                    "ctx":        ctx,
                })

        # Öğrenilen maçları kaydet
        self.mem["learned_matches"][learned_key] = list(already_learned)

        # Haftalık özet — aynı hafta varsa güncelle, yoksa ekle
        if week_total > 0:
            existing_idx = next((i for i, h in enumerate(
                self.mem["weekly_history"]) if h["week"] == week_id), None)

            # ── GÜVENLİK: completed hafta değiştirilemez ──────
            if existing_idx is not None:
                if self.mem["weekly_history"][existing_idx].get("status") == "completed":
                    return  # ASLA dokunma

            # Hafta tamamlandı mı? (15/15 sonuç girildi mi)
            total_in_week   = len(matches)
            actual_in_week  = len([m for m in matches if m.get("actual")])
            is_complete     = (actual_in_week >= total_in_week and total_in_week >= 10)

            # Confidence calibration
            conf_scores = []
            for m in matches:
                if not m.get("actual"): continue
                p1 = m.get("P1",0)/100; px = m.get("PX",0)/100; p2 = m.get("P2",0)/100
                best_p = max(p1, px, p2)
                conf_scores.append(best_p)
            avg_conf = round(sum(conf_scores)/len(conf_scores),3) if conf_scores else None
            acc_rate = round(week_correct/week_total,3) if week_total else 0
            overconf = round(avg_conf - acc_rate, 3) if avg_conf else None

            # ── ZORLUK KATSAYISI ──────────────────────────────
            # Beraberlik sayısı, KAOS maç sayısı ve sürpriz sayısına göre
            # _to_st: H/D/A ve 1/X/2 ve 0 → ST format (1/X/2)
            _to_st = {"H":"1","D":"X","A":"2","1":"1","X":"X","2":"2","0":"X"}
            actual_draws   = sum(1 for m in matches
                                 if _to_st.get(m.get("actual",""),"") == "X")
            pred_kaos      = sum(1 for m in matches
                                 if "X" in (m.get("pred","") or "")
                                 and "1" in (m.get("pred","") or "")
                                 and "2" in (m.get("pred","") or ""))
            # Sürpriz: yüksek güvende yanlış
            surprises = 0
            for m in matches:
                if not m.get("actual"): continue
                p1 = m.get("P1",0)/100; px=m.get("PX",0)/100; p2=m.get("P2",0)/100
                best_p = max(p1,px,p2)
                pred_raw = m.get("pred","")
                _actual_pred = _to_st.get(m.get("actual",""), "")
                if best_p >= 0.55 and not (_actual_pred and _actual_pred in pred_raw):
                    surprises += 1

            # Zorluk formülü:
            # bera_factor: her beraberlik +0.1 (max +0.5)
            # kaos_factor: az KAOS varken çok bera gelirse daha zor
            # surprise_factor: her sürpriz +0.1
            n = week_total or 1
            bera_ratio     = actual_draws / n
            kaos_ratio     = pred_kaos / n
            surprise_ratio = surprises / n

            # Zorluk 0-1 arası: 0=kolay, 1=çok zor
            difficulty = round(
                min(1.0,
                    bera_ratio * 0.5 +          # beraberlik katkısı
                    (bera_ratio - kaos_ratio) * 0.3 +  # beklenmez bera
                    surprise_ratio * 0.2         # sürpriz katkısı
                ), 3)
            difficulty = max(0.0, difficulty)

            # Zorluk etiket
            if difficulty >= 0.35:   diff_label = "⚡ Çok Zor"
            elif difficulty >= 0.25: diff_label = "🔴 Zor"
            elif difficulty >= 0.15: diff_label = "🟡 Orta"
            else:                    diff_label = "🟢 Kolay"

            # Düzeltilmiş başarı: zorluğa göre normalize
            # Formül: adj_acc = acc / (1 - difficulty * 0.3)
            adj_acc = round(min(1.0, acc_rate / max(0.5, 1 - difficulty * 0.3)), 3)

            entry = {
                "week":          week_id,
                "correct":       week_correct,
                "total":         week_total,
                "acc":           acc_rate,
                "adj_acc":       adj_acc,
                "difficulty":    difficulty,
                "diff_label":    diff_label,
                "actual_draws":  actual_draws,
                "thr_b":         self.mem["adaptive"]["banko_threshold"],
                "brier":         round(week_brier_sum/week_brier_n, 4)
                                 if week_brier_n else None,
                "logloss":       round(week_logloss_sum/week_logloss_n, 4)
                                 if week_logloss_n else None,
                "status":        "completed" if is_complete else "pending",
                "calibration":   {
                    "avg_confidence": avg_conf,
                    "accuracy":       acc_rate,
                    "overconfidence": overconf,
                } if is_complete and avg_conf else None,
            }

            if existing_idx is not None:
                self.mem["weekly_history"][existing_idx] = entry
            else:
                self.mem["total_weeks"] += 1
                self.mem["weekly_history"].append(entry)
            self.mem["weekly_history"] = self.mem["weekly_history"][-200:]

            # ── MODEL ÖĞRENME: sadece completed haftalarda ────
            if not is_complete:
                self.save()
                return  # Pending → model update yapma

            # Sezon özeti
            if season_code not in self.mem["season_summary"]:
                self.mem["season_summary"][season_code] = {
                    "correct": 0, "total": 0}
            ss = self.mem["season_summary"][season_code]
            ss["correct"] = sum(h["correct"] for h in self.mem["weekly_history"]
                                if season_code in h.get("week", ""))
            ss["total"]   = sum(h["total"]   for h in self.mem["weekly_history"]
                                if season_code in h.get("week", ""))

            # ── ROLLING ACCURACY → DİNAMİK EŞİK ─────────────
            completed_weeks = [h for h in self.mem["weekly_history"]
                               if h.get("status") == "completed"]
            if len(completed_weeks) >= 2:
                last3 = completed_weeks[-3:]
                rolling_acc = sum(h["acc"] for h in last3) / len(last3)
                base_thr = 0.65
                thr_dynamic = round(base_thr + (rolling_acc - 0.5) * 0.2, 3)
                thr_dynamic = max(0.60, min(0.75, thr_dynamic))
                self.mem["adaptive"]["banko_threshold"] = thr_dynamic

        # Adaptif eşik optimizasyonu
        if self.mem["total_preds"] >= MIN_SAMPLES:
            self._optimize_thresholds(week_id)

    # ═══════════════════════════════════════════════════════
    # KATMAN GÜNCELLEYİCİLER
    # ═══════════════════════════════════════════════════════

    def _update_team(self, team: str, venue: str,
                     actual: str, pred: str):
        if not team:
            return
        key = _normalize(team)
        if key not in self.mem["teams"]:
            self.mem["teams"][key] = {
                "H":0,"D":0,"A":0,
                "pred_H":0,"pred_D":0,"pred_A":0,
                "correct":0,"total":0,"name":team,
                "home_H":0,"home_D":0,"home_A":0,
                "away_H":0,"away_D":0,"away_A":0,
            }
        t = self.mem["teams"][key]
        t[actual] = t.get(actual,0) + 1
        t["total"] += 1
        # Mekan bazlı
        venue_key = f"{venue}_{actual}"
        t[venue_key] = t.get(venue_key, 0) + 1

        pred_ftr = FTR_MAP.get(pred)
        if pred_ftr:
            t[f"pred_{pred_ftr}"] = t.get(f"pred_{pred_ftr}", 0) + 1
            if pred_ftr == actual:
                t["correct"] += 1

    def _update_odds_bin(self, o1, ox, o2, actual, p1, px, p2):
        k = f"{round(float(o1),1)}-{round(float(ox),1)}-{round(float(o2),1)}"
        if k not in self.mem["odds_bins"]:
            self.mem["odds_bins"][k] = {
                "H":0,"D":0,"A":0,"n":0,
                "model_H":0.0,"model_D":0.0,"model_A":0.0,
            }
        b = self.mem["odds_bins"][k]
        b[actual] = b.get(actual, 0) + 1
        n_old = b["n"]
        b["n"] += 1
        # Kayan ortalama model olasılığı
        b["model_H"] = (b["model_H"]*n_old + p1) / b["n"]
        b["model_D"] = (b["model_D"]*n_old + px) / b["n"]
        b["model_A"] = (b["model_A"]*n_old + p2) / b["n"]

    def _update_profile(self, profile_label: str, actual: str,
                        p1: float, px: float, p2: float):
        """Profil bazlı hafızayı güncelle."""
        if profile_label not in self.mem["profiles"]:
            self.mem["profiles"][profile_label] = {
                "H":0,"D":0,"A":0,"n":0,
                "model_H":0.0,"model_D":0.0,"model_A":0.0,
            }
        p = self.mem["profiles"][profile_label]
        p[actual] = p.get(actual,0) + 1
        n_old = p["n"]
        p["n"] += 1
        p["model_H"] = (p["model_H"]*n_old + p1) / p["n"]
        p["model_D"] = (p["model_D"]*n_old + px) / p["n"]
        p["model_A"] = (p["model_A"]*n_old + p2) / p["n"]

    def _update_error_patterns(self, pred: str, actual: str,
                                correct: bool, max_p: float,
                                o1, ctx: str):
        """Sistematik hata desenlerini izle."""
        ep = self.mem["error_patterns"]

        # BANKO evde favoride yanılma
        if pred == "1" and max_p >= 0.65 and actual != "H":
            ep["banko_fail_home_fav"]["total"] += 1
            if not correct:
                ep["banko_fail_home_fav"]["wrong"] += 1

        # BANKO deplasmanda yanılma
        if pred == "2" and max_p >= 0.65 and actual != "A":
            ep["banko_fail_away_fav"]["total"] += 1
            if not correct:
                ep["banko_fail_away_fav"]["wrong"] += 1

        # KAOS gerçekte beraberlik miydi?
        if pred in ("1X2","1X","X2","12") and actual == "D":
            ep["kaos_actual_draw"]["wrong"] += 1
            ep["kaos_actual_draw"]["total"] += 1

        # Yüksek güvende beraberlik kaçırma
        if max_p >= 0.60 and actual == "D" and pred != "X":
            ep["high_conf_draw_miss"]["wrong"] += 1
            ep["high_conf_draw_miss"]["total"] += 1
        elif max_p >= 0.60 and actual != "D":
            ep["high_conf_draw_miss"]["total"] += 1

    def _update_streak(self, team: str, venue: str, actual: str):
        if not team:
            return
        key = _normalize(team)
        if key not in self.mem["streaks"]:
            self.mem["streaks"][key] = {
                "streak_type":None,"streak_n":0,
                "last5":"","last10":"","name":team,
            }
        s = self.mem["streaks"][key]
        won  = (venue=="home" and actual=="H") or \
               (venue=="away"  and actual=="A")
        drew = actual == "D"
        res  = "W" if won else ("D" if drew else "L")

        s["streak_type"] = res if s.get("streak_type") != res else s["streak_type"]
        s["streak_n"] = (s.get("streak_n",0)+1
                         if s.get("streak_type") == res
                         else 1)
        s["streak_type"] = res
        s["last5"]  = (s.get("last5","")  + res)[-5:]
        s["last10"] = (s.get("last10","") + res)[-10:]

    # ═══════════════════════════════════════════════════════
    # ADAPTİF EŞİK OPTİMİZASYONU
    # ═══════════════════════════════════════════════════════

    def _optimize_thresholds(self, week_id: str = ""):
        """
        Son 30 haftanın doğruluğuna göre eşikleri ayarla.

        Kurallar:
        - Yüksek güven (BANKO) doğruluğu < %55 → eşiği yükselt
        - Yüksek güven doğruluğu > %72 → eşiği düşür
        - Bağlam doğruluğu düşükse → boost'u küçült
        - Profil bazlı yanılma varsa → o profil için uyarı ekle
        """
        ad = self.mem["adaptive"]
        recent = self.mem["weekly_history"][-30:]
        if len(recent) < 5:
            return

        # Genel doğruluk
        tot = sum(w["total"] for w in recent)
        cor = sum(w["correct"] for w in recent)
        if tot == 0:
            return
        acc = cor / tot

        # Banko eşiği ayarı
        cur_b = ad["banko_threshold"]
        new_b = cur_b
        if acc < 0.52:
            new_b = min(cur_b + 0.02, 0.75)
        elif acc < 0.58:
            new_b = min(cur_b + 0.01, 0.72)
        elif acc > 0.72:
            new_b = max(cur_b - 0.01, 0.58)

        if abs(new_b - cur_b) >= 0.005:
            ad["banko_threshold"] = round(new_b, 3)
            change = f"{cur_b:.2f}→{new_b:.2f}"
            print(f"  [Öğrenme] BANKO eşiği: {change} "
                  f"(son 30h doğruluk: %{acc*100:.0f})")
            # Tarih kaydı
            ad["history"].append({
                "week":   week_id,
                "acc":    round(acc, 3),
                "old":    round(cur_b, 3),
                "new":    round(new_b, 3),
            })
            ad["history"] = ad["history"][-50:]

        # Bağlam boost optimizasyonu
        for ctx, d in self.mem["context_acc"].items():
            if d["total"] < 15:
                continue
            ctx_acc = d["correct"] / d["total"]
            boost_key = ctx.upper()
            if boost_key in ad["context_boosts"]:
                cur_boost = ad["context_boosts"][boost_key]
                # Bağlam başarı oranı düşükse boost azalt
                if ctx_acc < 0.45 and cur_boost > 0.01:
                    ad["context_boosts"][boost_key] = round(cur_boost - 0.005, 3)
                elif ctx_acc > 0.65 and cur_boost < 0.08:
                    ad["context_boosts"][boost_key] = round(cur_boost + 0.005, 3)

    # ═══════════════════════════════════════════════════════
    # UYGULAMA FONKSİYONLARI
    # ═══════════════════════════════════════════════════════

    def apply_team_bias(self, home_fd: str, away_fd: str,
                        p1: float, px: float, p2: float) -> tuple:
        """Takım hafızasından model sapması düzeltmesi."""
        MIN_T = 8

        def _bias(team, is_home):
            t = self.mem["teams"].get(_normalize(team))
            if not t or t.get("total", 0) < MIN_T:
                return 0.0
            n = t["total"]
            # Mekan bazlı gerçek oran
            if is_home:
                real_w = t.get("home_H", t.get("H",0)) / n
            else:
                real_w = t.get("away_A", t.get("A",0)) / n
            pred_w = t.get("pred_H" if is_home else "pred_A", 0) / n
            return (real_w - pred_w) * 0.15

        b_h = _bias(home_fd, True)
        b_a = _bias(away_fd, False)
        new_p1 = max(0.02, p1 + b_h)
        new_p2 = max(0.02, p2 + b_a)
        new_px = max(0.02, 1.0 - new_p1 - new_p2)
        t = new_p1 + new_px + new_p2
        return new_p1/t, new_px/t, new_p2/t

    def get_adaptive_thresholds(self) -> tuple:
        ad = self.mem["adaptive"]
        return (ad.get("banko_threshold", 0.65),
                ad.get("double_threshold", 0.40))

    def get_adaptive_boosts(self) -> dict:
        """Öğrenilmiş bağlam boost değerlerini döndür."""
        return self.mem["adaptive"].get("context_boosts", {})

    def get_week_status(self, week_id: str) -> str:
        """Hafta durumunu döndür: 'pending', 'completed', 'not_found'."""
        for h in self.mem.get("weekly_history", []):
            if h["week"] == week_id:
                return h.get("status", "pending")
        return "not_found"

    def is_week_completed(self, week_id: str) -> bool:
        return self.get_week_status(week_id) == "completed"

    def get_pending_weeks(self) -> list:
        """Sonuçları eksik haftaları listele."""
        return [h["week"] for h in self.mem.get("weekly_history", [])
                if h.get("status") == "pending"]

    def get_active_constraints(self) -> dict:
        """
        Hafızadan aktif kısıtlar üret — derin versiyon.

        1. Dinamik BANKO eşiği (banko_wrong oranına göre)
        2. Hafta bazlı trend (momentum)
        3. Takım bazlı güçlü bias (sapma güçlendir)
        4. Bağlam trend ayrımı (son 3 hafta vs genel)
        5. KAOS → X pattern (mevcut, güçlendirildi)
        """
        ep   = self.mem.get("error_patterns", {})
        ctx  = self.mem.get("context_acc", {})
        ad   = self.mem.get("adaptive", {})
        wh   = self.mem.get("weekly_history", [])
        teams= self.mem.get("teams", {})

        constraints = {
            "kaos_prefer_x":    False,
            "no_banko_ctx":     set(),
            "ci_penalty":       0.0,
            "banko_threshold":  ad.get("banko_threshold", 0.65),
            "momentum":         0.0,   # pozitif → agresif, negatif → muhafazakar
            "strong_teams":     {},    # takım → {"home_bias", "away_bias"}
            "context_recent":   {},    # bağlam → son3 doğruluk
        }

        # ── 1. DİNAMİK BANKO EŞİĞİ ──────────────────────────
        # Gerçek anahtarlar: banko_fail_home_fav + banko_fail_away_fav
        bw_total = (ep.get("banko_fail_home_fav",{}).get("total",0) +
                    ep.get("banko_fail_away_fav",{}).get("total",0))
        bw_wrong = (ep.get("banko_fail_home_fav",{}).get("wrong",0) +
                    ep.get("banko_fail_away_fav",{}).get("wrong",0))
        if bw_total >= 5:
            bw_rate = bw_wrong / bw_total
            if bw_rate >= 0.45:
                new_thr = min(0.75, constraints["banko_threshold"] + 0.02)
                constraints["banko_threshold"] = round(new_thr, 3)
                constraints["ci_penalty"] += 0.10
            elif bw_rate <= 0.20:
                new_thr = max(0.60, constraints["banko_threshold"] - 0.01)
                constraints["banko_threshold"] = round(new_thr, 3)

        # ── 2. HAFTA BAZLI TREND (MOMENTUM) ──────────────────
        recent3 = wh[-3:] if len(wh) >= 3 else wh
        older   = wh[-8:-3] if len(wh) >= 8 else wh[:-3]

        if len(recent3) >= 2 and len(older) >= 2:
            acc_recent = sum(h["correct"] for h in recent3) / max(
                sum(h["total"] for h in recent3), 1)
            acc_older  = sum(h["correct"] for h in older) / max(
                sum(h["total"] for h in older), 1)
            momentum = acc_recent - acc_older
            constraints["momentum"] = round(momentum, 3)

            # Momentum etkisi
            if momentum >= 0.10:
                # Yükseliyor → BANKO eşiğini hafifçe düşür
                constraints["banko_threshold"] = round(
                    max(0.60, constraints["banko_threshold"] - 0.01), 3)
            elif momentum <= -0.10:
                # Düşüyor → BANKO eşiğini yükselt
                constraints["banko_threshold"] = round(
                    min(0.75, constraints["banko_threshold"] + 0.02), 3)
                constraints["ci_penalty"] += 0.05

        # ── 3. TAKIM BAZLI GÜÇLÜ BİAS ────────────────────────
        MIN_TEAM = 10
        for team_key, t in teams.items():
            if t.get("total", 0) < MIN_TEAM:
                continue
            n = t["total"]

            # Ev galibiyet oranı
            home_win_real = t.get("home_H", 0) / n
            home_win_pred = t.get("pred_H", 0) / n
            home_bias = home_win_real - home_win_pred

            # Deplasman galibiyet oranı
            away_win_real = t.get("away_A", 0) / n
            away_win_pred = t.get("pred_A", 0) / n
            away_bias = away_win_real - away_win_pred

            # Güçlü sapma varsa kaydet (>%15)
            if abs(home_bias) >= 0.15 or abs(away_bias) >= 0.15:
                constraints["strong_teams"][team_key] = {
                    "home_bias":  round(home_bias, 3),
                    "away_bias":  round(away_bias, 3),
                    "total":      n,
                }

        # ── 4. BAĞLAM TREND AYRIMI (son 3 hafta) ────────────
        # Her hafta kaydına bağlam bilgisi henüz yok — genel ctx kullan
        # ama son 3 hafta vs genel doğruluk farkına bak
        for ctx_name, d in ctx.items():
            if d.get("total", 0) < 5:
                continue
            ctx_acc = d["correct"] / d["total"]
            constraints["context_recent"][ctx_name] = round(ctx_acc, 3)

            # Genel %45 altı → o bağlamda BANKO yasak
            if ctx_acc < 0.45 and d["total"] >= 8:
                constraints["no_banko_ctx"].add(ctx_name)

        # ── 5. KAOS → X PATTERN (güçlendirildi) ─────────────
        kd = ep.get("kaos_actual_draw", {})
        if kd.get("total", 0) >= 5:
            rate = kd["wrong"] / kd["total"]
            if rate >= 0.60:
                constraints["kaos_prefer_x"] = True
                # %80+ ise ekstra CI cezası ekle (daha geniş seçim)
                if rate >= 0.80:
                    constraints["ci_penalty"] += 0.10

        return constraints

    def get_team_strong_bias(self, home_fd: str, away_fd: str,
                              p1: float, px: float, p2: float) -> tuple:
        """
        Güçlü takım bias'ı uygula.
        Normal apply_team_bias'tan daha agresif (%25 ağırlık vs %15).
        """
        constraints = self.get_active_constraints()
        strong = constraints.get("strong_teams", {})

        h_key = _normalize(home_fd)
        a_key = _normalize(away_fd)

        b_h = strong.get(h_key, {}).get("home_bias", 0.0) * 0.25
        b_a = strong.get(a_key, {}).get("away_bias", 0.0) * 0.25

        new_p1 = max(0.02, p1 + b_h)
        new_p2 = max(0.02, p2 + b_a)
        new_px = max(0.02, 1.0 - new_p1 - new_p2)
        t = new_p1 + new_px + new_p2
        return new_p1/t, new_px/t, new_p2/t

    def get_momentum_info(self) -> str:
        """Momentum bilgisini ekran için formatla."""
        wh = self.mem.get("weekly_history", [])
        if len(wh) < 2:
            return ""
        recent3 = wh[-3:]
        acc = sum(h["correct"] for h in recent3) / max(
            sum(h["total"] for h in recent3), 1)
        trend = ""
        if len(wh) >= 4:
            older = wh[-6:-3]
            if older:
                acc_old = sum(h["correct"] for h in older) / max(
                    sum(h["total"] for h in older), 1)
                diff = acc - acc_old
                trend = f" {'↑' if diff>0.05 else '↓' if diff<-0.05 else '→'}{diff*100:+.0f}%"
        return f"Son {len(recent3)}H: %{acc*100:.0f}{trend}"

    def get_error_warning(self) -> str:
        """Kritik hata desenlerini uyarı olarak döndür."""
        ep = self.mem.get("error_patterns", {})
        warnings = []

        kd = ep.get("kaos_actual_draw", {})
        if kd.get("total", 0) >= 5:
            rate = kd["wrong"] / kd["total"]
            if rate >= 0.60:
                warnings.append(f"⚠ KAOS→X hata %{rate*100:.0f} ({kd['wrong']}/{kd['total']})")

        bw_total = (ep.get("banko_fail_home_fav",{}).get("total",0) +
                    ep.get("banko_fail_away_fav",{}).get("total",0))
        bw_wrong = (ep.get("banko_fail_home_fav",{}).get("wrong",0) +
                    ep.get("banko_fail_away_fav",{}).get("wrong",0))
        if bw_total >= 5 and bw_wrong/bw_total >= 0.45:
            warnings.append(f"⚠ BANKO hata %{bw_wrong/bw_total*100:.0f} ({bw_wrong}/{bw_total})")

        return "  " + " | ".join(warnings) if warnings else ""

    def get_streak_info(self, team_fd: str) -> str:
        """Takımın mevcut serisini döndür (3+ maç)."""
        s = self.mem.get("streaks", {}).get(_normalize(team_fd))
        if not s or not s.get("streak_type"):
            return ""
        n   = s.get("streak_n", 0)
        typ = s.get("streak_type", "")
        if n >= 3:
            emoji = "🔥" if typ=="W" else ("❄️" if typ=="L" else "〰️")
            return f"{emoji}{typ}{n}"
        return ""

    # ═══════════════════════════════════════════════════════
    # LOG FONKSİYONLARI
    # ═══════════════════════════════════════════════════════

    def log_predictions(self, week_id: str, results: list,
                        raw_matches: list):
        log = self._load_pred_log()
        if week_id not in log:
            log[week_id] = {"created": datetime.now().isoformat(),
                            "matches": []}
        for r, m in zip(results, raw_matches):
            existing = [x for x in log[week_id]["matches"]
                        if x["no"] == r["no"]]
            prf = r.get("profile")
            entry = {
                "no":           r["no"],
                "mac":          r["mac"],
                "home":         m["home"],
                "away":         m["away"],
                "league":       m.get("league","?"),
                "pred":         r["oneri"].split()[1] if " " in r["oneri"] else "?",
                "pred_label":   r["oneri"],
                "P1":           r["P1"],
                "PX":           r["PX"],
                "P2":           r["P2"],
                "ctx":          r.get("ctx",""),
                "odds":         m.get("odds",{}),
                "actual":       existing[0].get("actual") if existing else None,
                "fd_match":     r.get("fd_match",""),
                "profile_label":prf.get("label","") if prf else "",
            }
            log[week_id]["matches"] = [
                x for x in log[week_id]["matches"] if x["no"] != r["no"]
            ] + [entry]
        self._save_pred_log(log)
        print(f"  Tahminler kaydedildi → {PRED_LOG_FILE} [{week_id}]")

    def enter_results(self):
        """
        Sonuç giriş modu.
        T = Toplu: sonuçları tek satırda gir (eksikler - ile atlanır)
        S = Sıralı: her maç için ayrı giriş
        """
        log = self._load_pred_log()
        if not log:
            print("  Kaydedilmiş tahmin yok.")
            return

        import re as _re2
        def _wk_sort(wid):
            _wm = _re2.match(r'ST(\d+)-(\d+)', wid)
            return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)
        weeks = sorted(log.keys(), key=_wk_sort, reverse=True)
        print("\n  Kayıtlı haftalar:")
        for i, w in enumerate(weeks[:10], 1):
            m_cnt   = len(log[w]["matches"])
            entered = sum(1 for x in log[w]["matches"] if x.get("actual"))
            print(f"    {i}. {w}  ({entered}/{m_cnt} sonuç girilmiş)")

        print(f"\n  Hafta seçin (1-{min(len(weeks),10)}): ", end="")
        try:
            sel = int(input().strip()) - 1
            if not (0 <= sel < len(weeks)):
                raise ValueError("Geçersiz seçim")
            week_id = weeks[sel]
        except (OSError, IOError, ValueError, TypeError, KeyError):
            print("  İptal.")
            return

        matches = log[week_id]["matches"]

        # ── Önce Sofascore'u otomatik dene ─────────────────────
        ss_results = {}
        try:
            from data.sofascore import fetch_results_sofascore
            print(f"\n  Sofascore'dan sonuçlar çekiliyor...")
            ss_results = fetch_results_sofascore(matches)
        except (OSError, IOError, ValueError, TypeError, RuntimeError) as e:
            print(f"  Sofascore erişilemedi: {e}")

        ss_found = {no: ev for no, ev in ss_results.items()
                    if ev.get("result")}

        if ss_found:
            print(f"\n  Sofascore: {len(ss_found)} sonuç bulundu")
            print(f"  {'#':>2}  {'MAÇ':<28}  SKOR     SONUÇ")
            print("  " + "─"*52)
            for m in matches:
                no = m["no"]
                ev = ss_found.get(no)
                if ev:
                    print(f"  ✓ #{no:>2} {m['mac']:<28} "
                          f"{ev['score']:<8} {ev['result']}")
                else:
                    pend = ss_results.get(no)
                    tag  = f"⏳ {pend['score']}" if pend else "?"
                    print(f"  {tag:>4} #{no:>2} {m['mac']:<28} (bekleniyor)")
            print(f"\n  Kaydet? (Enter=Evet / T=Toplu manuel / S=Sıralı): ", end="")
            try:
                raw = input().strip().upper()
                ans = raw[:1] if raw[:1] in ("E","H","T","S") else ("E" if raw == "" else raw[:1])
            except (EOFError, KeyboardInterrupt):
                ans = "E"
            if ans in ("E", ""):
                changed = 0
                for i, m in enumerate(matches):
                    ev = ss_found.get(m["no"])
                    if ev:
                        matches[i]["actual"] = FTR_MAP.get(ev["result"], ev["result"])
                        changed += 1
                log[week_id]["matches"] = matches
                self._save_pred_log(log)
                if changed > 0:
                    print(f"\n  {changed} sonuç kaydedildi → öğrenme başlıyor...")
                    self._learn_from_week(week_id, matches)
                    self.save()
                    self._print_learning_report(week_id, matches)
                    # ── Excel arşivini güncelle ───────────────
                    try:
                        from output.xlsx_export import refresh_memory_sheet
                        refresh_memory_sheet(self, week_id, matches)
                        print(f"  [Excel] st_arsiv.xlsx güncellendi")
                    except Exception as _xe:
                        print(f"  [Excel] Güncelleme atlandı: {_xe}")

                # Eksik maçlar var mı?
                missing = [m for m in matches if not m.get("actual")]
                if missing:
                    print(f"\n  {len(missing)} maç eksik kaldı:")
                    for m in missing:
                        print(f"    #{m['no']:>2} {m['mac']}")
                    print(f"\n  Eksikleri şimdi girmek ister misin? (E/H): ", end="")
                    try:
                        raw2 = input().strip().upper()
                        do_missing = raw2[:1]
                    except (EOFError, KeyboardInterrupt):
                        do_missing = "H"
                    if do_missing in ("E","Y"):
                        mod = "T"
                    else:
                        return week_id
                else:
                    return week_id
            elif ans not in ("T","S"):
                ans = "T"
                mod = ans
            else:
                mod = ans
        else:
            print("  Sofascore'dan sonuç alınamadı — manuel giriş")
            mod = "T"

        changed = 0

        if mod == "T":
            print(f"\n  {'#':>2}  {'MAÇ':<28}  {'TAHMİN':>12}  MEVCUT")
            print("  " + "─"*56)
            for m in matches:
                actual = m.get("actual","")
                tag    = f"[{actual}]" if actual else "[ ]"
                print(f"  {m['no']:>2}. {m['mac']:<28}  "
                      f"{m.get('pred_label',''):>12}  {tag}")

            print(f"\n  Sonuçları gir (1/X/2, eksik olan için - kullan):")
            print(f"  Örnek 10 maç  : 2 X 1 X 2 1 2 1 1 1")
            print(f"  Örnek 15 maç  : 2 X 1 X 2 1 2 1 1 1 2 2 1 2 1")
            print(f"  Ara boşluk    : 2 X - - 2 1 2 - - 1  (- = oynamadı)")
            print(f"  > ", end="")

            try:
                line = input().strip().upper()
            except (EOFError, KeyboardInterrupt):
                print("  İptal.")
                return

            tokens = [t.strip() for t in line.replace(",", " ").split()]
            print()
            for i, tok in enumerate(tokens):
                if i >= len(matches):
                    break
                if tok in ("-", "_"):
                    continue
                if tok == "0":
                    tok = "X"  # Spor Toto geleneksel: 0 = X (beraberlik)
                if tok not in ("1","X","2"):
                    print(f"  ! #{i+1} geçersiz: '{tok}' atlandı")
                    continue
                matches[i]["actual"] = FTR_MAP.get(tok, tok)
                changed += 1
                m       = matches[i]
                correct = self._is_correct(m)
                icon    = "✓" if correct else "✗"
                print(f"  {icon} #{m['no']:>2} {m['mac']:<28} → {tok}")

            if changed == 0:
                print("  Sonuç girilmedi.")
                return

        else:
            print(f"\n  {week_id} — Sonuç gir (1/X/2, boş=atla, q=çık):")
            print(f"  {'#':>2}  {'MAÇ':<28}  {'TAHMİN':>12}  SONUÇ")
            print("  " + "─"*56)
            for i, m in enumerate(matches):
                actual = m.get("actual")
                status = f"[{actual}]" if actual else "[ ]"
                print(f"  {m['no']:>2}. {m['mac']:<28}  "
                      f"{m.get('pred_label',''):>12}  {status}  ", end="")
                try:
                    raw = input().strip().upper()
                except (EOFError, KeyboardInterrupt):
                    break
                if raw == "Q":
                    break
                if raw == "0":
                    raw = "X"  # Spor Toto geleneksel: 0 = X (beraberlik)
                if raw in ("1","X","2"):
                    matches[i]["actual"] = FTR_MAP.get(raw, raw)
                    changed += 1

        log[week_id]["matches"] = matches
        self._save_pred_log(log)

        if changed > 0:
            print(f"\n  {changed} sonuç kaydedildi → öğrenme başlıyor...")
            self._learn_from_week(week_id, matches)
            self.save()
            self._print_learning_report(week_id, matches)
            try:
                from output.xlsx_export import refresh_memory_sheet
                refresh_memory_sheet(self, week_id, matches)
                print(f"  [Excel] st_arsiv.xlsx güncellendi")
            except Exception as _xe:
                print(f"  [Excel] Güncelleme atlandı: {_xe}")
            return week_id

    # ═══════════════════════════════════════════════════════
    # RAPORLAMA
    # ═══════════════════════════════════════════════════════

    def _print_learning_report(self, week_id: str, matches: list):
        total   = sum(1 for m in matches if m.get("actual"))
        correct = sum(1 for m in matches if m.get("actual") and
                      self._is_correct(m))
        print(f"\n  ── ÖĞRENME RAPORU [{week_id}] ─────────────────────")
        if total:
            print(f"  Bu hafta : {correct}/{total} "
                  f"(%{correct/total*100:.0f})")

        tot = self.mem["total_preds"]
        cor = self.mem["correct"]
        if tot:
            print(f"  Tüm zamanlar: {cor}/{tot} (%{cor/tot*100:.1f})")

        # Hata uyarısı
        warn = self.get_error_warning()
        if warn:
            print(f"\n  {warn}")

        # Bağlam
        print(f"\n  Bağlam başarı oranları:")
        for ctx, d in self.mem["context_acc"].items():
            if d["total"] >= 3:
                acc = d["correct"]/d["total"]
                bar = "█"*int(acc*10)
                print(f"    {ctx:<12} {bar:<10} %{acc*100:.0f} "
                      f"({d['correct']}/{d['total']})")

        ad = self.mem["adaptive"]
        print(f"\n  Güncel eşikler: BANKO>={ad['banko_threshold']:.3f}  "
              f"ÇİFT>={ad['double_threshold']:.3f}")

    def _print_classification_report(self):
        """
        Macro F1-Score ve Confusion Matrix hesapla ve göster.
        Tüm haftalardaki tahmin-sonuç çiftlerini kullanır.
        """
        # Tüm maçları topla
        pairs = []  # (pred_class, actual_class)
        FTR_MAP = {"H":"1","D":"X","A":"2"}

        # profiles'dan sonuçları al
        profiles = self.mem.get("profiles", {})
        for team_key, prof in profiles.items():
            for m in prof.get("matches", []):
                actual_ftr = m.get("actual","")
                pred_raw   = m.get("pred","")
                if not actual_ftr or not pred_raw:
                    continue
                actual = FTR_MAP.get(actual_ftr, "")
                if not actual:
                    continue
                # Tahmin sınıfını belirle (tek seçim → o, çoklu → en olası)
                if pred_raw in ("1","X","2"):
                    pred = pred_raw
                elif pred_raw in ("1X","X1"):
                    pred = "1" if m.get("P1",0) >= m.get("PX",0) else "X"
                elif pred_raw in ("2X","X2"):
                    pred = "2" if m.get("P2",0) >= m.get("PX",0) else "X"
                elif pred_raw in ("12","21"):
                    pred = "1" if m.get("P1",0) >= m.get("P2",0) else "2"
                elif pred_raw == "1X2":
                    p = {"1":m.get("P1",0),"X":m.get("PX",0),"2":m.get("P2",0)}
                    pred = max(p, key=p.get)
                else:
                    continue
                pairs.append((pred, actual))

        # Yeterli veri yoksa alternatif kaynak — weekly_history + context_acc
        if len(pairs) < 10:
            # context_acc'tan yaklaşık hesapla
            ctx = self.mem.get("context_acc", {})
            total_correct = self.mem.get("correct", 0)
            total_preds   = self.mem.get("total_preds", 0)
            if total_preds < 10:
                return
            # Sadece genel istatistik göster
            print(f"\n  Sınıflandırma Özeti (yaklaşık):")
            print(f"    Genel doğruluk: %{total_correct/total_preds*100:.1f}")
            ep = self.mem.get("error_patterns", {})
            kd = ep.get("kaos_actual_draw",{})
            if kd.get("total",0):
                print(f"    KAOS → X hata: %{kd['wrong']/kd['total']*100:.0f} "
                      f"({kd['wrong']}/{kd['total']})")
            return

        # F1 hesapla (her sınıf için)
        classes = ["1","X","2"]
        labels  = {"1":"Ev(1)","X":"Bera(X)","2":"Dep(2)"}

        cm = {a:{p:0 for p in classes} for a in classes}
        for pred, actual in pairs:
            if pred in classes and actual in classes:
                cm[actual][pred] += 1

        f1_scores = {}
        for cls in classes:
            tp = cm[cls][cls]
            fp = sum(cm[a][cls] for a in classes if a != cls)
            fn = sum(cm[cls][p] for p in classes if p != cls)
            prec = tp / (tp + fp) if (tp+fp) > 0 else 0.0
            rec  = tp / (tp + fn) if (tp+fn) > 0 else 0.0
            f1   = 2*prec*rec/(prec+rec) if (prec+rec) > 0 else 0.0
            f1_scores[cls] = round(f1, 3)

        macro_f1 = sum(f1_scores.values()) / len(f1_scores)

        if macro_f1 >= 0.65:   f1_tag = "✅ İyi"
        elif macro_f1 >= 0.50: f1_tag = "✓ Orta"
        else:                  f1_tag = "⚠ Düşük"

        print(f"\n  Sınıf Bazlı Performans (F1):")
        for cls in classes:
            bar_len = int(f1_scores[cls] * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            total_cls = sum(cm[cls].values())
            correct_cls = cm[cls][cls]
            print(f"    {labels[cls]:<8} F1={f1_scores[cls]:.2f} "
                  f"[{bar}] ({correct_cls}/{total_cls})")

        print(f"    Macro F1 : {macro_f1:.3f}  {f1_tag}")

        # Mini confusion matrix
        print(f"\n  Karmaşıklık Matrisi (Tahmin→ / ←Gerçek):")
        print(f"    {'':8} {'Ev(1)':>6} {'Bera(X)':>7} {'Dep(2)':>7}")
        print(f"    {'─'*32}")
        for actual in classes:
            row = f"    {labels[actual]:<8}"
            for pred in classes:
                val = cm[actual][pred]
                marker = "【" + str(val) + "】" if actual == pred else f"  {val}  "
                row += f"{marker:>7}"
            print(row)

        # Zayıf nokta tespiti
        weakest = min(f1_scores, key=f1_scores.get)
        if f1_scores[weakest] < 0.40:
            print(f"\n  ⚠ En zayıf sınıf: {labels[weakest]} "
                  f"(F1={f1_scores[weakest]:.2f}) — "
                  f"{'Beraberlik tahminini güçlendir' if weakest=='X' else 'Veri artana kadar dikkatli ol'}")

    def print_memory_summary(self):
        print("\n" + "═"*62)
        print("  UZUN VADELİ ÖĞRENME HAFIZASI")
        print("═"*62)

        tot = self.mem["total_preds"]
        cor = self.mem["correct"]
        created = self.mem.get("created","?")[:10]
        updated = (self.mem.get("last_updated") or "?")[:16]

        print(f"\n  Oluşturulma  : {created}")
        print(f"  Son güncelleme: {updated}")
        print(f"  Toplam hafta  : {self.mem['total_weeks']}")
        print(f"  Toplam tahmin : {tot}")
        if tot:
            print(f"  Genel doğruluk: %{cor/tot*100:.1f} ({cor}/{tot})")

        # ── Brier Skoru & Log-Loss ────────────────────────────
        wh = self.mem.get("weekly_history", [])
        brier_vals  = [h["brier"]   for h in wh if h.get("brier") is not None]
        logloss_vals= [h["logloss"] for h in wh if h.get("logloss") is not None]

        if brier_vals:
            avg_brier   = sum(brier_vals) / len(brier_vals)
            avg_logloss = sum(logloss_vals) / len(logloss_vals) if logloss_vals else None

            if avg_brier < 0.20:   brier_tag = "✅ Mükemmel"
            elif avg_brier < 0.25: brier_tag = "✓ İyi"
            elif avg_brier < 0.30: brier_tag = "⚠ Orta"
            else:                  brier_tag = "🔴 Zayıf"

            print(f"\n  Olasılık Kalitesi (Brier/LogLoss):")
            print(f"    Brier Skoru   : {avg_brier:.4f}  {brier_tag}")
            if avg_logloss:
                print(f"    Log-Loss      : {avg_logloss:.4f}")
            if len(brier_vals) >= 2:
                trend = brier_vals[-1] - brier_vals[-3] if len(brier_vals) >= 3 else brier_vals[-1] - brier_vals[0]
                arrow = "↓ İyileşiyor" if trend < -0.01 else ("↑ Kötüleşiyor" if trend > 0.01 else "→ Sabit")
                print(f"    Trend         : {arrow} ({trend:+.4f})")
            print(f"    Hafta bazlı:")
            for h in wh[-5:]:
                if h.get("brier") is not None:
                    b = h["brier"]
                    tag = "✓" if b < 0.25 else "⚠"
                    print(f"      {h['week']}: Brier={b:.3f} {tag}  "
                          f"Acc=%{h['acc']*100:.0f}")

        # ── HAFTA ZORLUK ANALİZİ ─────────────────────────────
        weeks_with_diff = [h for h in wh if h.get("difficulty") is not None]
        if weeks_with_diff:
            print(f"\n  Hafta Zorluk & Düzeltilmiş Başarı:")
            print(f"    {'HAFTA':<12} {'SONUÇ':>6} {'ZORLUK':>8} {'ETİKET':<12} {'DÜZ.BAŞARI':>10}")
            print(f"    {'─'*52}")
            for h in weeks_with_diff:
                acc_pct = f"%{h['acc']*100:.0f}"
                adj_pct = f"%{h.get('adj_acc',h['acc'])*100:.0f}"
                diff    = h.get('difficulty', 0)
                label   = h.get('diff_label', '')
                draws   = h.get('actual_draws', '?')
                print(f"    {h['week']:<12} {h['correct']}/{h['total']} {acc_pct:>4}"
                      f"  {diff:>6.2f}   {label:<12} {adj_pct:>6}  ({draws}X)")

            # Ortalama düzeltilmiş başarı
            adj_vals = [h.get("adj_acc", h["acc"]) for h in weeks_with_diff]
            avg_adj  = sum(adj_vals) / len(adj_vals)
            raw_vals = [h["acc"] for h in weeks_with_diff]
            avg_raw  = sum(raw_vals) / len(raw_vals)
            print(f"    {'─'*52}")
            print(f"    {'Ortalama':<12} {'':>6}       {'':>6}   {'':>12} "
                  f"Ham=%{avg_raw*100:.1f} → Düz=%{avg_adj*100:.1f}")

        # ── MACRO F1 + CONFUSION MATRIX ──────────────────────
        self._print_classification_report()

        # Sezon bazlı özet
        if self.mem.get("season_summary"):
            print(f"\n  Sezon özeti:")
            for season, d in sorted(self.mem["season_summary"].items()):
                n = d["total"]
                if n:
                    acc = d["correct"]/n
                    print(f"    20{season[:2]}/20{season[2:]}: "
                          f"%{acc*100:.1f} ({d['correct']}/{n})")

        # Eşikler
        ad = self.mem["adaptive"]
        print(f"\n  Öğrenilmiş eşikler:")
        print(f"    BANKO >= {ad['banko_threshold']:.3f}")
        print(f"    ÇİFT  >= {ad['double_threshold']:.3f}")
        if ad.get("history"):
            print(f"    Eşik değişim sayısı: {len(ad['history'])}")

        # Bağlam
        print(f"\n  Bağlam başarı oranları:")
        for ctx, d in self.mem["context_acc"].items():
            if d["total"] >= 3:
                acc = d["correct"]/d["total"]
                boost = ad["context_boosts"].get(ctx, "-")
                print(f"    {ctx:<12} %{acc*100:.0f} ({d['correct']}/{d['total']})"
                      + (f"  boost:{boost:.3f}" if isinstance(boost, float) else ""))

        # Hata desenleri
        ep = self.mem.get("error_patterns", {})
        print(f"\n  Hata desenleri:")
        labels = {
            "banko_fail_home_fav": "Ev favorisi BANKO yanılma",
            "banko_fail_away_fav": "Dep favorisi BANKO yanılma",
            "kaos_actual_draw":    "KAOS → gerçekte beraberlik",
            "high_conf_draw_miss": "Yüksek güvende beraberlik kaçırma",
        }
        for key, d in ep.items():
            if d.get("total",0) >= 5:
                rate = d["wrong"]/d["total"]
                flag = " ⚠" if rate >= 0.55 else ""
                print(f"    {labels.get(key,key):<36} "
                      f"%{rate*100:.0f} ({d['wrong']}/{d['total']}){flag}")

        # Profil hafızası özet
        prf_count = len(self.mem.get("profiles", {}))
        prf_total = sum(v.get("n",0) for v in self.mem.get("profiles",{}).values())
        if prf_count:
            print(f"\n  Profil hafızası: {prf_count} profil, "
                  f"{prf_total:.0f} maç")

        # Zor takımlar
        bad = sorted(
            [(k,v) for k,v in self.mem["teams"].items()
             if v.get("total",0)>=8],
            key=lambda x: x[1]["correct"]/x[1]["total"]
        )[:5]
        if bad:
            print(f"\n  Model için zor takımlar:")
            for k, v in bad:
                acc = v["correct"]/v["total"]
                print(f"    {v.get('name',k):<22} "
                      f"%{acc*100:.0f} ({v['correct']}/{v['total']})")

        # Aktif seriler
        active = [(k,v) for k,v in self.mem["streaks"].items()
                  if v.get("streak_n",0)>=3]
        if active:
            print(f"\n  Aktif seriler (≥3):")
            for k,v in sorted(active, key=lambda x:-x[1]["streak_n"])[:8]:
                typ = {"W":"Galibiyet","D":"Beraberlik","L":"Mağlubiyet"
                       }.get(v.get("streak_type",""),"?")
                print(f"    {v.get('name',k):<22} "
                      f"{v['streak_n']}× {typ} | {v.get('last10','')}")

        # Sürprizler
        all_surprises = []
        for s_list in self.mem.get("surprises",{}).values():
            all_surprises.extend(s_list)
        all_surprises = sorted(all_surprises,
                               key=lambda x: x.get("confidence",0),
                               reverse=True)[:5]
        if all_surprises:
            print(f"\n  En büyük sürprizler (güvene rağmen yanılma):")
            for s in all_surprises:
                print(f"    {s['mac']:<26} "
                      f"Tahmin:{s['pred']} Gerçek:{s['actual']} "
                      f"%{s['confidence']:.0f} güven  [{s.get('ctx','')}]")

        print("═"*62)

    @staticmethod
    def _is_correct(m: dict) -> bool:
        actual   = m.get("actual","")
        pred_raw = m.get("pred","?")
        if not actual or not pred_raw:
            return False
        # actual → H/D/A normalize (1/X/2/0 formatlarını da kabul et)
        _norm = {"1":"H","X":"D","2":"A","0":"D"}
        actual_ftr = _norm.get(actual, actual)
        pred_ftr = FTR_MAP.get(pred_raw)
        if pred_ftr:
            return pred_ftr == actual_ftr
        # Çoklu seçim: 1X, 2X, 1X2, 12 vb.
        choices = [FTR_MAP.get(c) for c in pred_raw if c in FTR_MAP]
        return actual_ftr in choices if choices else False

    def _load_pred_log(self) -> dict:
        if os.path.exists(PRED_LOG_FILE):
            try:
                with open(PRED_LOG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, IOError, ValueError, TypeError, KeyError):
                pass
        return {}

    def _save_pred_log(self, log: dict):
        try:
            tmp_file = PRED_LOG_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, PRED_LOG_FILE)
        except (OSError, IOError, ValueError, TypeError, KeyError) as e:
            print(f"  [Log] Kaydedilemedi: {e}")


    # ═══════════════════════════════════════════════════════
    # TAKİM KRONİK PROFİLİ — Team DNA
    # ═══════════════════════════════════════════════════════
    # Her LPRM analiz sonucu hafızaya birikir.
    # Decay ile eski veriler zayıflar, confidence ile sinyal
    # kalitesi ölçülür, cold start durumunda fallback çalışır.

    _DECAY_ALPHA    = 0.85   # Ağırlık: 1=eski korunur, 0=sıfırlanır
    _MIN_CONFIDENCE = 0.30   # Lambda etkisi için min güven
    _MIN_SAMPLE     = 4      # Güvenilir sinyal için min maç

    def update_chronic_profile(self, team: str, band: str,
                                ftr: str, week_id: str,
                                tactic: int = None) -> None:
        """
        LPRM sinyalini hafızaya işle.

        team    : normalize takım ismi
        band    : oran bandı ('dominant','strong_fav',...)
        ftr     : gerçek sonuç ('H','D','A')
        week_id : 'ST40-2526'
        tactic  : dep taktik profili (0=press,1=mid,2=block)
        """
        if not team or not band or not ftr:
            return

        try:
            cp = self.mem.setdefault("chronic_profiles", {})
            if team not in cp:
                cp[team] = self._empty_profile()

            p = cp[team]

            # ── Odds Band güncellemesi ──────────────────────
            ob = p["odds_performance"].setdefault(band, {
                "wins": 0.0, "draws": 0.0, "losses": 0.0, "sample": 0
            })
            # Decay: eski değerler azalır
            ob["wins"]   *= self._DECAY_ALPHA
            ob["draws"]  *= self._DECAY_ALPHA
            ob["losses"] *= self._DECAY_ALPHA
            # Yeni maç ekle
            if   ftr == "H": ob["wins"]   += 1.0
            elif ftr == "D": ob["draws"]  += 1.0
            else:            ob["losses"] += 1.0
            ob["sample"] = min(ob["sample"] + 1, 200)

            # ── Tactical Ghosting güncellemesi ──────────────
            if tactic is not None:
                tkey = {0:"high_press", 1:"mid_press", 2:"low_block"}.get(tactic)
                if tkey:
                    tg = p["tactical_ghosting"].setdefault(tkey, {
                        "wins":0.0,"draws":0.0,"losses":0.0,"sample":0
                    })
                    tg["wins"]   *= self._DECAY_ALPHA
                    tg["draws"]  *= self._DECAY_ALPHA
                    tg["losses"] *= self._DECAY_ALPHA
                    if   ftr == "H": tg["wins"]   += 1.0
                    elif ftr == "D": tg["draws"]  += 1.0
                    else:            tg["losses"] += 1.0
                    tg["sample"] = min(tg["sample"] + 1, 200)

            p["last_updated"] = week_id
            p["total_matches"] = p.get("total_matches", 0) + 1

            self.save()

        except Exception as e:
            pass  # Hafıza hatası ana pipeline'ı durdurmasın

    def get_chronic_signal(self, team: str, band: str,
                            tactic: int = None,
                            position: int = None) -> dict:
        """
        Birikmiş kronik profili sinyale çevir.

        team     : normalize takım ismi
        band     : oran bandı
        tactic   : dep taktik profili
        position : Spor Toto liste pozisyonu (#3,#15 → düşük draw eşiği)
        """
        cp = self.mem.get("chronic_profiles", {})
        profile = cp.get(team)

        # ── Cold Start: veri yoksa fallback ─────────────────
        if not profile:
            return self._cold_start_signal()

        result = {"signal":"normal","confidence":0.0,
                  "lambda_mod":1.0,"warning":"","source":"memory"}

        # ── Odds Band sinyali ────────────────────────────────
        ob = profile.get("odds_performance", {}).get(band)
        if ob and ob.get("sample", 0) >= self._MIN_SAMPLE:
            total  = ob["wins"] + ob["draws"] + ob["losses"]
            if total > 0:
                win_r  = ob["wins"]  / total
                draw_r = ob["draws"] / total
                conf   = min(1.0, ob["sample"] / 30)  # 30 maç → tam güven

                # Pozisyon bazlı dinamik draw eşiği
                # #3,#15 → tarihsel %40+ beraberlik → eşiği 0.35'e çek
                _draw_thr = 0.35 if position in (3, 15) else 0.38

                # Sinyal üret
                if draw_r > _draw_thr:
                    result.update({
                        "signal":     "kilitleme",
                        "confidence": conf,
                        "lambda_mod": max(0.94, 1.0 - draw_r * 0.15),
                        "warning":    (f"[DNA] {team} bu oranda "
                                       f"%{draw_r*100:.0f} beraberlik "
                                       f"({ob['sample']} maç, güven %{conf*100:.0f})")
                    })
                elif win_r < 0.38:
                    result.update({
                        "signal":     "favori_tuzagi",
                        "confidence": conf,
                        "lambda_mod": max(0.92, 1.0 - (0.45-win_r) * 0.20),
                        "warning":    (f"[DNA] {team} bu oranda "
                                       f"%{win_r*100:.0f} kazanıyor — FAVORİ TUZAĞI "
                                       f"({ob['sample']} maç)")
                    })
                elif win_r > 0.65:
                    result.update({
                        "signal":     "kronik_kazanan",
                        "confidence": conf,
                        "lambda_mod": min(1.08, 1.0 + (win_r-0.55) * 0.15),
                        "warning":    (f"[DNA] {team} bu oranda "
                                       f"%{win_r*100:.0f} kazanıyor "
                                       f"({ob['sample']} maç, güven %{conf*100:.0f})")
                    })

        # ── Tactical Ghosting sinyali ────────────────────────
        if tactic is not None and result["signal"] == "normal":
            tkey  = {0:"high_press",1:"mid_press",2:"low_block"}.get(tactic,"")
            tg    = profile.get("tactical_ghosting",{}).get(tkey)
            if tg and tg.get("sample",0) >= self._MIN_SAMPLE:
                total  = tg["wins"] + tg["draws"] + tg["losses"]
                if total > 0:
                    win_r = tg["wins"] / total
                    conf  = min(1.0, tg["sample"] / 20)

                    if tkey == "low_block" and win_r < 0.42:
                        result.update({
                            "signal":     "dusuk_blok_tuzagi",
                            "confidence": conf,
                            "lambda_mod": max(0.93, 1.0 - (0.5-win_r)*0.15),
                            "warning":    (f"[DNA] {team} düşük bloklu rakibe "
                                           f"%{win_r*100:.0f} kazanıyor "
                                           f"({tg['sample']} maç)")
                        })
                    elif tkey == "high_press" and win_r < 0.40:
                        result.update({
                            "signal":     "pres_hassasiyeti",
                            "confidence": conf,
                            "lambda_mod": max(0.94, 1.0 - (0.5-win_r)*0.12),
                            "warning":    (f"[DNA] {team} yüksek baskıya "
                                           f"%{win_r*100:.0f} kazanıyor")
                        })

        # ── Takım-Pozisyon İstatistikleri ────────────────────
        # "Bu takım bu pozisyonda tarihsel olarak ne yaptı?"
        # Ham lig verisi — position_bias'dan bağımsız katman
        if position is not None and result["signal"] == "normal":
            tp = profile.get("team_position_stats", {}).get(str(position))
            if tp and tp.get("sample", 0) >= 3:
                win_r  = tp["win"] / 100
                draw_r = tp["draw"] / 100
                n      = tp["sample"]
                conf   = min(1.0, n / 8)   # 8 maç → tam güven

                if win_r >= 0.85:
                    result.update({
                        "signal":     "takim_pos_banko",
                        "confidence": conf,
                        "lambda_mod": min(1.08, 1.0 + (win_r-0.65)*0.20),
                        "warning":    (f"[POS] {team} #{position}'de "
                                       f"%{tp['win']:.0f} kazanıyor "
                                       f"({n} maç) — BANKO")
                    })
                elif draw_r >= 0.45:
                    result.update({
                        "signal":     "takim_pos_draw",
                        "confidence": conf,
                        "lambda_mod": max(0.95, 1.0 - draw_r*0.10),
                        "warning":    (f"[POS] {team} #{position}'de "
                                       f"%{tp['draw']:.0f} beraberlik "
                                       f"({n} maç) — ÇİFT 1X")
                    })
                elif win_r <= 0.40:
                    result.update({
                        "signal":     "takim_pos_zayif",
                        "confidence": conf,
                        "lambda_mod": max(0.94, 1.0 - (0.55-win_r)*0.15),
                        "warning":    (f"[POS] {team} #{position}'de "
                                       f"%{tp['win']:.0f} kazanıyor "
                                       f"({n} maç) — dikkat")
                    })

        # Minimum güven filtresi — etkisiz kalır
        if result["confidence"] < self._MIN_CONFIDENCE:
            result["lambda_mod"] = 1.0

        # ── Streak × Kronik Köprüsü ──────────────────────────
        # Mevcut streak verisiyle kronik profil çelişiyorsa uyar.
        # Yeni hesaplama yok — sadece mevcut iki veriyi birleştirir.
        try:
            streak_str = self.get_streak_info(team)
            if streak_str:
                sig = result["signal"]
                streak_n = int(''.join(c for c in streak_str if c.isdigit()) or "0")

                # Kronik güçlü ama kötü form → kriz
                if sig == "kronik_kazanan" and "L" in streak_str:
                    result["warning"] += (
                        f"  ⚠ KRONİK GÜÇLÜ ama {streak_str} FORMDA"
                        + (" — GEÇİCİ KRİZ?" if streak_n >= 3 else "")
                    )
                    result["signal"] = "kronik_kazanan_form_krizi"

                # Kronik kilitleme ama iyi form → iyileşme
                elif sig == "kilitleme" and "W" in streak_str:
                    result["warning"] += (
                        f"  🟡 KRONİK KİLİTLENME ama {streak_str} FORMDA"
                        + (" — FORM DÖNÜŞEBİLİR" if streak_n >= 3 else "")
                    )
                    result["signal"] = "kilitleme_form_iyilesiyor"
        except Exception:
            pass  # Streak yoksa köprü sessizce atlanır

        return result

    def preheat_profiles(self, df_all, league_code: str = "T1",
                          week_id: str = "preheat") -> int:
        """
        fd_cache CSV verisinden toplu profil ısıtması.
        Cold start sorununu çözer.

        Kullanım: Menü 6 sonrası veya ilk kurulumda çalıştır.
        Döner: işlenen maç sayısı
        """
        _nrm = _normalize  # input.team_resolver._normalize (satir 3'te import edildi)

        # Oran bandı belirleme
        def _band(o):
            if o is None: return None
            o = float(o)
            if o < 1.35: return "dominant"
            if o < 1.70: return "strong_fav"
            if o < 2.10: return "fav"
            if o < 2.60: return "slight_fav"
            if o < 3.20: return "even"
            return "underdog"

        processed = 0
        for _, row in df_all.iterrows():
            ftr   = row.get("FTR")
            home  = str(row.get("HomeTeam",""))
            o1    = row.get("B365H") or row.get("MaxH")
            if not ftr or not home or ftr not in ("H","D","A"):
                continue
            band = _band(o1)
            if not band:
                continue
            self.update_chronic_profile(
                team=home.upper(), band=band,
                ftr=ftr, week_id=week_id
            )
            processed += 1

        print(f"  [Preheat] {processed} maç işlendi ({league_code})")
        return processed

    def soft_reset_team(self, team: str, reason: str = "") -> None:
        """
        Takım profili soft reset — TD değişikliği, transfer dönemi vb.
        Eski veriler tamamen silinmez, yarıya indirilir.
        """
        cp = self.mem.get("chronic_profiles", {})
        if team not in cp:
            return
        p = cp[team]
        for band_data in p.get("odds_performance", {}).values():
            for k in ("wins","draws","losses"):
                if k in band_data:
                    band_data[k] *= 0.5
            band_data["sample"] = max(0, band_data.get("sample",0) // 2)
        for tg_data in p.get("tactical_ghosting", {}).values():
            for k in ("wins","draws","losses"):
                if k in tg_data:
                    tg_data[k] *= 0.5
            tg_data["sample"] = max(0, tg_data.get("sample",0) // 2)
        p["soft_reset"] = reason or "manuel"
        self.save()
        print(f"  [DNA] {team} profili soft reset: {reason}")

    def get_profile_summary(self, team: str) -> str:
        """Takım profilinin kısa özeti."""
        cp  = self.mem.get("chronic_profiles", {})
        p   = cp.get(team)
        if not p:
            return f"  {team}: Profil yok (cold start)"

        lines = [f"  {team} — DNA Profili"]
        for band, ob in p.get("odds_performance", {}).items():
            n = ob.get("sample",0)
            if n < 2: continue
            t = ob["wins"]+ob["draws"]+ob["losses"]
            if t == 0: continue
            lines.append(f"    {band:<12}: W%{ob['wins']/t*100:.0f} "
                          f"D%{ob['draws']/t*100:.0f} L%{ob['losses']/t*100:.0f} "
                          f"(n={n})")
        for tkey, tg in p.get("tactical_ghosting", {}).items():
            n = tg.get("sample",0)
            if n < 2: continue
            t = tg["wins"]+tg["draws"]+tg["losses"]
            if t == 0: continue
            lines.append(f"    {tkey:<15}: W%{tg['wins']/t*100:.0f} (n={n})")
        lines.append(f"    Güncelleme: {p.get('last_updated','?')} "
                     f"| Toplam: {p.get('total_matches',0)} maç")
        return "\n".join(lines)

    @staticmethod
    def _empty_profile() -> dict:
        return {
            "odds_performance":  {},
            "tactical_ghosting": {},
            "last_updated":      None,
            "total_matches":     0,
        }

    @staticmethod
    def _cold_start_signal() -> dict:
        """Veri yokken güvenli varsayılan — lambda değişmez."""
        return {
            "signal":     "cold_start",
            "confidence": 0.0,
            "lambda_mod": 1.0,
            "warning":    "",
            "source":     "cold_start",
        }

    # ═══════════════════════════════════════════════════════
    # DEVRET SİSTEMİ
    # ═══════════════════════════════════════════════════════

    def is_devret_week(self, week_id: str = "") -> bool:
        """
        Önceki haftada 15 bilen çıkmadıysa (devret ettiyse) True döner.

        Tespit sırası:
          1. weekly_history'de prize_15 == 0 kayıtlı ise → kesin devret
          2. st_predictions.json'da ikramiye.bilen_15 == 0 ise → kesin devret
          3. actual_draws > 8 heuristic → muhtemel devret
        """
        wh = self.mem.get("weekly_history", [])
        if not wh:
            return False

        import re as _re3
        def _wk_key_str(h):
            _wm = _re3.match(r'ST(\d+)-(\d+)', h.get("week",""))
            return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)
        completed = [h for h in wh
                     if h.get("status") == "completed"
                     and (not week_id or _wk_key_str(h) < _wk_key_str({"week": week_id}))]
        if not completed:
            return False

        prev = max(completed, key=_wk_key_str)

        if "prize_15" in prev:
            return prev["prize_15"] == 0

        draws = prev.get("actual_draws", 0)
        return draws >= 8

    def record_devret(self, week_id: str, bilen_15: int,
                      devret_etti: bool) -> None:
        """
        Haftalık sonuç eklenirken devret bilgisini kaydet.
        Menü 2'de sonuç girilince çağrılır.
        """
        wh = self.mem.get("weekly_history", [])
        for h in wh:
            if h.get("week") == week_id:
                h["prize_15"]    = bilen_15
                h["devret_etti"] = devret_etti
                break
        self.save()   # FIX: self._save() → self.save()

    def get_devret_status(self) -> dict:
        """
        Devret durumu özeti:
          devret_haftasi: bool — bu hafta devret var mı
          onceki_devret:  bool — geçen hafta devret etmiş miydi
          beklenen_x:     float — devret haftası X beklentisi
        """
        wh = self.mem.get("weekly_history", [])
        completed = [h for h in wh if h.get("status") == "completed"]
        if not completed:
            return {"devret_haftasi": False, "onceki_devret": False, "beklenen_x": 3.9}

        import re as _re4
        def _wk_key3(h):
            _wm = _re4.match(r'ST(\d+)-(\d+)', h.get("week",""))
            return (int(_wm.group(2)), int(_wm.group(1))) if _wm else (0, 0)
        prev = max(completed, key=_wk_key3)
        onceki_devret = (prev.get("prize_15", 1) == 0 or
                         prev.get("actual_draws", 0) >= 8)

        return {
            "devret_haftasi": onceki_devret,
            "onceki_devret":  onceki_devret,
            "beklenen_x":     15.8 if onceki_devret else 3.9,
            "onceki_hafta":   prev.get("week",""),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════
_memory = None


def get_memory() -> STMemory:
    global _memory
    if _memory is None:
        _memory = STMemory()
    return _memory

