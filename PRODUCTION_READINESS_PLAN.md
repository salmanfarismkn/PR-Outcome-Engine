# Production Readiness Plan

## Assessment scope

This is a static assessment of the current worktree, not a deployment
certification. The worktree was clean at inspection. No live GitHub API calls,
database connections or writes, secret values, model training, or artifact
reads were used. The Alembic graph was inspected without connecting to a
database and has one head, `c6e2f841a930`. Consequently, database contents,
production environment configuration, backup coverage, traffic levels, and
actual dataset quality remain unverified.

The target architecture stays with FastAPI, SQLAlchemy, and PostgreSQL. For
background work, first evaluate a PostgreSQL-backed queue using the existing
webhook event store (or a small queue table) and PostgreSQL row locking; do not
add a broker unless measured throughput or availability requirements justify
one.

Severity: **P0 Blocker** means a known failure prevents safe operation;
**P1 High** means production exposure or loss risk needs resolution before
launch; **P2 Moderate** means reliability/quality work with a defined
pre-launch or early-operation gate; **P3 Improvement** means useful hardening
after the launch gates. “Confirmed gap” is directly evidenced by the
implementation; “Unverified risk” means the repository alone cannot establish
whether a real deployment addresses it.

## Findings

### 1. Authentication, authorization, GitHub credentials, secrets, and network exposure

#### SEC-1 — Configured GitHub credential is not sent to GitHub
- **Current behavior / files:** `backend/app/github/service.py` passes
  `settings.github_token` to `GitHubClient`, but
  `backend/app/github/client.py` constructs the `Authorization` header with
  the literal value `"******"` instead of the supplied token.
  `backend/tests/test_github_review_pagination.py` currently asserts that
  literal header.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P0 Blocker.** Authenticated GitHub REST calls
  cannot use the configured credential; repository import and webhook
  synchronization that depends on GitHub will fail or be unauthorized.
- **Smallest justified change:** Build the bearer header from the constructor's
  token, reject missing credentials for operations that require them, and
  replace the masking-string test with an assertion against a test-only token.
- **Acceptance:** An `httpx.MockTransport` test verifies the configured
  test-only credential is sent as the bearer value; empty-token behavior is
  explicit; no test or log prints a real token. Exercise repository,
  PR, review, check, and changed-file API calls through mocked responses.
- **Dependencies:** None; complete before any GitHub-backed staging test.

#### SEC-2 — Static shared bearer credentials are not an operator identity system
- **Current behavior / files:** `backend/app/api/dependencies.py` compares
  shared read/admin bearer tokens and fails closed if either is unset or both
  are equal. `backend/app/api/router.py` applies read authentication to the
  business API; individual mutation routes use admin access. The standalone
  ML router also applies read/admin dependencies.
  `backend/app/main.py` publishes `/docs` and `/redoc`; `/`, `/health`,
  `/ready`, and the webhook endpoint are public by design. Existing
  `backend/tests/test_api_auth.py` covers basic read/admin distinctions.
- **Status:** Confirmed limitation; whether it is acceptable depends on the
  intended operator model and external access controls.
- **Severity / consequence:** **P1 High** if the API is reachable by more than
  a tightly controlled operator boundary. Shared static tokens lack named
  identities, per-repository authorization, expiry, revocation/audit history,
  and safe rotation; public API documentation reveals the route surface.
- **Smallest justified change:** Decide and document the supported trust
  boundary. For a single-operator private service, keep the simple roles, put
  credentials in the deployment secret manager, define rotation, and restrict
  ingress/docs. If multiple users or tenants will access it, add an identity
  provider and resource-level authorization rather than extending shared-token
  logic.
- **Acceptance:** Automated route tests cover every business and admin route;
  an operational test proves tokens can rotate without committing values;
  externally reachable routes and docs match an approved exposure list.
- **Dependencies:** SEC-3 and the chosen deployment boundary.

#### SEC-3 — No production network/TLS boundary is implemented in this repo
- **Current behavior / files:** Root `docker-compose.yml` runs only PostgreSQL
  and pgAdmin, bound to loopback. `backend/Dockerfile` starts Uvicorn on
  `0.0.0.0:8000`, but Compose does not build or run the API.
  `infrastructure/README.md` is only a placeholder; no tracked reverse-proxy,
  TLS, or deployment configuration is present.
