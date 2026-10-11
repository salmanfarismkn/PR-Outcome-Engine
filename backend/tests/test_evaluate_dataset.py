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
