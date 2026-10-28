import os
import numpy as np
import pandas as pd
import joblib
from typing import Dict, List, Optional, Tuple

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (accuracy_score, log_loss, brier_score_loss,
                             classification_report)

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except Exception:
    HAS_XGB = False


class ModelTrainer:
    def __init__(self):
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_names: List[str] = []
        self.classes_: List[str] = []

    # ---------- Base estimator ----------
    def _base_estimator(self):
        rf = RandomForestClassifier(
            n_estimators=200, max_depth=12, random_state=42,
            class_weight="balanced", n_jobs=-1)
        if not HAS_XGB:
            return rf
        xgb = XGBClassifier(
            n_estimators=300, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            use_label_encoder=False, eval_metric="mlogloss",
            random_state=42, verbosity=0)
        # Expose XGB separately for SHAP later
        self._xgb_estimator = xgb
        return xgb  # XGB alone; RF used as fallback

    # ---------- Training ----------
    def train_model(self, df: pd.DataFrame,
                    feature_cols: Optional[List[str]] = None,
                    time_col: str = "timestamp"
                    ) -> Tuple[Optional[float], Optional[Dict]]:
        """
        Time-series split: train on 80% earliest, validate on 20% latest.
        Returns (accuracy, metrics_dict). No random shuffling.
        """
        if df.empty or len(df) < 100:
            return None, None

        df = df.sort_values(time_col).reset_index(drop=True)
        if "result" not in df.columns:
            return None, None

        if feature_cols is None:
            feature_cols = [c for c in df.columns
                            if c not in ("result", "fixture_id", "date",
                                         "timestamp", "home", "away",
                                         "home_id", "away_id",
                                         "league_id", "league_name",
                                         "season", "referee", "venue",
                                         "home_goals", "away_goals")]
        self.feature_names = feature_cols

        X = df[feature_cols].fillna(0.0).to_numpy(dtype=float)
        y = df["result"].to_numpy()

        split = int(len(X) * 0.8)
        X_tr, X_te = X[:split], X[split:]
        y_tr, y_te = y[:split], y[split:]

        self.scaler.fit(X_tr)
        X_tr_s = self.scaler.transform(X_tr)
        X_te_s = self.scaler.transform(X_te)

        base = self._base_estimator()
        # Calibrate on training only
        calibrated = CalibratedClassifierCV(base, method="isotonic", cv=3)
        calibrated.fit(X_tr_s, y_tr)

        pred = calibrated.predict(X_te_s)
        proba = calibrated.predict_proba(X_te_s)
        self.classes_ = list(calibrated.classes_)

        acc = float(accuracy_score(y_te, pred))
        ll = float(log_loss(y_te, proba, labels=self.classes_))
        # Brier (multiclass average, one-vs-rest)
        briers = []
        for i, cls in enumerate(self.classes_):
            briers.append(brier_score_loss(
                (y_te == cls).astype(int), proba[:, i]))
        brier = float(np.mean(briers))

        self.model = calibrated
        self.is_trained = True

        metrics = {
            "accuracy": acc,
            "log_loss": ll,
            "brier": brier,
            "n_train": len(X_tr),
            "n_test": len(X_te),
            "report": classification_report(y_te, pred, output_dict=True),
        }
        return acc, metrics

    # ---------- Predict ----------
    def predict_match(self, features: List[float]) -> Dict:
        if not self.is_trained:
            raise ValueError("Model not trained")
        feats = self.scaler.transform(np.asarray([features], dtype=float))
        pred = self.model.predict(feats)[0]
        proba = self.model.predict_proba(feats)[0]
        classes = list(self.model.classes_)
        result_map = {"H": "Home Win", "D": "Draw", "A": "Away Win"}
        return {
            "prediction": result_map[pred],
            "probabilities": {
                "Home Win": float(proba[classes.index("H")]) if "H" in classes else 0.0,
                "Draw":     float(proba[classes.index("D")]) if "D" in classes else 0.0,
                "Away Win": float(proba[classes.index("A")]) if "A" in classes else 0.0,
            },
            "confidence": float(max(proba)),
            "_scaled_features": feats,
        }

    # ---------- SHAP on XGB sub-model ----------
    def get_shap_attributions(self, features: List[float],
                              top_k: int = 5) -> List[Dict]:
        """SHAP TreeExplainer directly on XGBoost (voting ensembles break SHAP)."""
        try:
            import shap
        except ImportError:
            return self._importance_fallback(features, top_k)

        xgb = getattr(self, "_xgb_estimator", None)
        if xgb is None:
            return self._importance_fallback(features, top_k)

        try:
            feat_arr = np.asarray([features], dtype=float)
            scaled = self.scaler.transform(feat_arr)
            explainer = shap.TreeExplainer(xgb)
            sv = explainer.shap_values(scaled)
            # multiclass: list of arrays, one per class
            if isinstance(sv, list):
                stacked = np.zeros_like(sv[0])
                for arr in sv:
                    mask = np.abs(arr) > np.abs(stacked)
                    stacked = np.where(mask, arr, stacked)
                vals = stacked[0]
            else:
                vals = sv[0]
            total = float(np.sum(np.abs(vals))) or 1.0
            pairs = sorted(
                [(self.feature_names[i], float(vals[i]) / total)
                 for i in range(len(self.feature_names))],
                key=lambda p: abs(p[1]), reverse=True)[:top_k]
            return [{"label": n.replace("_", " ").title(),
                     "impact": round(v, 3)} for n, v in pairs]
        except Exception:
            return self._importance_fallback(features, top_k)

    def _importance_fallback(self, features, top_k):
        xgb = getattr(self, "_xgb_estimator", None)
        if xgb is None:
            return []
        try:
            imps = xgb.feature_importances_
            vals = np.asarray(features, dtype=float)
            scored = sorted(
                [(self.feature_names[i],
                  float(imps[i]) * (1 if vals[i] >= 0 else -1))
                 for i in range(min(len(imps), len(vals)))],
                key=lambda p: abs(p[1]), reverse=True)[:top_k]
            return [{"label": n.replace("_", " ").title(),
                     "impact": round(v, 3)} for n, v in scored]
        except Exception:
            return []

    # ---------- Persistence ----------
    def save_model(self, path: str):
        if not self.is_trained:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        joblib.dump({
            "model": self.model,
            "scaler": self.scaler,
            "is_trained": True,
            "feature_names": self.feature_names,
            "classes": self.classes_,
            "xgb_estimator": getattr(self, "_xgb_estimator", None),
        }, path)

    def load_model(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            data = joblib.load(path)
            self.model = data["model"]
            self.scaler = data["scaler"]
            self.is_trained = True
            self.feature_names = data.get("feature_names", [])
            self.classes_ = data.get("classes", [])
            if data.get("xgb_estimator") is not None:
                self._xgb_estimator = data["xgb_estimator"]
            return True
        except Exception:
            return False