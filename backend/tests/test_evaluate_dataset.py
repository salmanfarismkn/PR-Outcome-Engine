import app.main  # noqa: F401
from scripts import evaluate_pr_dataset


def test_single_class_dataset_is_not_evaluated_or_saved(
    monkeypatch,
) -> None:
    class SingleClassModel:
        def train(self, dataset, *, save_model):
            assert dataset == [{"label": "problematic"}]
            assert save_model is False
            raise ValueError(
                "Training requires healthy and problematic examples."
            )

    monkeypatch.setattr(
        evaluate_pr_dataset,
        "PRRiskModelService",
        SingleClassModel,
    )

    result = evaluate_pr_dataset.evaluate_dataset(
        [{"label": "problematic"}]
    )

    assert result == {
        "evaluation_status": "not_evaluable",
        "evaluation_reason": (
            "Training requires healthy and problematic examples."
        ),
    }


def test_readiness_report_flags_repository_and_partition_limits() -> None:
    report = evaluate_pr_dataset.build_readiness_report(
        [
            {
                "pull_request_id": 1,
                "repository_id": 10,
                "label": "healthy",
            },
            {
                "pull_request_id": 2,
                "repository_id": 10,
                "label": "problematic",
            },
        ],
        [
            {
                "repository_id": 10,
                "repository": "owner/repo",
                "outcome": "healthy",
                "eligible_snapshot_count": 1,
            },
            {
                "repository_id": 10,
                "repository": "owner/repo",
                "outcome": "healthy",
                "eligible_snapshot_count": 0,
            },
            {
                "repository_id": 10,
                "repository": "owner/repo",
                "outcome": "problematic",
                "eligible_snapshot_count": 1,
            },
        ],
        {
            "evaluation_status": "not_evaluable",
            "evaluation_reason": "insufficient repositories",
        },
    )

    assert report["repository_count"] == 1
    assert report["repositories_per_eligible_class"] == {
        "healthy": 1,
        "problematic": 1,
    }
    assert report["repository_diversity_sufficient"] is False
    assert report["evaluation_partitions"] is None
    assert (
        report["evaluation_partitions_unavailable_reason"]
        == "insufficient repositories"
    )
    healthy_eligibility = next(
        item
        for item in report[
            "outcome_snapshot_eligibility_by_repository_and_outcome"
        ]
        if item["outcome"] == "healthy"
    )
    assert healthy_eligibility["outcomes"] == 2
    assert healthy_eligibility["complete_premerge_snapshot"] == 1
    assert healthy_eligibility["missing_complete_premerge_snapshot"] == 1
    assert healthy_eligibility["eligible_training_rows"] == 1
