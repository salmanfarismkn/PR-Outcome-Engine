# PR Analyzer portfolio handoff

## Purpose

PR Analyzer collects evidence about GitHub pull requests and exposes analysis
and risk-oriented API endpoints. It is intended to make PR history, review
activity, changed code, CI results, and later outcomes inspectable without
treating incomplete evidence as a reliable label.

## Architecture and engineering decisions

- The Python backend uses FastAPI, SQLAlchemy, PostgreSQL, and Alembic.
  GitHub REST access is isolated in the GitHub client/service layer;
  application services coordinate pull requests, commits, changed files,
  reviews, checks, snapshots, and outcomes.
- Signed GitHub webhook events enter through `POST /webhooks/github`.
  Events and raw payloads are persisted in `webhook_event` before dispatch so
  processing can be retried using the GitHub delivery ID.
- Feature snapshots are pre-merge observations. Outcome evaluation and
  training-data selection use persisted evidence and conservative time
  cutoffs rather than changing historical snapshots to improve results.
- The local Compose setup provides PostgreSQL and pgAdmin only. It is not a
  production deployment and does not run the API service.

## Authentication and webhook security

Protected business and data API routes use static bearer credentials:

- `API_READ_TOKEN`: read access.
- `API_ADMIN_TOKEN`: read access plus administrative operations, imports,
  mutations, and model training.

Both credentials must be configured, non-empty, and distinct. `/`, `/health`,
and `/ready` are public status endpoints. API docs are also public.
`POST /webhooks/github` does not use API bearer authentication; it validates
the raw request body with GitHub's `X-Hub-Signature-256` HMAC and
`GITHUB_WEBHOOK_SECRET`. An empty webhook secret rejects deliveries.

This is a single-operator demonstration mechanism, not multi-user identity,
session management, credential revocation, or per-repository authorization.
Do not expose it as a public production API.

## Synchronization, idempotency, and recovery

- PR lifecycle processing synchronizes commits and changed files before
  checks, reviews, snapshots, and outcome evaluation.
- Review records are keyed by GitHub review ID and updated on re-delivery;
  attempts to associate an existing review with a different PR are rejected.
  Check runs are protected from cross-PR reassignment and synchronized against
  the PR's current head SHA.
- A duplicate webhook delivery already marked `processed` is acknowledged
  without dispatch. Other stored states can be retried. Pending review
  deliveries are replayed when the matching PR lifecycle event is processed,
  after source and check synchronization.
- A missing dependency may be returned as HTTP 200 with status `pending`.
  GitHub does not automatically retry a 2xx delivery. Operators must monitor
  `webhook_event` and use GitHub **Recent Deliveries > Redeliver** for
  unresolved deliveries. Check-run deliveries do not share the automatic
  pending-review replay path.
- If the final `processed` status commit fails, the endpoint responds HTTP
  500. It rolls back that transaction and attempts to persist `failed`. If
  that second status write also fails, the last durable state can remain
  `processing`; the payload was persisted before dispatch and same-ID
  redelivery retries any event not already marked `processed`. Database
  outages can prevent durable status transitions, so inspect status before
  manual recovery.
- A check-run delivery can be acknowledged without importing evidence when
  the repository is unknown or the check cannot be associated with a PR.
  Verify persisted current-head check rows rather than using HTTP success as
  proof of evidence collection.

## Snapshot and outcome rules

- Snapshots are skipped for closed or merged PRs and unless both commit and
  changed-file evidence are present.
- Training selection requires a complete snapshot created at or before the
  merge timestamp and selects at most one row per PR.
- Unmerged PRs remain `uncertain`. A verified revert or a completed failing
  current-head CI check is `problematic`. A merged PR is `healthy` only with
  current-head check evidence and all such checks completed successfully.
  Missing, pending, cancelled, or otherwise non-qualifying evidence remains
  `uncertain`; uncertain outcomes are excluded from training.
- Do not backdate snapshots, fabricate examples, or modify labels to meet
  evaluation gates.

## Local setup and commands

