
import json
import statistics
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

URL = "http://127.0.0.1:8000/dataset/training"

FEATURES = [
    "additions",
    "deletions",
    "changed_files",
    "commit_count",
    "unique_authors",
    "review_count",
    "unique_reviewers",
    "approvals",
    "change_requests",
    "check_count",
    "successful_checks",
    "failed_checks",
    "pending_checks",
    "is_draft",
    "age_hours",
]


def main():
    request = urllib.request.Request(
        URL,
        headers={"Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"Could not fetch training dataset: {exc}")

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("examples", payload.get("data"))
        if not isinstance(rows, list):
            raise SystemExit(
                "Unexpected API response structure. "
                "Inspect training_dataset.json and adjust the parser."
            )
    else:
        raise SystemExit("Unexpected API response type.")

    if not rows:
        raise SystemExit("Training dataset is empty.")

    output = Path("training_dataset.json")
    output.write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )

    labels = Counter(row.get("label") for row in rows)

    print("\n=== DATASET SUMMARY ===")
    print(f"Total examples: {len(rows)}")
    print(f"Labels: {dict(labels)}")
    print(f"Missing labels: {sum(not r.get('label') for r in rows)}")
    print(
        "Duplicate PR IDs:",
        len(rows) - len({
            r.get("pull_request_id") for r in rows
        }),
    )

    print("\n=== FEATURE DISTRIBUTION ===")
    for feature in FEATURES:
        values = [
            row[feature]
            for row in rows
            if row.get(feature) is not None
        ]

        if not values:
            print(f"{feature:20} NO DATA")
            continue

        numeric = [float(value) for value in values]

        print(
            f"{feature:20} "
            f"min={min(numeric):10.3f} "
            f"max={max(numeric):10.3f} "
            f"mean={statistics.mean(numeric):10.3f} "
            f"distinct={len(set(numeric))}"
        )

    print("\n=== CLASS-SPECIFIC CHECKS ===")
    for label in ("healthy", "problematic", "uncertain"):
        subset = [r for r in rows if r.get("label") == label]
        print(f"\n{label}: {len(subset)} examples")

        for feature in (
            "additions",
            "deletions",
            "changed_files",
            "commit_count",
            "failed_checks",
            "successful_checks",
        ):
            values = [r[feature] for r in subset if r.get(feature) is not None]
            if values:
                print(
                    f"  {feature:20} "
                    f"min={min(values)}, max={max(values)}, "
                    f"distinct={len(set(values))}"
                )

    feature_keys = [
        tuple(row.get(feature) for feature in FEATURES)
        for row in rows
    ]
    print("\n=== DUPLICATE FEATURE VECTORS ===")
    print(f"Unique vectors: {len(set(feature_keys))}")
    print(f"Repeated rows beyond first occurrence: "
          f"{len(feature_keys) - len(set(feature_keys))}")

    print("\n=== CI LABEL SANITY CHECK ===")
    for label in ("healthy", "problematic"):
        subset = [r for r in rows if r.get("label") == label]
        failed = sum((r.get("failed_checks") or 0) > 0 for r in subset)
        print(
            f"{label}: {failed}/{len(subset)} examples "
            "have failed_checks > 0"
        )


if __name__ == "__main__":
    main()
