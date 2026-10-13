# PR Analyzer data collection and release runbook

This runbook is for collecting **real prospective PR evidence** and deciding
whether the resulting dataset supports evaluation. Do not backdate snapshots,
edit labels, or use generated examples as production training data.

## 1. Prepare the backend and register repositories

From `backend/`, configure the backend environment without printing or
committing values:

- `DATABASE_URL` is required by the application.
- `GITHUB_TOKEN` is used for GitHub REST access.
- `GITHUB_WEBHOOK_SECRET` must match the secret configured on each repository
  webhook.
- `GITHUB_API_URL` is optional; it defaults to `https://api.github.com`.
- `API_READ_TOKEN` and `API_ADMIN_TOKEN` must both be configured with distinct,
  high-entropy values. Use the read token for inspection and the admin token
  for repository registration/import operations.

The settings load `.env` relative to the backend working directory. Use the
deployment's normal process manager to start the application. For local
development, `uv run uvicorn app.main:app --reload` serves the API on
`http://127.0.0.1:8000`.
Store secrets in the ignored local `.env` file or deployment secret manager;
never print or commit them. The admin token also grants read access.

The supported repository-import workflow imports repositories visible to the
configured GitHub account and persists them in the database. In PowerShell:

```powershell
$BaseUrl = "http://127.0.0.1:8000"
$AdminTokenSecure = Read-Host "API admin token" -AsSecureString
$AdminToken = [Net.NetworkCredential]::new("", $AdminTokenSecure).Password
$AdminHeaders = @{ Authorization = "Bearer $AdminToken" }
Invoke-RestMethod -Method Post -Uri "$BaseUrl/github/repositories/import" -Headers $AdminHeaders
$ReadTokenSecure = Read-Host "API read token" -AsSecureString
$ReadToken = [Net.NetworkCredential]::new("", $ReadTokenSecure).Password
$ReadHeaders = @{ Authorization = "Bearer $ReadToken" }
$Repositories = Invoke-RestMethod -Method Get -Uri "$BaseUrl/repositories" -Headers $ReadHeaders
$Repositories | Select-Object id, owner, name, default_branch
```

Confirm the additional repositories appear with the intended owner and name.
The returned `id` is the internal repository ID, not a GitHub ID. The import
endpoint calls GitHub and writes repository records to the database; it
imports the authenticated user's accessible repositories, not just one
repository. If the target does not appear, verify token access. The existing
single-repository endpoint is `POST /repositories`; its request schema is
`github_id`, `owner`, `name`, optional `description`, optional
`default_branch` (defaults to `main`), and required `is_private`. Prefer the
GitHub import endpoint so repository IDs and metadata come from GitHub rather
than being entered manually.

All business/data API routes require bearer authentication: use the read token
for GET routes and the admin token for mutations and imports. `/`, `/health`,
and `/ready` are public. `POST /webhooks/github` accepts no API bearer token;
it authenticates only with GitHub's HMAC signature and
`GITHUB_WEBHOOK_SECRET`. This shared-token setup is for a single-operator demo,
not a multi-user identity or repository-level authorization system.

## 2. Configure and verify webhooks in GitHub

For each repository, configure a webhook manually in **Settings > Webhooks**:

1. Use the reachable backend URL ending in `/webhooks/github`, select JSON
   payloads, enable SSL verification, and configure a strong secret matching
   `GITHUB_WEBHOOK_SECRET`. Never put the secret in this runbook, command
   history, or logs.
2. Subscribe to **Pull requests**, **Pull request reviews**, and **Check runs**.
   Keep the activity types used by the application enabled:
   - PR: `opened`, `reopened`, `synchronize`, `closed`
   - Review: `submitted`, `edited`, `dismissed`
   - Check run: `created`, `rerequested`, `completed`
3. Also subscribe to **Pushes** if verified revert evidence is being collected.
4. Use GitHub **Recent Deliveries** to verify actual deliveries have successful
   HTTP responses. The backend validates `X-Hub-Signature-256` before storing
   or dispatching a delivery.

The backend stores a delivery in `webhook_event` with its delivery ID, event
type, status, error, and raw payload before dispatch. Do not query or share the
payload. A delivery with status `processed` completed; `pending` means a
dependency was not yet available; `failed` means processing raised an error.
GitHub does not automatically retry failed deliveries or a delivery that
received HTTP 200 with a `pending` response.