Use PowerShell from the repository root unless a command says to change
directory. Never commit local environment files or put secret values into
command history.

1. Copy `.env.example` to `.env` with `Copy-Item .env.example .env`. Set
   distinct non-empty random values for `POSTGRES_PASSWORD` and
   `PGADMIN_DEFAULT_PASSWORD`.
2. Validate Compose interpolation without starting services:

   ```powershell
   docker compose --env-file .env config --quiet
   ```

3. When a local database is needed, start only the local data services:

   ```powershell
   docker compose --env-file .env up -d
   ```

   PostgreSQL and pgAdmin publish to loopback by default. Existing volumes
   keep their initialized credentials; changing `.env` does not rotate them.
4. Copy `backend/.env.example` to `backend/.env` with
   `Copy-Item backend/.env.example backend/.env`. Replace the
   `URL_ENCODED_PASSWORD` placeholder in `DATABASE_URL` with the URL-encoded
   password configured for local PostgreSQL. Set `API_READ_TOKEN`,
   `API_ADMIN_TOKEN`, `GITHUB_TOKEN` when GitHub REST access is needed, and
   `GITHUB_WEBHOOK_SECRET` when receiving webhooks. Use distinct API tokens.
   Token and webhook secret values in the example are blank.
5. From `backend/`, install the locked project dependencies and migrate a
   disposable local database:

   ```powershell
   uv sync --locked
   uv run alembic upgrade head
   ```

   `alembic upgrade head` writes schema changes. Do not aim this command at a
   production database as part of a portfolio demonstration.
6. From `backend/`, launch the local API with SQL echo disabled:

   ```powershell
   $env:DEBUG = "false"
   uv run uvicorn app.main:app --reload
   ```

   Visit `http://127.0.0.1:8000/docs` for the API schema. The docs are public;
   business endpoints still require the appropriate bearer credential.
7. Run checks from `backend/`:

   ```powershell
   uv run pytest
   uv run ruff check app scripts tests
   uv run alembic current
   uv run alembic check
   ```

   `pytest` and Ruff do not train a model. Alembic `current` reads the
   configured database revision; `check` compares schema metadata and does
   not apply migrations. Both require an accessible configured database.

For data status, `uv run python scripts/audit_training_readiness.py` reads the
configured database and prints a read-only JSON report. The evaluator command
`uv run python scripts/evaluate_pr_dataset.py` fits an in-memory model only
and does not save an artifact. Do not run `POST /ml/train` for a demo audit:
it writes `artifacts/pr_risk_model.joblib`.

These setup, test, lint, and migration commands are verified against the
repository's current scripts and configuration. Compose configuration was
validated without starting or recreating containers. The local setup and
migration commands above are instructions; they were not run as part of this
handoff.

## Verification and known limitations

The current verified release checks are:

- Backend suite: 75 tests passed.
- `uv run ruff check app scripts tests`: passed.
- Application import and SQLAlchemy mapper configuration: passed.
- `git diff --check`: passed.
- Alembic reported revision `c6e2f841a930 (head)` with no metadata drift.
  Compose configuration validated without service startup.

The suite emits existing Pydantic configuration/deprecation and
Starlette/httpx deprecation warnings. The effective local `DEBUG` setting was
observed enabled during handoff preparation even though the application
default and tracked example are false. The ignored `.env` was not inspected
or changed; explicitly set `DEBUG=false` in the launch environment as shown
above before demonstrating.

The latest readiness audit found 135 eligible examples from one repository:
2 healthy and 133 problematic. Repository-grouped evaluation is
`not_evaluable` because both classes are not represented across enough
repositories. The pipeline is experimental; this dataset does not establish
model accuracy, generalization, or predictive validity.

Other limitations include shared static API secrets, operator-managed webhook
redelivery, database dependence for delivery-state recovery, no production
TLS/secret-management or network policy in Compose, and no demonstrated
production deployment. The project is suitable only for a controlled,
supervised portfolio demonstration after explicitly disabling `DEBUG`.
