import pandas as pd

from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

from app.ml.model import FEATURE_COLUMNS


class PRRiskModelService:

    def train(
        self,
        dataset: list[dict],
    ):

        if len(dataset) < 10:
            raise ValueError(
                "At least 10 labeled training examples are required."
            )

        df = pd.DataFrame(dataset)

        # -----------------------------------------
        # Features
        # -----------------------------------------

        X = df[FEATURE_COLUMNS]

        # -----------------------------------------
        # Labels
        # -----------------------------------------

        y = (
            df["label"]
            .map(
                {
                    "healthy": 0,
                    "problematic": 1,
                }
            )
        )

        if y.isna().any():
            raise ValueError(
                "Dataset contains invalid labels."
            )

        if y.nunique() < 2:
            raise ValueError(
                "Training requires both healthy and problematic examples."
            )

        # -----------------------------------------
        # Train / test split
        # -----------------------------------------

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=0.2,
            random_state=42,
            stratify=y,
        )

        # -----------------------------------------
        # Model
        # -----------------------------------------

        model = LogisticRegression(
            max_iter=1000,
        )

        model.fit(
            X_train,
            y_train,
        )

        # -----------------------------------------
        # Evaluation
        # -----------------------------------------

        predictions = model.predict(X_test)

        accuracy = accuracy_score(
            y_test,
            predictions,
        )

        report = classification_report(
            y_test,
            predictions,
            output_dict=True,
            zero_division=0,
        )

        matrix = confusion_matrix(
            y_test,
            predictions,
        )

        return {
            "model": model,
            "accuracy": float(accuracy),
            "classification_report": report,
            "confusion_matrix": matrix.tolist(),
            "training_rows": len(X_train),
            "testing_rows": len(X_test),
        }