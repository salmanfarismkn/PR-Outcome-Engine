# PR Outcome Engine data collection and release runbook

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

Automatic stale recovery is a separate process and is disabled by default.
This prevents one recovery scheduler from starting in every API worker. Start
exactly one instance under the deployment process manager after setting
`WEBHOOK_RECOVERY_ENABLED=true`:

```powershell
$env:WEBHOOK_RECOVERY_ENABLED = "true"
uv run python scripts\run_webhook_recovery.py
```

The scheduler runs one recovery cycle immediately and then repeats every five
minutes by default. Configure `WEBHOOK_RECOVERY_INTERVAL_SECONDS`,
`WEBHOOK_RECOVERY_STALE_MINUTES`, `WEBHOOK_RECOVERY_MAX_ATTEMPTS`, and
`WEBHOOK_RECOVERY_BATCH_LIMIT` in the process environment. Command-line
options on `run_webhook_recovery.py` override these numeric settings. Stop it
with Ctrl+C or the process manager's normal stop command; the current cycle
finishes before shutdown. Database failures are logged and retried on the next
cycle. The existing `scripts\recover_webhooks.py` command remains dry-run by
default and is independent of this process.

For local PostgreSQL and pgAdmin containers, copy the root `.env.example` to
`.env` and set distinct non-empty random URL-safe values for
`POSTGRES_PASSWORD` and `PGADMIN_DEFAULT_PASSWORD`. Compose requires both
instead of supplying development passwords. Validate without starting
services using `docker compose --env-file .env config --quiet`; start them
only when needed with `docker compose --env-file .env up -d`. PostgreSQL and
pgAdmin bind to loopback (`127.0.0.1`) by default. `POSTGRES_HOST_PORT` and
`PGADMIN_HOST_PORT` can change the host-side ports. pgAdmin waits for the
PostgreSQL health check; containers communicate on the Compose network using
hostname `postgres` and port 5432. For a backend run on the host, set
`DATABASE_URL` in `backend/.env` to connect through `127.0.0.1` and the chosen
host port with the same PostgreSQL credentials. Compose does not start a
backend container and this local setup is not a production deployment.
Existing Postgres and pgAdmin volumes retain their initialization
credentials; changing Compose environment values does not rotate them. Do
not delete volumes as a password-reset shortcut. `DEBUG` defaults to
false, but a local `.env` or process environment can override the default.
Set `DEBUG=false` explicitly before starting a demo so SQL statements and
parameters are not echoed.

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

If committing the final `processed` status fails, the endpoint returns HTTP
500 rather than a processed-success response. It rolls back that status
transaction and attempts to persist `failed`. If the database also rejects
that update, the last durable state remains `processing`; the delivery payload
was committed before dispatch, and a redelivery with the same delivery ID
will retry any status other than `processed`. Check the stored status before
manual recovery; do not assume a failed status transition was persisted.

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

### Operator-controlled stale recovery

The backend includes a dry-run-by-default recovery command for stale
`received` and `processing` events. The default stale threshold is 15 minutes
and the default recovery limit is 3 attempts per delivery. Recovery is not a
scheduler or background worker; run it explicitly from `backend/` after
checking the dry-run output:

```powershell
uv run python scripts\recover_webhooks.py
uv run python scripts\recover_webhooks.py --stale-minutes 30 --limit 25
uv run python scripts\recover_webhooks.py --execute --stale-minutes 30 --limit 10
```

`--execute` is required before an event is claimed or dispatched. The command
prints only event ID, delivery ID, event type, status, age, and attempt count;
it never prints stored payloads or secrets. PostgreSQL row locks with
`SKIP LOCKED` prevent two recovery commands from claiming the same event, and
the claim transaction is committed before handler execution.

