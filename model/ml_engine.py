# -*- coding: utf-8 -*-
"""
model/ml_engine.py — AUGUR ENGINE ML Katmanı
=============================================

3 model ensemble:
  LR  (Logistic Regression)   → ağırlık 0.20
  GB  (Gradient Boosting)     → ağırlık 0.55
  MLP (Sinir Ağı)             → ağırlık 0.25

Pydroid3 uyumlu (RAM < 100MB, sklearn hafif parametreler).

Kullanım:
  from model.ml_engine import AugurML
  ml = AugurML()
  ml.load()                    # kayıtlı modeli yükle (yoksa None)
  p = ml.predict(features)     # {'p1':0.45,'px':0.30,'p2':0.25} veya None
  ml.train(X, y)               # yeni veriyle eğit
  ml.save()                    # modeli kaydet

Eğitim zamanlaması:
  300+  maç → ilk GB eğitimi   (Ağustos 2026 ~20. hafta)
  500+  maç → LR + GB ensemble (Eylül 2026  ~30. hafta)
  780+  maç → tam ensemble     (Aralık 2026 ~52. hafta)
"""

from __future__ import annotations

import os
import json
import pickle
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Dosya yolları ─────────────────────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.dirname(_HERE)
MODEL_FILE = os.path.join(_ROOT, "ml_model.pkl")

# ── Minimum veri eşikleri ─────────────────────────────────────────────────────
MIN_SAMPLES_GB  = 300   # GB için minimum maç sayısı
MIN_SAMPLES_LR  = 200   # LR için minimum maç sayısı
MIN_SAMPLES_MLP = 500   # MLP için minimum maç sayısı
MIN_SAMPLES_RF  = 300   # RF için minimum maç sayısı

# ── Ensemble ağırlıkları ──────────────────────────────────────────────────────
WEIGHTS = {"lr": 0.15, "gb": 0.45, "mlp": 0.20, "rf": 0.20}

# ── Feature isimleri (sıra önemli) ───────────────────────────────────────────
# Feature isimleri training_loader.py ile senkron (28 özellik)
try:
    from tools.training_loader import FEATURE_NAMES, N_FEATURES
except ImportError:
    FEATURE_NAMES = [f"f{i}" for i in range(15)]  # ARAŞTIRMA: 28 → 15
    N_FEATURES = 15


# ── AugurML sınıfı ────────────────────────────────────────────────────────────


