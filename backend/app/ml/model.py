from dataclasses import dataclass
from typing import Any

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


FEATURE_COLUMNS = [
    "additions",
    "deletions",
    "changed_files",
    "commit_count",
    "unique_authors",
    "review_count",
    "unique_reviewers",
    "approvals",
    "change_requests",
    "is_draft",
    "age_hours",
]


@dataclass
class TrainingResult:
    model: Pipeline
    metrics: dict[str, Any]
    train_size: int
    test_size: int


def train_baseline(examples: list[dict]) -> TrainingResult:
    if len(examples) < 30:
        raise ValueError(
            f"Need at least 30 labeled examples; received {len(examples)}."
        )

    df = pd.DataFrame(examples)

    required_columns = FEATURE_COLUMNS + ["label"]
    missing = set(required_columns) - set(df.columns)
    if missing:
        raise ValueError(
            f"Dataset is missing required columns: {sorted(missing)}"
        )

    df = df[required_columns].copy()
    df = df.dropna(subset=required_columns)

    # The classifier must learn both classes.
    if df["label"].nunique() != 2:
        raise ValueError("Training requires both healthy and problematic labels.")

    # Map the positive class explicitly.
    y = (df["label"] == "problematic").astype(int)
    X = df[FEATURE_COLUMNS].astype(float)

    if y.value_counts().min() < 2:
        raise ValueError("Each class needs at least two examples.")

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
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=42,
                ),
            ),
        ]
    )

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    probabilities = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
        "precision_problematic": round(
            float(precision_score(y_test, predictions, zero_division=0)), 4
        ),
        "recall_problematic": round(
            float(recall_score(y_test, predictions, zero_division=0)), 4
        ),
        "f1_problematic": round(
            float(f1_score(y_test, predictions, zero_division=0)), 4
        ),
        "roc_auc": (
            round(float(roc_auc_score(y_test, probabilities)), 4)
            if y_test.nunique() == 2
            else None
        ),
        "confusion_matrix": confusion_matrix(
            y_test, predictions, labels=[0, 1]
        ).tolist(),
        "classification_report": classification_report(
            y_test,
            predictions,
            labels=[0, 1],
            target_names=["healthy", "problematic"],
            zero_division=0,
            output_dict=True,
        ),
        "feature_columns": FEATURE_COLUMNS,
    }

    return TrainingResult(
        model=model,
        metrics=metrics,
        train_size=len(X_train),
        test_size=len(X_test),
    )