- **Status:** Confirmed gap in the repository; actual external network
  controls are unverified.
- **Severity / consequence:** **P1 High.** A production operator has no
  repository-defined TLS termination, ingress allowlist, or backend exposure
  policy. Exposing the container port directly could expose credentials and
  webhook/API traffic without a managed TLS boundary.
- **Smallest justified change:** Define one production hosting target and a
  minimal deployment contract for TLS, ingress, egress, and database access.
  Keep the local Compose setup separate; do not add Kubernetes or a new proxy
  stack without a hosting requirement.
- **Acceptance:** A deployment smoke test confirms HTTPS, intended public
  routes only, private database connectivity, and no direct public database
  port; webhook SSL verification remains enabled.
- **Dependencies:** SEC-2 and the selected hosting environment.

#### SEC-4 — Secret validation, payload privacy, and request-size limits need an operational policy
- **Current behavior / files:** `backend/app/core/config.py` defaults the
  GitHub token, webhook secret, and API tokens to empty strings; only API-token
  validation is fail-closed in `backend/app/api/dependencies.py`.
  `backend/app/webhook/router.py` reads the whole request body and
  `backend/app/webhook/service.py` stores the raw decoded payload in
  `backend/app/webhook/models.py`. No application-level body-size limit or
  payload-retention policy is visible.
- **Status:** Confirmed gaps for configuration validation, request-size
  handling, and repository-level retention policy; encryption/retention at a
  managed database or proxy is unverified.
- **Severity / consequence:** **P1 High.** An oversized request can consume
  memory/storage; webhook payloads can contain contributor identity and PR
  content and are retained for replay without a documented expiry.
- **Smallest justified change:** Validate required production settings at
  startup (while allowing local/test configuration deliberately), cap webhook
  bytes at the ingress and application boundaries, and set a documented
  retention/delete policy that preserves required replay/audit windows.
  Require encrypted transport and encrypted database storage in the chosen
  environment.
- **Acceptance:** Startup fails clearly for invalid production configuration;
  oversized body returns a bounded 4xx without persistence; retention tests
  verify the defined cutoff and preserve a delivery within the recovery window.
- **Dependencies:** SEC-3 and WEB-1's recovery/retention requirements.

### 2. Webhook durability, duplicate delivery, retries, dead letters, and recovery

#### WEB-1 — Processing is synchronous and `processing` has no lease/reaper
- **Current behavior / files:** `backend/app/webhook/router.py` persists the
  delivery and then dispatches it in the request, including GitHub REST calls,
  synchronization, snapshots, and evaluation. Statuses in
  `backend/app/webhook/models.py` include `received`, `processing`, `pending`,
  `processed`, and `failed`; there is no attempt count, lease expiry,
  `not_before`, or worker claim. `backend/app/application/webhook_retry.py`
  only replays pending review deliveries from a later PR lifecycle event.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P0 Blocker.** Slow GitHub calls tie up request
  workers and can exceed webhook response timeouts. A process crash can leave
  an event permanently `processing`; non-review pending events have no
  scheduled retry. HTTP 200 for a pending event also prevents GitHub's normal
  non-2xx retry.
- **Smallest justified change:** Convert the durable delivery row into a
  PostgreSQL-backed work item: acknowledge only after a committed enqueue,
  claim bounded batches atomically (for example with `FOR UPDATE SKIP LOCKED`),
  record attempt count/lease expiry/next attempt, recover expired claims, and
  route exhausted or permanent failures to a queryable dead-letter state.
  Keep the dispatcher and domain services; do not add Redis or another broker
  before measuring PostgreSQL queue limits.
- **Acceptance:** A worker crash after claim is recovered after lease expiry;
  transient failures retry at a bounded backoff; permanent/exhausted events
  remain inspectable; acknowledgement is sent only after durable enqueue; an
  event can be manually replayed by an authorized operator.
- **Dependencies:** DB-1 transaction/idempotency boundaries; WEB-2 duplicate
  claim semantics.