Pull-request, review, check-run, and push deliveries are replayed only through
the existing dispatcher. Their primary records use GitHub IDs or delivery
uniqueness checks, but replay can still repeat GitHub read calls and derived
database work. `pending` events remain reserved for the existing
PR-triggered review replay path. `failed` and exhausted events are not
automatically retried; inspect them and redeliver from GitHub or resolve them
manually. A handler failure is returned to `received` until the attempt limit
is reached, then recorded as `failed`. A recovery command failure leaves the
claimed event in `processing` or the last durable state; rerun the dry-run
after resolving the database or handler issue.

To inspect exhausted or failed deliveries without exposing payloads:

```sql
SELECT id, delivery_id, event_type, status, attempt_count,
       last_attempt_at, last_error_at, error_message
FROM webhook_event
WHERE status = 'failed' OR attempt_count >= 3
ORDER BY updated_at DESC
LIMIT 100;
```

### Health, readiness, and webhook observability

`GET /health` is a liveness check and returns healthy when the application
process is running. `GET /ready` performs a lightweight database query and
returns HTTP 503 when the database is unavailable; it does not expose
connection details.

Recovery command output includes a database-backed status summary for total,
received, processing, pending, processed, failed, exhausted, eligible, and
oldest unrecovered events. Application logs include event and delivery IDs,
status transitions, attempt counts, failure category, and processing duration.
Payloads, credentials, and tokens are not logged.

Failed events are not automatically requeued. The current CLI supports
operator-controlled stale recovery only for `received` and `processing`
events. Requeueing an exhausted or permanently invalid event requires manual
review and a new explicit operator procedure; the current API does not provide
an authenticated manual requeue endpoint or individual operator identity
audit.

## PostgreSQL integration verification

The repository's PostgreSQL integration tests target PostgreSQL 17, matching
the existing `docker-compose.yml` service. They require a separate database
and never fall back to the application's development `DATABASE_URL`.

Required environment variable:

- `PR_OUTCOME_ENGINE_TEST_DATABASE_URL` — a `postgresql+psycopg` URL for a dedicated
  integration database.

The normal application configuration may also require `DATABASE_URL`,
`GITHUB_WEBHOOK_SECRET`, `API_READ_TOKEN`, and `API_ADMIN_TOKEN`; do not put
their values in documentation or command history. The integration test
process uses `PR_OUTCOME_ENGINE_TEST_DATABASE_URL` as its database URL and refuses
to continue if it is the same as `DATABASE_URL`.

Configure the dedicated database and apply migrations explicitly. The
commands below do not create, drop, or reset a database:

```powershell
Set-Location backend
$env:PR_OUTCOME_ENGINE_TEST_DATABASE_URL = Read-Host "Dedicated PostgreSQL test URL"
$previousDatabaseUrl = $env:DATABASE_URL
$env:DATABASE_URL = $env:PR_OUTCOME_ENGINE_TEST_DATABASE_URL
uv run alembic upgrade head
uv run alembic current
uv run alembic heads
uv run alembic check
if ($null -eq $previousDatabaseUrl) {
    Remove-Item Env:DATABASE_URL
} else {
    $env:DATABASE_URL = $previousDatabaseUrl
}
uv run pytest tests\integration -m postgres -q
```

Run the full suite separately:

```powershell
uv run pytest tests -q
uv run ruff check app tests scripts migrations
```

The integration suite covers duplicate delivery uniqueness, independent
sessions, `FOR UPDATE SKIP LOCKED` claims, crash-after-claim recovery,
attempt-count persistence, handler failures, malformed payloads, and migration
columns/indexes. The recovery migration preserves existing webhook IDs and
adds database-generated IDs for new webhook rows. A missing test URL causes
all nine PostgreSQL tests to be skipped with a prerequisite message; skipped
tests are not PostgreSQL verification.

Tests use unique delivery IDs and delete only their own rows during cleanup.
If a test process terminates before cleanup, inspect the dedicated database
and remove only rows with the `postgres-` delivery prefix after confirming no
test is running. Never clean the development or production database.

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

The repository-wide Ruff command is `uv run ruff check app scripts tests`;
require it to pass before the demo. It checks code without modifying files.

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