class ResidualML:
    """
    Rezidüel ML — 5C Mimarisi (Ağustos 2026)
    ==========================================

    Fikir: Mevcut model (AugurML) oranlardan %54 doğruluk çıkarıyor.
    Bu tavan oranların doğal bilgi sınırı.

    Rezidüel yaklaşım:
      base_p1  = LPRM tahmini (Poisson + katmanlar)
      actual   = gerçek sonuç (1/0 vektörü)
      residual = actual - base_p1  ← bunu öğren!

    Avantaj:
      Model oranları yeniden öğrenmek yerine SADECE
      oranların fiyatlamadığı fazlalığı öğrenir.
      → Pinnacle dışı bilgi: ELO fark, form delta, sakatlık
      → %54 tavanı kırılabilir

    Eğitim:
      X: odds-dışı özellikler (elo_diff, form_delta, pos_diff,
         injury_flag, rest_days, fixture_congestion)
      y: actual_1 - base_p1  ← sürekli değer (regresyon!)
      Model: GradientBoostingRegressor × 3

    Inference:
      base_p1, base_px, base_p2 = LPRM çıktısı
      delta_1  = residual_model.predict(X_extras)
      final_p1 = base_p1 + lambda * delta_1
      lambda   = 0.3 (tunable — Ağustos A/B test)

    Gerekli minimum veri: 300 maç (Ağustos ~6. haftada)
    """

    RESIDUAL_FILE   = MODEL_FILE.replace("ml_model.pkl", "residual_model.pkl")
    MIN_SAMPLES     = 300
    BLEND_LAMBDA    = 0.30   # delta katkı ağırlığı — tunable
    MAX_DELTA       = 0.15   # max ±%15 düzeltme

    EXTRA_FEATURES  = [
        "elo_diff_norm",     # (ev_elo - dep_elo) / 400
        "form_delta",        # ev son 5 maç puan ort - dep son 5 maç puan ort
        "pos_diff",          # dep_rank - ev_rank (normalize)
        "injury_h",          # ev takım sakatlık sayısı
        "injury_a",          # dep takım sakatlık sayısı
        "rest_days_h",       # ev son maçtan bu yana gün
        "rest_days_a",       # dep son maçtan bu yana gün
        "h2h_win_rate",      # H2H ev galibiyeti oranı (son 5)
        "market_move_h",     # kapanış - açılış oran farkı (line movement)
        "season_week_norm",  # sezon haftası / 38
    ]
    N_EXTRA = len(EXTRA_FEATURES)

    def __init__(self):
        self.reg_1  = None   # 1 (ev galibiyet) residual
        self.reg_x  = None   # X (beraberlik) residual
        self.reg_2  = None   # 2 (dep galibiyet) residual
        self.trained = False
        self.n_samples = 0
        self.scores = {}

    def load(self) -> bool:
        if not os.path.exists(self.RESIDUAL_FILE):
            return False
        try:
            with open(self.RESIDUAL_FILE, "rb") as f:
                data = pickle.load(f)
            self.reg_1     = data.get("reg_1")
            self.reg_x     = data.get("reg_x")
            self.reg_2     = data.get("reg_2")
            self.trained   = data.get("trained", False)
            self.n_samples = data.get("n_samples", 0)
            self.scores    = data.get("scores", {})
            return self.trained
        except Exception:
            return False

    def save(self) -> bool:
        try:
            tmp = self.RESIDUAL_FILE + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump({
                    "reg_1": self.reg_1, "reg_x": self.reg_x, "reg_2": self.reg_2,
                    "trained": self.trained, "n_samples": self.n_samples,
                    "scores": self.scores,
                }, f)
            os.replace(tmp, self.RESIDUAL_FILE)
            return True
        except Exception:
            return False

    def train(self, X_extra: list, base_probs: list,
              y_actual: list, sample_weights: list = None,
              verbose: bool = True) -> dict:
        """
        Rezidüel eğitim.

        Args:
            X_extra:      N × N_EXTRA (odds-dışı özellikler)
            base_probs:   N × 3 (base_p1, base_px, base_p2 — LPRM çıktısı)
            y_actual:     N (0=H, 1=D, 2=A)
            sample_weights: opsiyonel

        Returns:
            {"r2_1": ..., "r2_x": ..., "r2_2": ...}
        """
        if len(X_extra) < self.MIN_SAMPLES:
            if verbose:
                print(f"  [Rezidüel] Yetersiz veri: {len(X_extra)}/{self.MIN_SAMPLES}")
            return {}

        try:
            import numpy as np
            from sklearn.ensemble import GradientBoostingRegressor
            from sklearn.model_selection import cross_val_score

            X  = np.array(X_extra, dtype=float)
            bp = np.array(base_probs, dtype=float)    # N×3
            y  = np.array(y_actual, dtype=int)

            # Rezidüel hedefler
            # actual_1 = 1 if H else 0
            y1 = (y == 0).astype(float)   # ev galibiyet
            yx = (y == 1).astype(float)   # beraberlik
            y2 = (y == 2).astype(float)   # dep galibiyet

            res_1 = y1 - bp[:, 0]   # actual_1 - base_p1
            res_x = yx - bp[:, 1]   # actual_x - base_px
            res_2 = y2 - bp[:, 2]   # actual_2 - base_p2

            sw = np.array(sample_weights) if sample_weights else None

            params = {"n_estimators": 80,   # RAM tasarrufu (Bus error önlemi)
                      "max_depth": 3,         # 4→3
                      "learning_rate": 0.05, "subsample": 0.8,
                      "random_state": 42}

            results = {}
            for name, target, attr in [
                ("1", res_1, "reg_1"),
                ("x", res_x, "reg_x"),
                ("2", res_2, "reg_2"),
            ]:
                reg = GradientBoostingRegressor(**params)
                reg.fit(X, target, sample_weight=sw)
                cv = cross_val_score(reg, X, target, cv=5,
                                     scoring="r2").mean()
                setattr(self, attr, reg)
                results[f"r2_{name}"] = round(cv, 4)
                if verbose:
                    print(f"  [Rezidüel] P{name.upper()} R²={cv:.4f}")

            self.trained   = True
            self.n_samples = len(X_extra)
            self.scores    = results
            # Uyarı: R² < 0 ise model henüz anlamlı sinyal görememiş
            _neg = [k for k,v in results.items() if v < 0]
            if _neg and verbose:
                print(f"  ⚠ Rezidüel R² negatif ({_neg}) → lambda'ya UYGULANMAYACAK")
                print("  → Gerçek ELO/form/sakat verileri gelince anlamlı olacak")

            if verbose:
                print(f"  [Rezidüel] Eğitim tamamlandı: {len(X_extra)} maç")

            return results

        except ImportError:
            if verbose:
                print("  [Rezidüel] sklearn yok")
            return {}

    def predict_delta(self, x_extra: list) -> tuple:
        """
        Tek maç için (delta_1, delta_x, delta_2) döner.
        final_p = base_p + BLEND_LAMBDA × delta (kliplenmiş)
        """
        if not self.trained:
            return 0.0, 0.0, 0.0
        try:
            import numpy as np
            X = np.array([x_extra], dtype=float)
            d1 = float(self.reg_1.predict(X)[0])
            dx = float(self.reg_x.predict(X)[0])
            d2 = float(self.reg_2.predict(X)[0])
            # Klip
            d1 = max(-self.MAX_DELTA, min(self.MAX_DELTA, d1))
            dx = max(-self.MAX_DELTA, min(self.MAX_DELTA, dx))
            d2 = max(-self.MAX_DELTA, min(self.MAX_DELTA, d2))
            return d1, dx, d2
        except Exception:
            return 0.0, 0.0, 0.0

    def apply(self, base_p1: float, base_px: float, base_p2: float,
              x_extra: list) -> tuple:
        """
        base_p + lambda × delta ile nihai olasılıkları üret.
        Normalize edilmiş (p1+px+p2=1) tuple döner.
        """
        d1, dx, d2 = self.predict_delta(x_extra)
        p1 = base_p1 + self.BLEND_LAMBDA * d1
        px = base_px + self.BLEND_LAMBDA * dx
        p2 = base_p2 + self.BLEND_LAMBDA * d2
        # Negatif önle
        p1, px, p2 = max(0.03, p1), max(0.03, px), max(0.03, p2)
        total = p1 + px + p2
        return round(p1/total, 4), round(px/total, 4), round(p2/total, 4)