#### WEB-2 — Duplicate delivery lookup and status transitions are not atomic
- **Current behavior / files:** `backend/app/webhook/router.py` checks the
  delivery ID, then creates or updates the row in separate operations.
  `backend/app/webhook/models.py` has a unique `delivery_id`, but
  `backend/app/webhook/service.py` does not atomically claim a row or use a
  status-qualified transition. A duplicate in any state except `processed`
  may be dispatched concurrently. The insert `IntegrityError` path in
  `create_event` attempts to refresh the just-created event object after
  rollback rather than re-querying the winning row.
- **Status:** Confirmed gap; concurrent impact has not been measured.
- **Severity / consequence:** **P1 High.** Redelivery races can repeat side
  effects, collide on unique rows, or fail to recover the already-created
  event reliably.
- **Smallest justified change:** Use an atomic insert/upsert or conflict
  handling that re-reads the existing row, and claim work with a guarded
  status/lease update in the same transaction. Keep handlers idempotent as a
  second line of defense.
- **Acceptance:** A PostgreSQL concurrency test submits the same delivery
  concurrently from multiple clients and proves one active claim, one durable
  event row, no uncaught integrity error, and convergent domain state.
- **Dependencies:** WEB-1 and DB-1.

#### WEB-3 — Recovery exists as operator redelivery, not a complete recovery workflow
- **Current behavior / files:** `DATA_COLLECTION_RUNBOOK.md` documents status
  inspection and GitHub Recent Deliveries redelivery; review events can be
  replayed on a PR lifecycle event. There is no authenticated admin replay or
  dead-letter/reprocess interface. `backend/app/application/webhook_retry.py`
  loads all pending review rows for a type and filters them in Python.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P1 High.** Operators have no consistent,
  auditable way to retry failed, stale-processing, or non-review pending
  events, and a large pending set can make PR handling inefficient.
- **Smallest justified change:** Add an admin-only bounded requeue/replay
  operation after WEB-1, with delivery ID, reason, actor, attempt history, and
  safeguards against an active lease. Index/filter by repository/PR where
  known.
- **Acceptance:** Runbook recovery of one failed, one dependency-pending, and
  one stale-processing delivery is repeatable and records each attempt without
  exposing raw payloads.
- **Dependencies:** WEB-1, WEB-2, SEC-2.

### 3. Database transactions, constraints, concurrency, migrations, backup, and restore

#### DB-1 — Event processing commits partial domain work across multiple transactions
- **Current behavior / files:** The webhook event's state changes are committed
  separately in `backend/app/webhook/service.py`. Domain services also commit
  independently, including `backend/app/application/pull_request_webhook.py`,
  `backend/app/application/check_webhook.py`,
  `backend/app/application/review_webhook.py`,
  `backend/app/application/push_webhook.py`,
  `backend/app/application/check_sync.py`, and
  `backend/app/feature/service.py`.
- **Status:** Confirmed gap; exact partial states depend on the failure point.
- **Severity / consequence:** **P1 High.** A crash or database error can leave
  a PR partially synchronized while the delivery is retried. The event status
  and related rows cannot be treated as one atomic unit; duplicate side effects
  become more likely.
- **Smallest justified change:** Define transaction ownership at the worker
  boundary. Keep external GitHub calls outside long DB transactions, then
  persist each fetched batch through a short explicit unit of work with
  idempotent upserts and a clear commit boundary. Do not promise whole-event
  atomicity across external network calls.
- **Acceptance:** Failure injection before and after each persistence boundary
  followed by retry produces consistent rows, no duplicates, and a truthful
  event state.
- **Dependencies:** WEB-1 and WEB-2.

#### DB-2 — Core uniqueness exists, but snapshot writes and high-contention paths need database-backed validation
- **Current behavior / files:** Unique constraints are present for repository
  GitHub ID and owner/name, PR repository/GitHub ID, commit SHA, review
  GitHub ID, check-run GitHub ID, webhook delivery ID, push delivery ID, and
  one outcome per PR (see the corresponding `backend/app/*/models.py` files
  and `backend/migrations/versions/`). Snapshot records intentionally permit
  history, but `backend/app/feature/service.py` performs
  read-then-insert/reuse with no unique state key or concurrent-write guard.
