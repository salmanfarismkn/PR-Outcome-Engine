import pytest

import app.main  # noqa: F401
from app.ml.model import FEATURE_COLUMNS
from app.ml.service import PRRiskModelService


def _dataset(repository_count: int) -> list[dict]:
    rows = []
    for repository_id in range(repository_count):
        for label in ("healthy", "problematic"):
            for sample in range(20):
                row = {
                    feature: 1
                    for feature in FEATURE_COLUMNS
                }
                row.update(
                    {
                        "pull_request_id": (
                            repository_id * 40
                            + (0 if label == "healthy" else 20)
                            + sample
                        ),
                        "repository_id": repository_id,
                        "label": label,
                    }
                )
                rows.append(row)
    return rows


def test_single_repository_is_not_evaluable_for_repository_holdout() -> None:
    with pytest.raises(
        ValueError,
        match="at least two repositories containing examples",
    ):
        PRRiskModelService().train(
            _dataset(1),
            save_model=False,
        )


def test_repository_grouped_split_keeps_repositories_separate() -> None:
    dataset = _dataset(4)
    partitions = PRRiskModelService.get_partition_class_counts(dataset)
    result = PRRiskModelService().train(
        dataset,
        save_model=False,
    )

    assert partitions == {
        "training": {"healthy": 60, "problematic": 60},
        "testing": {"healthy": 20, "problematic": 20},
    }
    assert result["model_path"] is None
    assert (
        result["metrics"]["split_strategy"]
        == "StratifiedGroupKFold by repository_id"
    )
    assert result["metrics"]["training_class_distribution"] == {
        "healthy": 60,
        "problematic": 60,
    }
    assert result["metrics"]["testing_class_distribution"] == {
        "healthy": 20,
        "problematic": 20,
    }
