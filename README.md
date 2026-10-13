# PR Outcome Engine

This repository has been scaffolded with the requested project structure.

## Structure

- backend/
- frontend/
- infrastructure/
- docs/
- scripts/
- .github/

## Outcome labeling and training

Outcome labels are evidence-based and are recalculated in place for each PR:

- A verified revert is labeled `problematic`.
- A completed `failure`, `timed_out`, or `action_required` CI check for the
  current PR head is labeled `problematic`.
- A merged PR is labeled `healthy` only when it has at least one check for its
  current head and every such check completed with `success`.
- Missing head/check evidence, pending or in-progress checks, cancelled checks,
  and other non-success conclusions are labeled `uncertain`.
- Review requests are not themselves defect evidence; a merged PR may have
  resolved an earlier request for changes.
- Unmerged PRs remain `uncertain`.

The supervised dataset contains one row per merged PR, selecting the latest
feature snapshot created at or before its merge timestamp. This represents
prediction immediately before merge and excludes post-merge snapshots.

## Prospective training data collection

Configure the repository webhook in **Settings > Webhooks > Add webhook**:

1. Set the payload URL to the publicly reachable application URL ending in
   `/webhooks/github` (for local testing, expose the local server through a
   trusted tunnel).
2. Set **Content type** to `application/json`, enable SSL verification, and
   set a strong webhook secret. Put the same value in the backend's
   `GITHUB_WEBHOOK_SECRET` environment variable; do not commit or share it.
3. Select **Let me select individual events**, then enable **Pull requests**,
   **Pull request reviews**, and **Check runs**. Keep all activity types for
   those event families enabled, or at minimum include PR `opened`, `reopened`,
   `synchronize`, `closed`; review `submitted`, `edited`, `dismissed`; and
   check-run `created`, `rerequested`, `completed`.
   Also enable **Pushes** if push-based revert detection is required.
4. Save the webhook. Use GitHub's **Recent Deliveries** page to confirm that
   `pull_request_review` deliveries reach `/webhooks/github` and receive a
   successful response.

Open/reopened/synchronized PRs sync commits and changed files before checks,
reviews, feature snapshots, and outcome evaluation. Review/check events refresh
their evidence and snapshot only while the PR is unmerged. A merged PR's
completed checks can still update its outcome, but do not create or alter a
training snapshot.

Snapshot creation skips closed/merged PRs and incomplete source records. Webhook
processing failures are recorded as failed or pending deliveries; inspect the
webhook event status and application logs when an event does not complete. A
review delivery that arrives before its PR is ingested stays pending and is
retried when the matching PR webhook is processed; it is not discarded.
Do not backdate or manually create pre-merge snapshots for historical PRs.

From `backend/`, periodically run
`uv run python scripts/audit_training_readiness.py`. This read-only audit
reports eligible rows by outcome, repository, and pre-merge snapshot
completeness, plus repository-grouped partition class counts when a valid split
is possible. It does not fit or save a model. Evaluation requires at least 30
eligible examples and healthy and problematic examples represented in at least
two repositories each; a single-repository dataset is reported
`not_evaluable`.

When the audit reports a valid repository-grouped split, run
`uv run python scripts/evaluate_pr_dataset.py` to calculate non-persisting
evaluation metrics. That command fits only an in-memory evaluation model and
does not save a model artifact. Continue collecting prospective examples if
either command reports `not_evaluable`; do not backdate snapshots or weaken
evidence requirements to force evaluation.