- **Status:** Confirmed core uniqueness; unverified concurrent behavior.
- **Severity / consequence:** **P1 High.** Simultaneous events or manual
  refreshes can create duplicate equivalent snapshots or hit integrity errors
  despite service-level checks.
- **Smallest justified change:** Preserve existing natural-key constraints;
  add only database constraints or conflict-safe persistence justified by
  observed duplicate state. Define a snapshot identity/version policy rather
  than incorrectly making all snapshots unique per PR.
- **Acceptance:** Run concurrent refresh/webhook tests against PostgreSQL;
  uniqueness and idempotency hold across repeated and parallel event delivery.
- **Dependencies:** WEB-2 and DB-1.

#### DB-3 — Migration history is linear, but production migration safety is unproven
- **Current behavior / files:** `backend/migrations/versions/` contains the
  history; inspection with Alembic showed one head,
  `c6e2f841a930`. `backend/migrations/env.py` reads the configured database
  URL. `PORTFOLIO_HANDOFF.md` documents local `alembic upgrade head`,
  `current`, and `check`, but no production expand/contract, lock-time, or
  rollback process is defined. No database was connected during this review.
- **Status:** Confirmed one migration head; production upgrade behavior and
  deployed schema revision are unverified.
- **Severity / consequence:** **P1 High.** A valid local graph does not prove
  migrations are safe against production-sized tables, deployed schema drift,
  or a failed release.
- **Smallest justified change:** Establish a release migration procedure:
  preflight current revision and drift, review generated SQL, use
  backward-compatible expand/contract migrations for changes spanning app
  versions, and define forward-fix versus rollback policy.
- **Acceptance:** Apply every migration from the supported previous release
  to a production-like PostgreSQL copy; measure lock duration; verify app
  compatibility before and after; test a failed migration recovery.
- **Dependencies:** DB-4; run before first production data migration.

#### DB-4 — No backup/restore procedure or recovery objective is present
- **Current behavior / files:** `docker-compose.yml` defines a local
  PostgreSQL volume only. `DATA_COLLECTION_RUNBOOK.md`,
  `PORTFOLIO_HANDOFF.md`, and `infrastructure/README.md` do not define
  production backups, point-in-time recovery, restore validation, or RPO/RTO.
  No production database provider or existing backup system was inspected.
- **Status:** Confirmed repository documentation/config gap; actual provider
  backups are unverified.
- **Severity / consequence:** **P1 High.** Database loss or corruption could
  irreversibly lose webhook history, PR evidence, and trained-data provenance.
- **Smallest justified change:** Select managed PostgreSQL with automated
  encrypted backups/PITR, retention and access controls; document measured
  RPO/RTO and a restore runbook. Do not treat a persistent Docker volume as a
  backup.
- **Acceptance:** Restore a recent backup into an isolated PostgreSQL instance,
  verify schema/data consistency and application readiness, record elapsed
  restore time against approved RPO/RTO, and schedule periodic restore drills.
- **Dependencies:** Hosting choice and DB-3.

### 4. Current-head checks, review sync, snapshot completeness, and temporal eligibility

#### DATA-1 — Current-head association and pre-merge cutoff are present, but not end-to-end certified
- **Current behavior / files:** `backend/app/application/check_sync.py` fetches
  the PR from GitHub, stores its current head SHA, imports checks for that SHA,
  and filters check associations. `backend/app/feature/service.py` includes
  only checks matching `pull_request.head_sha`; checks are empty if the head is
  unknown. `backend/app/outcome/service.py` bases CI labels on current-head
  checks. `backend/app/dataset/service.py` selects the latest complete
  snapshot at or before `merged_at`; `backend/app/ml/router.py` applies the
  same pre-merge timestamp cutoff for prediction.
- **Status:** Correct behavior is visible and covered by focused unit tests,
  but database-backed ordering, webhook retries, and real GitHub behavior are
  unverified.
- **Severity / consequence:** **P1 High** as a release data-validity gate.
  Incorrect ordering or missing synchronization could associate stale checks
  or post-merge features with a pre-merge prediction.
