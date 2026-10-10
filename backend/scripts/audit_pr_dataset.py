
import json
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
    "is_draft",
    "age_hours",
]


def main():
    request = urllib.request.Request(
        URL,
        headers={"Accept": "application/json"},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (
                value
                for key in ("rows", "data", "items", "dataset")
                if isinstance((value := payload.get(key)), list)
            ),
            None,
        )
        if rows is None:
            raise ValueError(
                f"Could not find dataset rows. Response keys: "
                f"{list(payload.keys())}"
            )
    else:
        raise ValueError("Unexpected dataset response format.")

    if not rows:
        raise ValueError("The training dataset is empty.")

    print(f"\nTotal rows: {len(rows)}")

    labels = Counter(row.get("label") for row in rows)
    print("\nLabel distribution:")
    for label, count in sorted(labels.items(), key=lambda x: str(x[0])):
        print(f"  {label}: {count}")

    ids = [row.get("pull_request_id") for row in rows]
    print(f"\nUnique PR IDs: {len(set(ids))}")
    print(f"Duplicate PR IDs: {len(ids) - len(set(ids))}")

    print("\nFeature quality:")
    for feature in FEATURES:
        values = [row.get(feature) for row in rows]
        present = [value for value in values if value is not None]
        distinct = set(present)

        print(
            f"  {feature:20} "
            f"present={len(present):3}/{len(rows)} "
            f"distinct={len(distinct):3} "
            f"constant={len(distinct) <= 1}"
        )

    vectors = [
        tuple(row.get(feature) for feature in FEATURES)
        for row in rows
    ]
    print(
        "\nDuplicate feature vectors:",
        len(vectors) - len(set(vectors)),
    )

    print("\nFeature variation by label:")
    for label in sorted(labels, key=str):
        group = [row for row in rows if row.get("label") == label]
        print(f"\n  {label} (n={len(group)})")

        for feature in FEATURES:
            values = {
                row.get(feature)
                for row in group
                if row.get(feature) is not None
            }
            print(f"    {feature:20} distinct={len(values)}")

    report = {
        "total_rows": len(rows),
        "label_distribution": dict(labels),
        "duplicate_pr_ids": len(ids) - len(set(ids)),
        "duplicate_feature_vectors": len(vectors) - len(set(vectors)),
    }

    output = Path("artifacts/dataset_audit_summary.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSummary saved to: {output}")


if __name__ == "__main__":
    main()
