# Engineering decisions

## FastAPI and SQLAlchemy

**Context:** The service needs HTTP routing, dependency injection, typed
request validation, and transactional persistence.

**Decision:** Use FastAPI for HTTP APIs and SQLAlchemy sessions/models for
application persistence.

**Trade-offs:** This keeps the codebase small and conventional, but long
webhook handlers still occupy request workers because processing is
synchronous.

**Current limitations:** No separate worker queue or production process
manager configuration is included.

## PostgreSQL persistence

**Context:** Webhook uniqueness, transactions, and row-locking semantics are
central to reliable delivery handling.

**Decision:** Use PostgreSQL as the application database and Alembic for
migrations.

**Trade-offs:** PostgreSQL provides the required transactional and locking
primitives, but local development and integration testing require a running
database.

**Current limitations:** Live migration and concurrency verification has not
been completed in the current environment.

## Durable webhook event records

**Context:** A request can terminate after receiving a delivery, and operators
need an audit/recovery record.

**Decision:** Persist the raw webhook payload and delivery metadata before
dispatch.

**Trade-offs:** Replay is possible, but payload storage requires retention,
access-control, and database-protection policies.

**Current limitations:** No repository-level payload retention job is
implemented.

## Delivery ID uniqueness and idempotency

**Context:** GitHub can redeliver the same delivery and concurrent requests can
race.

**Decision:** Enforce a unique database constraint on `delivery_id`, roll back
insert conflicts, re-query the winning row, and suppress duplicate dispatch.

**Trade-offs:** This prevents duplicate delivery processing, but event-specific
handlers still need their own domain uniqueness/upsert behavior.

**Current limitations:** The concurrent PostgreSQL behavior is covered by
prepared integration tests but has not run against live PostgreSQL.

## Pending review replay

**Context:** A review can arrive before its pull request is synchronized.

**Decision:** Store the review delivery as `pending` and replay it only through
the existing pull-request lifecycle path when the matching pull request is
available.

**Trade-offs:** This avoids replaying unrelated events, but pending work is
not handled by stale recovery and can require a later PR event or GitHub
redelivery.

**Current limitations:** There is no general pending-event operator requeue
API.

## Bounded retries

**Context:** Replaying handlers indefinitely can repeat external reads or
derived database work.

**Decision:** Track attempts and transition exhausted recovery events to
`failed` after the configured maximum.

**Trade-offs:** Permanent failures remain for manual investigation instead of
being retried automatically.

**Current limitations:** Failed events require operator diagnosis and GitHub
redelivery or another controlled procedure.

## PostgreSQL `SKIP LOCKED` recovery claims

**Context:** Two recovery workers must not claim the same stale event.

**Decision:** Select stale rows with `FOR UPDATE SKIP LOCKED`, commit the claim
before running the handler, and use a separate processing session.

**Trade-offs:** Workers do not wait on one another, and transactions are short,
but correctness depends on PostgreSQL behavior and deployment configuration.

**Current limitations:** No live PostgreSQL claim test has executed here.

## Separate scheduler process

**Context:** An in-process task would start once per API worker or replica
without a distributed ownership mechanism.

**Decision:** Keep FastAPI free of scheduler startup and provide
`run_webhook_recovery.py` as a separately owned process.

**Trade-offs:** Deployment must supervise one scheduler process, while the
existing database claim logic protects individual event claims.

**Current limitations:** The repository does not provide a process-manager
unit or distributed scheduler lease. Exactly-one process ownership is an
operational requirement.

## No message broker

**Context:** The current workload already has a durable PostgreSQL event store
and bounded recovery requirements.

**Decision:** Do not introduce Redis, Celery, RabbitMQ, or another broker.

**Trade-offs:** The system avoids new infrastructure and operational
dependencies, but synchronous webhook handling and database-backed recovery
have lower scalability than a dedicated queue.

**Current limitations:** A broker or worker architecture may be needed if
throughput or handler latency exceeds the current deployment model.

## Operator-controlled recovery

**Context:** Replay can repeat non-trivial handler work and external reads.

**Decision:** Keep manual recovery dry-run by default and require an explicit
execution option. Automatic recovery is a separately enabled process.

**Trade-offs:** Operators retain control over risky replay, but unresolved
events can remain stale until the process or command runs.

**Current limitations:** There is no alerting system or automatic scheduler
lease.

## No individual operator requeue

**Context:** The current API uses shared read/admin bearer tokens rather than
named operator identities.

**Decision:** Do not add a manual requeue endpoint that would claim to audit
individual operators.

**Trade-offs:** Failed/exhausted events require database inspection and
controlled redelivery instead of a convenient API.

**Current limitations:** A future identity and audit model would be required
before implementing secure per-operator requeue.