- **Smallest justified change:** Preserve these policies; add explicit
  integration assertions that the fetched head SHA, associated check SHA,
  snapshot timestamp, and merge timestamp agree. Make missing/stale evidence
  visible as incomplete rather than silently treating it as complete.
- **Acceptance:** For a PR with two head revisions, a real or replayed fixture
  proves old-head failures do not label the current head; snapshots after
  merge are excluded; no complete snapshot yields an explicit not-evaluable
  result.
- **Dependencies:** SEC-1, WEB-1, TEST-1.

#### DATA-2 — Commit and changed-file imports fetch a single page
- **Current behavior / files:** `backend/app/github/client.py` requests PR
  commits and changed files without `per_page`/`page` loops. The review-list
  and check-run methods do paginate. `backend/app/application/pull_request_sync.py`
  replaces the PR-level changed-file set with the returned files, and
  `backend/app/application/commit_sync.py` imports the returned commit list.
  `backend/app/feature/service.py` calls a snapshot “complete” when it has
  more than zero commits and changed files.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P1 High.** PRs exceeding the API default page
  size can have truncated commit/file counts and additions/deletions while
  still passing the current nonzero completeness check. This biases features
  and makes “complete” misleading.
- **Smallest justified change:** Paginate commits and changed files using
  GitHub's response pagination/limits, and define what “complete” means when
  GitHub's endpoint maximum is reached. Persist enough sync/completeness
  metadata to distinguish full from truncated results.
- **Acceptance:** Mock more than one page for each endpoint and assert every
  row/count is imported; test the endpoint limit and ensure an incomplete
  result cannot qualify as a complete training snapshot.
- **Dependencies:** DATA-1 and TEST-1.

#### DATA-3 — Review synchronization is idempotent at review ID, but snapshot evidence has limited freshness metadata
- **Current behavior / files:** `backend/app/github/client.py` paginates review
  pages. `backend/app/application/review_webhook.py` and
  `backend/app/review/service.py` upsert by GitHub review ID; review data is
  refreshed on webhook and PR synchronization. `backend/app/feature/service.py`
  snapshots counts and review states but records no per-source sync watermark
  or evidence provenance.
- **Status:** Review pagination/upsert is confirmed; freshness/consistency
  during concurrent events is unverified.
- **Severity / consequence:** **P2 Moderate.** A snapshot can combine data
  collected at different times, and operators/model audits cannot tell whether
  review/check/file inputs were fully synchronized at snapshot time.
- **Smallest justified change:** Add source sync timestamps/completeness
  indicators only where they are needed to gate snapshots and diagnose stale
  data; preserve review-ID idempotency. Avoid a larger event-sourcing rewrite.
- **Acceptance:** Delayed/out-of-order review delivery tests converge to the
  latest review; snapshots report freshness and exclude evidence older than
  the defined collection threshold.
- **Dependencies:** WEB-1, DATA-2.

### 5. Logs, metrics, tracing, health, alerts, and runbooks

#### OPS-1 — Logs are not production-observable and contain ad hoc debug output
- **Current behavior / files:** `backend/app/core/logging.py` configures basic
  text logging. Numerous webhook, sync, feature, and outcome modules use
  `print`; `backend/app/github/client.py` logs review request URLs and debug
  counts. There is no request/delivery correlation context, metrics, tracing,
  or alert configuration in tracked infrastructure.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P1 High.** An operator cannot reliably measure
  queue age, failure/retry rates, GitHub latency/rate limits, database errors,
  or end-to-end event delay, and ad hoc logs are difficult to correlate.
- **Smallest justified change:** Replace prints with structured standard
  logging, add request/delivery IDs and outcome fields, redact payloads and
  secrets, and expose a small set of service/queue/database metrics. Add
  tracing only if the selected hosting stack can collect it.
- **Acceptance:** Logs correlate one delivery across enqueue/claim/dispatch
  without raw payload/token values; metrics expose queue depth, oldest age,
  attempts, processing latency, failures, and DB pool health; a test verifies
  redaction.
- **Dependencies:** WEB-1; hosting/monitoring selection.