For an event with a missing dependency, correct repository/PR ingestion first,
then use GitHub **Recent Deliveries > Redeliver**. Pending review deliveries
are also retried when a matching PR lifecycle event is processed, after PR
source and check synchronization. Check-run deliveries do not have that
automatic review-retry path; manually redeliver them after the associated PR
has been ingested. Repeated failures remain visible in `webhook_event` and
backend logs; resolve the cause before redelivery.

Do not treat HTTP 200 or `processed` alone as proof that a check was imported:
the check-run handler currently ignores a check if its repository is not
registered, or if the payload has no PR association and no matching commit
association is found. When the payload names a PR that is not yet ingested,
the event is instead marked `pending`. Verify the current-head `check_run` rows
below and manually redeliver the actual check-run delivery after fixing
repository/PR ingestion if evidence is absent.

To inspect delivery status without exposing payloads, run this in the
configured database's SQL console:

```sql
SELECT delivery_id, event_type, status, error_message, created_at
FROM webhook_event
ORDER BY created_at DESC
LIMIT 50;
```

## 3. Collect evidence through normal PR lifecycle events

Collect real PRs created and reviewed through normal project work. A supported
prospective flow is:

1. GitHub sends `pull_request.opened`. The PR webhook persists the PR, syncs
   commits and changed files, imports current checks and reviews, then requests
   a snapshot and evaluates available outcome evidence.
2. Further commits produce `synchronize`; review activity produces review
   deliveries; CI produces check-run deliveries. These update persisted
   evidence and may refresh the feature snapshot while the PR remains open.
3. Before merging, confirm the PR exists in the backend and its current-head
   checks are complete. The status endpoint is:

   ```text
   GET /dataset/pr/github/{owner}/{repo}/{github_pr_number}/status
   ```

   It reports the internal PR ID separately from the GitHub PR number, current
   head SHA, current-head check counts, and whether snapshot/outcome records
   exist. A missing snapshot is not made valid by a successful status response:
   verify the snapshot's stored timestamp and completeness in the database.
4. Keep the PR open until the pre-merge snapshot has been verified. Merged or
   closed PRs do not receive new feature snapshots. A `closed`/merged event
   synchronizes evidence and evaluates the outcome, but must not be used to
   create or backdate a training snapshot.

Reviews do not themselves determine healthy/problematic labels. Current
review/check evidence contributes only to the snapshot features.

### Verify persisted evidence and snapshot timing

Use the internal PR ID obtained from the status endpoint for these read-only
queries. The names below are the actual tables and columns used by the
application. Replace `:internal_pr_id` in each statement with that numeric
internal database ID before running it in a SQL console.

Current-head checks:

```sql
SELECT p.id AS internal_pr_id,
       p.number AS github_pr_number,
       p.head_sha AS current_head_sha,
       c.github_id AS github_check_run_id,
       c.name, c.status, c.conclusion, c.head_sha, c.completed_at
FROM pull_requests AS p
LEFT JOIN check_run AS c
       ON c.pull_request_id = p.id
      AND c.head_sha = p.head_sha
WHERE p.id = :internal_pr_id
ORDER BY c.completed_at;
```

Reviews:

```sql
SELECT p.id AS internal_pr_id,
       p.number AS github_pr_number,
       r.github_id AS github_review_id,
       r.reviewer_login, r.state, r.submitted_at
FROM pull_requests AS p
LEFT JOIN review AS r ON r.pull_request_id = p.id
WHERE p.id = :internal_pr_id
ORDER BY r.submitted_at;
```

Snapshots and outcome, after merge:

```sql
SELECT p.id AS internal_pr_id,
       p.number AS github_pr_number,
       o.outcome, o.reason, o.merged_at,
       s.id AS snapshot_id, s.created_at AS snapshot_created_at,
       s.commit_count, s.changed_files,
       (s.id IS NOT NULL
        AND o.merged_at IS NOT NULL
        AND s.created_at <= o.merged_at
        AND s.commit_count > 0
        AND s.changed_files > 0) AS eligible_premerge_snapshot
FROM pull_requests AS p
LEFT JOIN pull_request_outcome AS o ON o.pull_request_id = p.id
LEFT JOIN pr_feature_snapshot AS s ON s.pull_request_id = p.id
WHERE p.id = :internal_pr_id
ORDER BY s.created_at;
```

