# PR Outcome Engine

PR Analyzer collects GitHub pull-request evidence and provides API endpoints
for reviewing persisted PR data, analysis, and experimental risk evaluation.

## Local container setup

The root `docker-compose.yml` starts PostgreSQL and pgAdmin for local
development; it does not build or start the backend. Copy the root
`.env.example` to `.env`, set distinct non-empty random URL-safe values for
`POSTGRES_PASSWORD` and `PGADMIN_DEFAULT_PASSWORD`, then run
`docker compose --env-file .env config --quiet` to validate configuration
without starting containers. Start the local database tools with
`docker compose --env-file .env up -d`. Compose exits with a clear error when
either service password is unset.

PostgreSQL and pgAdmin are published only on `127.0.0.1` by default, on ports
5432 and 8080 respectively; override `POSTGRES_HOST_PORT` or
`PGADMIN_HOST_PORT` in the ignored root `.env` if those local ports are busy.
The pgAdmin service waits for PostgreSQL's `pg_isready` health check. From the
host-run backend, configure `DATABASE_URL` in `backend/.env` to use
`127.0.0.1`, the selected PostgreSQL port, and the same database username and
password. For a client running inside the Compose network, PostgreSQL's
hostname is `postgres` and its port is 5432. pgAdmin can connect to that same
internal hostname.

The backend's local configuration is separate: copy `backend/.env.example` to
`backend/.env` and set `DATABASE_URL`, distinct `API_READ_TOKEN` and
`API_ADMIN_TOKEN` values, and `GITHUB_WEBHOOK_SECRET` when receiving webhooks.
The root and backend `.env` files are ignored by Git. The Compose file is a
local-development convenience, not a production deployment: it provides no
TLS termination, external secret manager, backend service, or production
network policy. `DEBUG` defaults to false, but a process environment or local
`.env` can override it. Set `DEBUG=false` explicitly for a demo so SQL
statements and parameters are not echoed; enable it only for local
troubleshooting when query logging is appropriate.

Compose environment variables initialize PostgreSQL and pgAdmin when their
data volumes are first created; changing passwords in `.env` does not rotate
credentials stored in an existing volume. Preserve existing volumes and use
the already-configured credentials when connecting to existing local data.
Credential rotation for an existing database or pgAdmin volume is a separate,
deliberate operation; do not remove volumes to apply new credentials.

## API authentication

The backend requires two distinct, high-entropy bearer credentials:

- `API_READ_TOKEN` grants read-only access.
- `API_ADMIN_TOKEN` grants read access plus administrative operations.

Set both in the backend process environment or in a local, untracked
`backend/.env` file based on `backend/.env.example`. Replace the placeholders
with different randomly generated secrets (for example, from a password
manager). Never commit, print, or log the configured values. If either value
is missing/empty or the two values are identical, protected API requests fail
closed with a server configuration error.

All business/data routes require bearer authentication:

- **Read token or admin token:** `GET /github/me`, `GET /repositories`,
  `GET /pull-requests/{pull_request_id}`, `GET /analysis/{pull_request_id}`,
  `GET /risk/pull-request/{pull_request_id}` and
  `GET /risk/pull-request/{pull_request_id}/history`,
  `GET /features/pull-request/{pull_request_id}`,
  `GET /dataset/training`,
  `GET /dataset/pr/github/{owner}/{repo}/{pr_number}/status`, and
  `POST /ml/predict/{pull_request_id}`.
- **Admin token only:** `POST /repositories`,
  `POST /github/repositories/import`,
  `POST /pull-requests/import/{repository_id}`,
  `POST /pull-requests/{pull_request_id}/refresh`,
  `POST /commits/import/{pull_request_id}`,
  `POST /changed-files/import/{commit_id}`,
  `POST /reviews/import/{pull_request_id}`,
  `POST /check-runs/import/{pull_request_id}`,
  `POST /risk/pull-request/{pull_request_id}/analyze`,
  `POST /features/pull-request/{pull_request_id}/snapshot`,
  `POST /outcomes/pull-request/{pull_request_id}`, and `POST /ml/train`.

`/`, `/health`, and `/ready` are public status endpoints. API docs are also
public.

`POST /webhooks/github` is not authenticated with either API token. It
continues to require a valid GitHub `X-Hub-Signature-256` HMAC using
`GITHUB_WEBHOOK_SECRET`; an unset secret rejects all deliveries.

This is a minimal, single-operator demo mechanism, not a multi-user identity
system: credentials are shared static secrets, there are no individual users,
sessions, revocation records, or per-repository permissions. Use a proper
identity provider and authorization layer before exposing a production API.

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

API bearer credentials are separate from the webhook secret. Configure
`API_READ_TOKEN` and `API_ADMIN_TOKEN` for the operator and use the appropriate
bearer token when calling protected API routes; do not send either token to
GitHub as the webhook secret.

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