#### OPS-2 — Health and readiness checks are too shallow for production
- **Current behavior / files:** `backend/app/health/router.py` returns a
  constant `/health` response and `/ready` checks only `SELECT 1`. There is
  no worker heartbeat/queue readiness, GitHub dependency metric, or alerting
  policy.
- **Status:** Confirmed gap; external monitor availability is unverified.
- **Severity / consequence:** **P1 High.** The API can report ready while
  webhook work is stuck or a required worker is down; no alert catches
  growing backlog or repeated delivery failures.
- **Smallest justified change:** Keep liveness cheap; make readiness represent
  required local dependencies and worker health, not an external GitHub
  availability probe. Alert on queue-age SLO breach, persistent failures,
  database unavailability, and backup/restore failures.
- **Acceptance:** Tests distinguish liveness from DB/worker readiness; an
  injected unavailable DB/worker changes readiness; alert rules are exercised
  with a synthetic backlog/failure signal.
- **Dependencies:** WEB-1 and OPS-1.

#### OPS-3 — Existing collection guidance is not an on-call runbook
- **Current behavior / files:** `DATA_COLLECTION_RUNBOOK.md` explains
  registration, webhook delivery inspection, GitHub redelivery, and local
  collection. `PORTFOLIO_HANDOFF.md` documents local commands. Neither defines
  production on-call ownership, SLOs, escalation, incident communications,
  credential rotation, backup restoration, or a full dead-letter workflow.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P2 Moderate**, but a production launch gate
  because recovery responsibilities are unclear.
- **Smallest justified change:** Extend the operational runbook with service
  owner/contact, dashboards/alerts, safe replay, outage recovery, secret
  rotation, backup restore, migration, and rollback procedures.
- **Acceptance:** A person other than the implementer completes a tabletop
  exercise for GitHub outage, database outage, backlog recovery, and restore
  using only the runbook.
- **Dependencies:** WEB-3, DB-3, DB-4, OPS-1.

### 6. Images, configuration, CI/CD, scanning, deployment, rollback, and environment separation

#### REL-1 — Container build is not reproducible or hardened for production
- **Current behavior / files:** `backend/Dockerfile` uses mutable
  `python:3.11-slim`, copies `pyproject.toml` and `app`, installs via
  `pip install .` without `uv.lock`, runs as the default root user, and has no
  health check. It does not copy `backend/artifacts/`; the model path in
  `backend/app/ml/service.py` is relative to the process working directory.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P1 High.** The image may resolve different
  dependency versions than the lockfile, includes a root runtime, and model
  predictions in a container cannot rely on the repository artifact being
  present. Container restarts/replicas may not share a model artifact.
- **Smallest justified change:** Build from the lockfile using the existing
  package manager, pin the base image by supported tag/digest policy, run
  non-root, add an appropriate health check, and make model artifacts an
  explicit versioned deployment input (or disable ML serving until then).
- **Acceptance:** Repeated clean builds resolve the same dependency set; image
  scans pass policy; runtime is non-root; container starts/readiness works;
  prediction behavior is deterministic across restart/replica using the
  declared model version.
- **Dependencies:** ML-2 and the hosting decision.

#### REL-2 — No CI/CD or supply-chain gates are configured
- **Current behavior / files:** No tracked files exist under `.github/`;
  `backend/pyproject.toml` declares pytest and Ruff but no automated workflow.
  No dependency, image, secret, or source scanning policy is tracked.
- **Status:** Confirmed gap.
- **Severity / consequence:** **P1 High.** There is no enforced test/lint,
  migration, artifact, or vulnerability gate before a production image is
  released.
- **Smallest justified change:** Add a minimal CI pipeline for locked install,
  Ruff, targeted/full tests, migration-graph/metadata checks using disposable
  PostgreSQL where needed, and build. Add dependency/image and secret scanning
  with documented exception ownership.
- **Acceptance:** Pull requests fail on test/lint/migration checks; release
  images are traceable to commit and dependency lock; scanner findings have
  severity-based blocking thresholds and an exception process.
- **Dependencies:** TEST-1, DB-3, REL-1.