The snapshot service only saves snapshots for open PRs with at least one
persisted commit and one changed file. Training selects the latest complete
snapshot with `created_at <= merged_at`. If one is missing, check successful
`pull_request` deliveries and commit/file synchronization before merge. Do not
manually insert a snapshot or change its timestamp. For a missed delivery,
redeliver the actual GitHub PR event; the PR importer alone imports PR metadata
and does not recreate historical pre-merge evidence.

## 4. Verify label policy and dataset eligibility

Outcomes are evidence-based:

- `problematic`: a verified revert, or a completed current-head check with
  conclusion `failure`, `timed_out`, or `action_required`.
- `healthy`: merged, at least one current-head check exists, all current-head
  checks completed with `success`, and no verified revert exists.
- `uncertain`: missing current-head evidence, pending/in-progress checks,
  cancelled checks, or other evidence that does not meet either rule.

Compare `pull_request_outcome.outcome`, `reason`, and `merged_at` with the
current-head check records and known revert evidence before relying on labels.
Do not relabel uncertain outcomes to improve class balance.

From `backend/`, run the read-only readiness audit:

```powershell
uv run python scripts/audit_training_readiness.py
```

It reads the configured database and prints JSON to stdout; it does not train
or save a model/report. Review:

- `training_rows` versus `distinct_pull_requests` (they must be equal);
- `training_label_counts` for both `healthy` and `problematic`;
- `eligible_rows_by_repository_outcome_and_snapshot_completeness`;
- `outcome_snapshot_eligibility_by_repository_and_outcome`;
- `repositories_per_class`, `repository_diversity_sufficient`, and
  `evaluation_partition_class_counts`;
- `evaluation_status` and `evaluation_reason`.

Uncertain outcomes are excluded. Each training PR contributes no more than one
row, selected from a complete snapshot at or before its merge timestamp.
`repository_id` is carried into the evaluator so one repository cannot occur
in both partitions.

The current implementation's technical evaluation gate requires at least 30
eligible rows, both outcome classes, and at least two distinct repositories
containing each class; it must also find a grouped split with both classes in
both partitions. Passing these gates only means a split can be formed. It does
not establish model quality. Collect enough independent repositories and
examples to support the evaluation design and conclusions you intend to make.

## 5. Evaluate only after the data gates pass

Run the non-persisting evaluation from `backend/` only after the audit reports
both classes and valid repository-grouped partitions:

```powershell
uv run python scripts/evaluate_pr_dataset.py
```

This command reads the dataset and fits an in-memory evaluation model with
`save_model=False`; metrics are printed to stdout and no model or report file
is written. Treat output as local data because it includes PR-level audit
details. A `not_evaluable` result is a stop condition, not a reason to relax
the gates.

Do **not** call `POST /ml/train` as part of auditing: that endpoint trains and
writes `artifacts/pr_risk_model.joblib`. Model training and deployment require
separate release approval after evaluation review.

## 6. Test and release checks

Run these from `backend/`:

```powershell
uv run pytest
uv run ruff check app scripts tests
uv run alembic current
uv run alembic check
```

Pytest and Ruff operate on code/tests; they do not backfill or train against
the configured database. `alembic current` reads the database's migration
revision. `alembic check` compares model metadata to the database and reports
pending autogenerated migration operations; it does not apply them.

The repository-wide Ruff command currently reports 38 violations in existing
code. Treat that as an unresolved release gate; this runbook does not change
those files or suppress the findings.

If a reviewed release requires applying pending schema migrations, the
existing command is `uv run alembic upgrade head`. This **writes to the
database**; review migration history, take the approved backup, and apply only
under the normal release change process. Do not run it as part of routine
collection or readiness auditing.

## Generator warning

`scripts/generate_pr_dataset.py` accepts `--owner`, `--repo`, `--repo-path`,
`--count` (default `1`), and `--scenario` (`healthy` or `ci_failure`, default
`healthy`). It validates that `--repo-path` is the root of a matching clone,
then creates generated content, pushes a branch, opens a GitHub PR, waits for
checks, and merges it. It is a mutating integration/test utility, and its PR
content is generated for dataset testing. Do not use it to collect production
training examples or run it as part of this release procedure.
