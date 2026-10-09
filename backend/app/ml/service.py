
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.model import FEATURE_COLUMNS


MODEL_PATH = Path("artifacts/pr_risk_model.joblib")


class PRRiskModelService:
    def train(
        self,
        dataset: list[dict],
        save_model: bool = True,
    ) -> dict[str, Any]:
        if len(dataset) < 30:
            raise ValueError(
                f"At least 30 labeled examples are required; got {len(dataset)}."
            )

        df = pd.DataFrame(dataset)

        required_columns = FEATURE_COLUMNS + ["label"]
        missing = set(required_columns) - set(df.columns)

        if missing:
            raise ValueError(
                f"Dataset is missing columns: {sorted(missing)}"
            )

        df = df[required_columns].copy()
        df = df.dropna(subset=required_columns)

        if df.empty:
            raise ValueError("No complete training examples remain.")

        valid_labels = {"healthy", "problematic"}
        if not set(df["label"].unique()).issubset(valid_labels):
            raise ValueError("Dataset contains invalid labels.")

        y = (df["label"] == "problematic").astype(int)
        X = df[FEATURE_COLUMNS].astype(float)

        if y.nunique() != 2:
            raise ValueError(
                "Training requires healthy and problematic examples."
            )

        if y.value_counts().min() < 2:
            raise ValueError(
                "Each class needs at least two examples."
            )

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=0.25,
            random_state=42,
            stratify=y,
        )

        model = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=1000,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        )

        model.fit(X_train, y_train)

        predictions = model.predict(X_test)
        probabilities = model.predict_proba(X_test)[:, 1]

        metrics = {
            "accuracy": float(accuracy_score(y_test, predictions)),
            "precision_problematic": float(
                precision_score(y_test, predictions, zero_division=0)
            ),
            "recall_problematic": float(
                recall_score(y_test, predictions, zero_division=0)
            ),
            "f1_problematic": float(
                f1_score(y_test, predictions, zero_division=0)
            ),
            "roc_auc": float(roc_auc_score(y_test, probabilities)),
            "classification_report": classification_report(
                y_test,
                predictions,
                labels=[0, 1],
                target_names=["healthy", "problematic"],
                zero_division=0,
                output_dict=True,
            ),
            "confusion_matrix": confusion_matrix(
                y_test,
                predictions,
                labels=[0, 1],
            ).tolist(),
        }

        if save_model:
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {
                    "model": model,
                    "feature_columns": FEATURE_COLUMNS,
                    "labels": {
                        0: "healthy",
                        1: "problematic",
                    },
                },
                MODEL_PATH,
            )

        return {
            "metrics": metrics,
            "training_rows": len(X_train),
            "testing_rows": len(X_test),
            "model_path": str(MODEL_PATH) if save_model else None,
            "feature_columns": FEATURE_COLUMNS,
        }

    def load_model(self) -> dict[str, Any]:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Trained model not found at {MODEL_PATH}. Train it first."
            )

        artifact = joblib.load(MODEL_PATH)

        if artifact.get("feature_columns") != FEATURE_COLUMNS:
            raise ValueError(
                "Saved model features do not match the current feature schema."
            )

        return artifact

    def predict(self, features: dict) -> dict:
        artifact = self.load_model()
        model = artifact["model"]
        feature_columns = artifact["feature_columns"]

        missing = set(feature_columns) - set(features)
        if missing:
            raise ValueError(
                f"Missing prediction features: {sorted(missing)}"
            )

        row = pd.DataFrame(
            [{name: features[name] for name in feature_columns}],
            columns=feature_columns,
        ).astype(float)

        if row.isna().any().any():
            raise ValueError("Prediction features cannot contain null values.")

        probability = float(model.predict_proba(row)[0][1])
        prediction = int(model.predict(row)[0])

        return {
            "predicted_outcome": (
                "problematic" if prediction == 1 else "healthy"
            ),
            "problematic_probability": probability,
            "model_version": "logistic-regression-v1",
            "prediction_status": "experimental",
        }