# ── Singleton ─────────────────────────────────────────────────────────────────
_residual_ml: ResidualML = None

def get_residual_ml() -> ResidualML:
    global _residual_ml
    if _residual_ml is None:
        _residual_ml = ResidualML()
        _residual_ml.load()
    return _residual_ml

class AugurML:
    """
    AUGUR ENGINE ML katmanı.

    LPRM'in ürettiği P1/PX/P2'yi geçmiş verilerle kalibre eden ensemble model.
    Yeterli veri yoksa (< MIN_SAMPLES_GB) tahmin None döner → LPRM'e devret.
    """

    def __init__(self):
        self.lr   = None   # LogisticRegression
        self.gb   = None   # GradientBoostingClassifier
        self.mlp  = None   # MLPClassifier
        self.rf   = None   # RandomForestClassifier
        self.trained = {
            "lr": False, "gb": False, "mlp": False, "rf": False
        }
        self.n_samples = 0  # Eğitimde kullanılan toplam maç sayısı
        self.accuracy  = {}  # {"lr": 0.72, "gb": 0.76, "mlp": 0.74}
        self.feature_importances = {}  # GB feature importance

    # ── Yükle ────────────────────────────────────────────────────────────────
    def load(self) -> bool:
        """
        Kayıtlı modeli yükle.
        Returns: True başarılı, False model yok veya hatalı.
        """
        if not os.path.exists(MODEL_FILE):
            logger.info("ml_engine: Model dosyası yok (%s) → LPRM aktif", MODEL_FILE)
            return False

        try:
            with open(MODEL_FILE, "rb") as f:
                data = pickle.load(f)
            self.lr   = data.get("lr")
            self.gb   = data.get("gb")
            self.mlp  = data.get("mlp")
            self.rf   = data.get("rf")
            # FIX: Eski pkl'de 'rf' anahtarı yoktu → merge ile varsayılan koru
            _loaded_trained = data.get("trained", {})
            for k in self.trained:          # lr, gb, mlp, rf
                if k in _loaded_trained:
                    self.trained[k] = _loaded_trained[k]
            self.n_samples  = data.get("n_samples", 0)
            self.accuracy   = data.get("accuracy", {})
            self.feature_importances = data.get("fi", {})
            logger.info("ml_engine: Model yüklendi (%d maç)", self.n_samples)
            return True
        except Exception as e:
            logger.warning("ml_engine: Model yüklenemedi → %s", e)
            return False

    # ── Kaydet ───────────────────────────────────────────────────────────────
    def save(self) -> bool:
        """Modeli diske kaydet."""
        try:
            data = {
                "lr":        self.lr,
                "gb":        self.gb,
                "mlp":       self.mlp,
                "rf":        self.rf,
                "trained":   self.trained,
                "n_samples": self.n_samples,
                "accuracy":  self.accuracy,
                "fi":        self.feature_importances,
            }
            tmp = MODEL_FILE + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump(data, f)
            os.replace(tmp, MODEL_FILE)
            logger.info("ml_engine: Model kaydedildi")
            return True
        except Exception as e:
            logger.warning("ml_engine: Kayıt başarısız → %s", e)
            return False

    # ── Eğit ─────────────────────────────────────────────────────────────────
    def train(self, X: list, y: list,
              sample_weights: list = None,
              verbose: bool = True) -> dict:
        """
        Modelleri eğit.

        Args:
            X: [[p1,px,p2,lam_h,...], ...]   N×20 feature matrisi
            y: [0,1,2, ...]                  0=ev, 1=beraberlik, 2=dep

        Returns:
            {"gb_acc": 0.76, "lr_acc": 0.72, "mlp_acc": 0.74,
             "n": 350, "status": "ok"}
        """
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.neural_network import MLPClassifier
            from sklearn.model_selection import cross_val_score
            import numpy as np
        except ImportError:
            return {"status": "sklearn_yok",
                    "msg": "pip install scikit-learn --break-system-packages"}

        n = len(X)
        self.n_samples = n
        result = {"n": n, "status": "ok"}

        if verbose:
            print(f"\n  [ML] Eğitim başlıyor: {n} maç, {N_FEATURES} özellik")

        # NaN/Inf temizleme
        import math
        clean_X, clean_y, clean_w = [], [], []
        sw_arr = sample_weights if sample_weights else [1.0]*len(X)
        for xi, yi, wi in zip(X, y, sw_arr):
            if any(v is None or (isinstance(v, float) and
                   (math.isnan(v) or math.isinf(v))) for v in xi):
                continue
            clean_X.append(xi); clean_y.append(yi); clean_w.append(wi)

        n_dropped = len(X) - len(clean_X)
        if n_dropped > 0 and verbose:
            print(f"  [Temizleme] {n_dropped} NaN satır atlandı")

        X_arr = np.array(clean_X, dtype=float)
        y_arr = np.array(clean_y, dtype=int)
        sw_arr = np.array(clean_w, dtype=float)

        # ── Gradient Boosting (ana model) ─────────────────────────────────
        if n >= MIN_SAMPLES_GB:
            self.gb = GradientBoostingClassifier(
                n_estimators=60,        # RAM tasarrufu (Bus error önlemi)
                max_depth=3,            # 4→3 bellek yarıya iner
                learning_rate=0.12,     # daha az tree, biraz hızlı öğren
                subsample=0.80,
                random_state=42,
            )
            self.gb.fit(X_arr, y_arr, sample_weight=sw_arr)
            self.trained["gb"] = True

            # CV — saf model üzerinde (Platt öncesi klonlanabilir)
            # TimeSeriesSplit: zaman sırası korunur, gelecek sızmaz (Haziran 2026)
            from sklearn.model_selection import TimeSeriesSplit
            tscv = TimeSeriesSplit(n_splits=3)
            cv_scores = cross_val_score(self.gb, X_arr, y_arr, cv=tscv)
            gb_acc = round(cv_scores.mean(), 4)
            self.accuracy["gb"] = gb_acc
            result["gb_acc"] = gb_acc

            # Platt scaling — CV sonrası fit edilmiş modele uygula
            # cv='prefit': model zaten fit, sadece sigmoid kalibrasyonu fit et
            try:
                from sklearn.calibration import CalibratedClassifierCV
                _n_cal = max(30, int(len(X_arr) * 0.10))
                _calib_gb = CalibratedClassifierCV(self.gb, method='sigmoid', cv='prefit')
                _calib_gb.fit(X_arr[-_n_cal:], y_arr[-_n_cal:])
                self.gb = _calib_gb
            except Exception:
                pass   # Kalibrasyon başarısızsa orijinal model korunur

            # Feature importance — Platt sonrası gb CalibratedClassifier olabilir
            # .calibrated_classifiers_[0].estimator ile orijinal GB'ye ulaş
            try:
                _gb_base = self.gb
                if hasattr(_gb_base, "calibrated_classifiers_"):
                    _gb_base = _gb_base.calibrated_classifiers_[0].estimator
                fi = dict(zip(FEATURE_NAMES, _gb_base.feature_importances_))
                self.feature_importances = {
                    k: round(float(v), 4)
                    for k, v in sorted(fi.items(), key=lambda x: -x[1])
                }
            except Exception:
                self.feature_importances = {}

            import gc; gc.collect()  # Bus error önlemi — GB sonrası bellek boşalt
            if verbose:
                print(f"  [GB] Eğitildi → CV doğruluk: %{gb_acc*100:.1f}")
                top3 = [(k, f"{v:.4f}") for k, v in list(self.feature_importances.items())[:3]]
                print(f"  [GB] Top-3 özellik: {top3}")
        else:
            result["gb_status"] = f"Yetersiz veri ({n}/{MIN_SAMPLES_GB})"

        # ── Logistic Regression ───────────────────────────────────────────
        if n >= MIN_SAMPLES_LR:
            self.lr = LogisticRegression(
                max_iter=500,
                C=1.0,
                multi_class="multinomial",
                solver="lbfgs",
                random_state=42,
            )
            self.lr.fit(X_arr, y_arr, sample_weight=sw_arr)
            self.trained["lr"] = True

            # CV — saf model üzerinde (Platt öncesi)
            tscv = TimeSeriesSplit(n_splits=3)
            cv_scores = cross_val_score(self.lr, X_arr, y_arr, cv=tscv)
            lr_acc = round(cv_scores.mean(), 4)
            self.accuracy["lr"] = lr_acc
            result["lr_acc"] = lr_acc

            # Platt scaling — CV sonrası
            try:
                from sklearn.calibration import CalibratedClassifierCV
                _n_cal = max(30, int(len(X_arr) * 0.10))
                _calib_lr = CalibratedClassifierCV(self.lr, method='sigmoid', cv='prefit')
                _calib_lr.fit(X_arr[-_n_cal:], y_arr[-_n_cal:])
                self.lr = _calib_lr
            except Exception:
                pass

            import gc; gc.collect()  # LR sonrası bellek boşalt
            if verbose:
                print(f"  [LR] Eğitildi → CV doğruluk: %{lr_acc*100:.1f}")
        else:
            result["lr_status"] = f"Yetersiz veri ({n}/{MIN_SAMPLES_LR})"

        # ── MLP (Sinir Ağı) ───────────────────────────────────────────────
        if n >= MIN_SAMPLES_MLP:
            self.mlp = MLPClassifier(
                hidden_layer_sizes=(32, 16),  # hafif ağ
                activation="relu",
                max_iter=200,
                random_state=42,
                early_stopping=True,
                validation_fraction=0.15,
            )
            self.mlp.fit(X_arr, y_arr)
            self.trained["mlp"] = True

            tscv = TimeSeriesSplit(n_splits=3)
            cv_scores = cross_val_score(self.mlp, X_arr, y_arr, cv=tscv)
            mlp_acc = round(cv_scores.mean(), 4)
            self.accuracy["mlp"] = mlp_acc
            result["mlp_acc"] = mlp_acc

            if verbose:
                print(f"  [MLP] Eğitildi → CV doğruluk: %{mlp_acc*100:.1f}")
        else:
            result["mlp_status"] = f"Yetersiz veri ({n}/{MIN_SAMPLES_MLP})"

        # ── Random Forest ─────────────────────────────────────────────
        if n >= MIN_SAMPLES_RF:
            try:
                from sklearn.ensemble import RandomForestClassifier
                self.rf = RandomForestClassifier(
                    n_estimators=50,   # RAM tasarrufu
                    max_depth=4,       # Bus error önlemi
                    min_samples_leaf=5,
                    n_jobs=1,
                    random_state=42,
                    class_weight="balanced",
                )
                self.rf.fit(X_arr, y_arr, sample_weight=sw_arr)
                self.trained["rf"] = True
                tscv = TimeSeriesSplit(n_splits=3)
                cv_rf = cross_val_score(self.rf, X_arr, y_arr, cv=tscv).mean()
                self.accuracy["rf"] = round(cv_rf, 4)
                result["rf_acc"] = round(cv_rf, 4)
                if verbose:
                    print(f"  [RF] Eğitildi → CV doğruluk: %{cv_rf*100:.1f}")
            except Exception as _rfe:
                result["rf_status"] = f"RF hata: {_rfe}"
        else:
            result["rf_status"] = f"Yetersiz veri ({n}/{MIN_SAMPLES_RF})"

        return result

    # ── Tahmin ───────────────────────────────────────────────────────────────
    def predict(self, features: list) -> Optional[dict]:
        """
        Tek maç için P(ev/beraberlik/dep) tahmin et.

        Args:
            features: 15 elemanlı liste (FEATURE_NAMES sırasında).
                      build_features() ile oluşturulur.
                      (Haziran 2026: 28 → 15 özellik, korelasyonlu gruplar çıkarıldı)

        Returns:
            {"p1": 0.45, "px": 0.30, "p2": 0.25,
             "confidence": 0.72,
             "source": "gb+lr"} veya None (model hazır değil)
        """
        try:
            import numpy as np
        except ImportError:
            return None

        # Hiç model eğitilmemişse None döndür
        if not any(self.trained.values()):
            return None

        X = np.array([features], dtype=float)
        proba_sum  = None
        weight_sum = 0.0
        sources    = []

        # Dinamik ağırlık: CV doğruluğu biliniyorsa ona göre hesapla,
        # yoksa sabit WEIGHTS'e düş. Düşük doğruluklu modeller daha az ağırlık alır.
        # Minimum doğruluk eşiği: %45 — altındaki model ensemble'a dahil edilmez.
        MIN_ACC_THRESHOLD = 0.45

        for name, model in [
            ("lr",  self.lr),
            ("gb",  self.gb),
            ("mlp", self.mlp),
            ("rf",  self.rf),
        ]:
            if not self.trained.get(name, False) or model is None:
                continue
            # Dinamik ağırlık: CV doğruluğu varsa kullan, yoksa sabit
            acc = self.accuracy.get(name, 0.0)
            if acc > 0:
                if acc < MIN_ACC_THRESHOLD:
                    continue    # Çok düşük doğruluk → ensemble dışı
                # CAWPE üstel ağırlık (Large et al. 2019):
                # w = acc^k (k=4) — güçlü modeli vurgular, küçük veride ideal
                # Lineer w=acc yerine çok daha seçici ağırlıklandırma
                w = acc ** 4
            else:
                w = WEIGHTS.get(name, 0.10) ** 4  # Fallback: sabit
            try:
                p = model.predict_proba(X)[0]  # [p_ev, p_ber, p_dep]
                if proba_sum is None:
                    proba_sum = p * w
                else:
                    proba_sum += p * w
                weight_sum += w
                sources.append(name)
            except Exception:
                continue

        if proba_sum is None or weight_sum == 0:
            return None

        # Normalize
        proba = proba_sum / weight_sum
        p1, px, p2 = float(proba[0]), float(proba[1]), float(proba[2])

        # Confidence: en yüksek olasılık
        confidence = round(max(p1, px, p2), 4)

        return {
            "p1":         round(p1, 4),
            "px":         round(px, 4),
            "p2":         round(p2, 4),
            "confidence": confidence,
            "source":     "+".join(sources),
            "n_samples":  self.n_samples,
        }

    # ── Veri Hazırlık ─────────────────────────────────────────────────────────
    @staticmethod
    def build_features(match: dict,
                       position: int = None,
                       season_week: int = 20,
                       devret_flag: int = 0,
                       draw_rate_pos: float = 0.22,
                       league_draw_rate: float = 0.25,
                       elo_diff: float = 0.0,
                       form_h: float = 1.5,
                       form_a: float = 1.5) -> list:
        """
        Maç dict'inden 15 feature vektörü oluştur.
        TrainingLoader._row_to_features ile aynı boyut ve sıra.
        ARAŞTIRMA (Haziran 2026): 28 → 15 (korelasyonlu özellikler çıkarıldı)
        Sıra: p1_pin, px_pin, p2_pin, odds_spread,
              lam_h, lam_a, lam_diff, over25, form_diff,
              lm_h, lm_d, season_week, is_home_fav, draw_rate_lig, pos_diff_norm
        """
        import math

        p1 = float(match.get("P1", 45.0)) / 100.0
        px = float(match.get("PX", 27.0)) / 100.0
        p2 = float(match.get("P2", 28.0)) / 100.0

        odds = match.get("odds", {}) or {}
        o1 = float(odds.get("1") or 0) or (1.0 / p1 if p1 else 2.5)
        ox = float(odds.get("X") or 0) or (1.0 / px if px else 3.2)
        o2 = float(odds.get("2") or 0) or (1.0 / p2 if p2 else 2.8)

        # normalize
        raw = 1/o1 + 1/ox + 1/o2
        p1_b = round((1/o1)/raw, 4)
        px_b = round((1/ox)/raw, 4)
        p2_b = round((1/o2)/raw, 4)
        odds_spread = round(max(o1,ox,o2) - min(o1,ox,o2), 2)

        # Pinnacle/Avg bilinmiyorsa B365 kullan
        p1_pin = p1_b; px_pin = px_b; p2_pin = p2_b
        p1_avg = p1_b; px_avg = px_b; p2_avg = p2_b

        # Line movement bilinmiyor
        lm_h = 0.0; lm_d = 0.0; lm_a = 0.0

        # Lambda
        lam_h = max(0.2, round(-math.log(max(0.01, 1-p1_b))*1.5, 3))
        lam_a = max(0.2, round(-math.log(max(0.01, 1-p2_b))*1.5, 3))
        lam_diff = round(lam_h - lam_a, 3)

        # O/U
        over25 = 0.52; under25 = 0.48

        # Form
        fhgf = round(form_h, 3); fhga = 1.5
        fagf = round(form_a, 3); faga = 1.5
        fdiff = round((fhgf - fhga) - (fagf - faga), 3)

        is_hf = 1 if o1 < o2 else 0
        pos   = position or match.get("no", 8)
        dr    = round(league_draw_rate, 3)

        # pos_diff_norm: elo_diff proxy (inference에서 bilinmiyor → 0.0)
        pos_diff_norm = round(elo_diff / 18.0, 3) if elo_diff != 0.0 else 0.0
        # ARAŞTIRMA GÜNCELLEMESİ (Haziran 2026): 28 → 15 özellik
        # Korelasyonlu gruplar tek temsilciyle tutuldu (p1_pin en güçlü)
        # Sıra FEATURE_NAMES ile senkron olmalı
        return [
            p1_pin, px_pin, p2_pin,   # Oran (Shin-kalibre)
            odds_spread,               # Spread
            lam_h, lam_a, lam_diff,   # Lambda
            over25,                    # O/U
            fdiff,                     # Form diff
            lm_h, lm_d,               # Line movement
            season_week, is_hf, dr,   # Bağlam
            pos_diff_norm,             # Pozisyon
        ]

    # ── Durum Raporu ─────────────────────────────────────────────────────────
    def status(self) -> str:
        lines = ["\n  ── ML Engine Durumu ────────────────────"]
        lines.append(f"  Toplam eğitim verisi: {self.n_samples} maç")
        lines.append(f"  Minimum gerekli (GB): {MIN_SAMPLES_GB} maç")
        lines.append(f"  Hazır: {'EVET' if any(self.trained.values()) else 'HAYIR — LPRM aktif'}")
        for name in ["lr","gb","mlp","rf"]:
            if self.trained.get(name, False):
                acc = self.accuracy.get(name, 0)
                # Dinamik ağırlık göster
                dyn_w = f"{acc:.3f}" if acc > 0 else WEIGHTS.get(name, "?")
                lines.append(f"    {name.upper()}: ✅ %{acc*100:.1f}  (ağırlık: {dyn_w})")
            else:
                lines.append(f"    {name.upper()}: ⏳ bekliyor")
        if self.feature_importances:
            lines.append("  Top-5 özellik (GB):")
            for k,v in list(self.feature_importances.items())[:5]:
                lines.append(f"    {k:<22}: {v:.4f}")
        lines.append("  ────────────────────────────────────────")
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────
_ml_instance: Optional[AugurML] = None


def get_ml() -> AugurML:
    """Singleton ML instance döndür, gerekirse modeli yükle."""
    global _ml_instance
    if _ml_instance is None:
        _ml_instance = AugurML()
        _ml_instance.load()
    return _ml_instance