#### REL-3 — Runtime configuration and environment promotion are not defined
- **Current behavior / files:** `backend/app/core/config.py` loads `.env` and
  ignores extra fields; `docker-compose.yml` is only a local DB/pgAdmin setup.
  The Docker image has no production deployment definition, secret injection,
  staging environment, or rollback process in tracked infrastructure.
- **Status:** Confirmed repository gap; hosting provider controls unverified.
- **Severity / consequence:** **P1 High.** Local defaults and production
  settings can drift; releases cannot be promoted or rolled back predictably.
- **Smallest justified change:** Define staging and production configuration
  contracts, required/optional settings, secret-manager injection, migration
  execution ownership, immutable image promotion, and a tested previous-image
  rollback procedure. Keep database schema rollback policy explicit.
- **Acceptance:** Staging uses the same immutable image as production; config
  validation rejects missing required values; a release rollback restores
  service with a backward-compatible schema.
- **Dependencies:** SEC-3, DB-3, REL-1, REL-2.

### 7. Integration, failure-injection, load, and recovery testing

#### TEST-1 — Existing coverage is useful but does not demonstrate production behavior
- **Current behavior / files:** `backend/tests/` includes tests for API auth,
  webhook lifecycle, check/review synchronization, snapshots, outcome policy,
  dataset selection, and repository-grouped ML evaluation. Several tests use
  mocks/TestClient; `backend/tests/test_github_review_pagination.py` uses
  `httpx.MockTransport`. No production-like PostgreSQL, full webhook-to-worker
  integration, failure-injection, load, or restore test setup is tracked.
- **Status:** Confirmed test coverage gap. No test suite was run for this
  documentation-only task.
- **Severity / consequence:** **P1 High.** The most consequential assumptions
  (transactions, duplicate claims, migrations, queue recovery, and throughput)
  are not exercised at their actual persistence/concurrency boundary.
- **Smallest justified change:** Add a small PostgreSQL integration profile and
  deterministic GitHub HTTP fixtures, then targeted failure-injection and
  bounded load/recovery tests. Keep normal unit tests fast.
- **Acceptance:** CI proves duplicate concurrent delivery is idempotent;
  process death during a lease recovers; GitHub timeout/rate limit and DB
  rollback are retryable; migration upgrade works from prior release; a
  declared expected event rate and backlog recovery time are met under load.
- **Dependencies:** WEB-1/2, DB-1/3, REL-2.

### 8. ML data quality, repository-grouped evaluation, baselines, and serving

#### ML-1 — Evaluation design has sound safeguards, but model quality and data quality are not certified
- **Current behavior / files:** `backend/app/dataset/service.py` excludes
  uncertain outcomes, selects at most one qualifying snapshot per PR, and
  enforces the merge-time cutoff. `backend/app/ml/service.py` validates
  required features/classes, uses a repository-grouped stratified split, and
  reports a most-frequent dummy baseline plus classifier metrics.
  `backend/scripts/audit_training_readiness.py` and
  `backend/scripts/evaluate_pr_dataset.py` report class/repository and
  snapshot readiness. `backend/tests/test_ml_repository_grouping.py` checks
  repository separation. The dataset/artifact contents and actual metrics
  were not inspected or trained in this review.
- **Status:** Safeguards are confirmed in code; actual labels, coverage,
  representativeness, leakage, class balance, and baseline performance are
  unverified.
- **Severity / consequence:** **P1 High** if predictions will influence
  production decisions; otherwise **P2 Moderate** while ML remains explicitly
  experimental. A grouped split and baseline do not establish sufficient
  sample size, stable performance, calibration, or generalization to new
  repositories/time periods.
- **Smallest justified change:** Define minimum prospective, human-audited
  data gates by outcome and repository; preserve repository holdout; add a
  time-based holdout and label/source audit, report baseline comparison and
  confidence intervals, and require a documented go/no-go threshold before
  any operational use. Keep the model advisory until these pass.
- **Acceptance:** A privacy-reviewed dataset audit verifies labels against
  source evidence, no PR/repository leakage, pre-merge feature cutoffs,
  minimum per-class/per-repository counts, and superiority to a declared
  baseline on an untouched temporal/repository holdout. Report uncertainty
  intervals and calibration before enabling decisions.
- **Dependencies:** DATA-1/2/3 and TEST-1.

#### ML-2 — Model serving is local-file and in-process, with no production lifecycle
- **Current behavior / files:** `backend/app/ml/router.py` exposes an admin
  training endpoint that trains in the API process and a prediction endpoint.
  `backend/app/ml/service.py` writes/loads `artifacts/pr_risk_model.joblib`
  relative to the current working directory, loads it per prediction, and
  returns a hard-coded model version with experimental status. The Dockerfile
  does not copy the existing artifact directory; replicas have no shared,
  versioned model store or atomic promotion mechanism.
- **Status:** Confirmed serving limitation; no production model host was
  inspected.
- **Severity / consequence:** **P1 High** before production ML use, not a
  blocker for a non-ML service. Training can consume API capacity, artifact
  persistence is deployment-dependent, and different replicas may serve
  missing/different models.
- **Smallest justified change:** Keep model training offline/out of request
  handling; publish a validated, versioned artifact as part of release
  promotion, load it at startup or through a controlled local artifact mount,
  and expose the loaded version/readiness. Do not add a separate model service
  absent measured need.
- **Acceptance:** Staging rollout canary serves one immutable model hash on
  every instance; restart/rollback preserves the selected version; missing or
  incompatible artifacts fail readiness; inference latency/resource use is
  measured under expected API load.
- **Dependencies:** ML-1, REL-1, REL-3.

## Ordered implementation plan

1. **Unblock GitHub integration:** Fix SEC-1 and its currently misleading
   authorization test. Add mock-only tests for required GitHub endpoint
   behavior. Do not run live GitHub calls in CI.
2. **Make webhook intake durable and repeat-safe:** Implement WEB-1/2 on
   PostgreSQL, with atomic idempotent claims, leases, bounded retry/backoff,
   terminal/dead-letter states, and a bounded authorized recovery operation
   (WEB-3). Decide payload retention and size limits (SEC-4).
3. **Stabilize persistence and schema operations:** Define event persistence
   transaction boundaries and failure convergence (DB-1/2); document and
   test the one-head migration process (DB-3); select backup/PITR and complete
   a restore drill (DB-4).
4. **Protect evidence quality:** Paginate commits and changed files (DATA-2);
   retain current-head and pre-merge rules while testing them end-to-end
   (DATA-1); add only the freshness/completeness metadata needed for reliable
   snapshots (DATA-3).
5. **Establish minimum operations:** Standardize redacted structured logs,
   correlation, queue/database metrics, liveness/readiness, and actionable
   alerts (OPS-1/2); complete and exercise the on-call runbook (OPS-3).
6. **Create a reproducible release path:** Select hosting and ingress
   boundaries; harden and lock the image (REL-1); add CI, source/dependency/
   image/secret scanning (REL-2); define staging, secret injection, promotion,
   migration ownership, and rollback (SEC-2/3, REL-3).
7. **Prove operational behavior:** Add PostgreSQL integration, concurrency,
   failure-injection, recovery, migration, and bounded load tests (TEST-1) and
   require these in CI.
8. **Keep ML gated:** Audit real prospective evidence and evaluate against
   repository/time holdouts and baselines before making claims (ML-1). Until
   quality gates pass, retain experimental/advisory status; then package and
   promote model artifacts explicitly (ML-2).

## Production deployment gate

On the inspected repository evidence alone, **this service is not ready for a
production deployment**. At minimum, the GitHub credential defect must be
fixed; webhook intake needs durable asynchronous processing, atomic duplicate
claims, lease recovery, retry/dead-letter handling, and repeatable recovery;
data imports must be complete; database transaction/migration and tested
backup/restore procedures must exist; and the chosen deployment must provide
TLS/network controls, managed secrets, health/metrics/alerts, CI/security
gates, and a tested rollback path.

The repository does not establish whether an external team already provides
managed PostgreSQL backups, TLS/ingress, secret management, monitoring, or
deployment controls. Those are verification items, not assumed capabilities.
Production use of ML would additionally remain blocked until real dataset
quality, prospective label validity, repository/time generalization, baseline
performance, calibration, and artifact promotion are demonstrated. This plan
does not certify those properties or make a claim about actual stored data.
