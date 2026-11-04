# API reference

The running application publishes the authoritative OpenAPI document at
`/openapi.json`, with interactive documentation at `/docs` and `/redoc`.
Business routes require `Authorization: Bearer <token>` unless noted below.
The read token permits read routes; the admin token is required for mutation,
import, refresh, analysis, and training routes.

## Public routes

| Method | Endpoint | Request | Response |
|---|---|---|---|
| GET | `/` | None | Application name, running status, version |
| GET | `/health` | None | `{"status":"healthy"}` |
| GET | `/ready` | None | `{"status":"ready"}` or HTTP 503 if `SELECT 1` fails |
| POST | `/webhooks/github` | GitHub headers and raw JSON body | Processed, pending, duplicate, or failed status |

`POST /webhooks/github` does not use bearer authentication. It requires
`X-GitHub-Event`, `X-GitHub-Delivery`, and a valid
`X-Hub-Signature-256`. Invalid signatures return HTTP 401. Malformed JSON or
UTF-8 returns HTTP 400 and is persisted as failed. Handler failures return
HTTP 500. Duplicate delivery responses reflect persisted state.

## Read routes

| Method | Endpoint | Parameters |
|---|---|---|
| GET | `/github/me` | None |
| GET | `/repositories` | None |
| GET | `/pull-requests/{pull_request_id}` | Path integer ID |
| GET | `/analysis/{pull_request_id}` | Path integer ID |
| GET | `/risk/pull-request/{pull_request_id}` | Path integer ID |
| GET | `/risk/pull-request/{pull_request_id}/history` | Path integer ID |
| GET | `/features/pull-request/{pull_request_id}` | Path integer ID |
| GET | `/dataset/training` | None |
| GET | `/dataset/pr/github/{owner}/{repo}/{pr_number}/status` | Owner, repo, PR number |
| POST | `/ml/predict/{pull_request_id}` | Path integer ID |

Responses are typed by the corresponding Pydantic schemas where the route
declares a response model. Missing resources generally return HTTP 404;
prediction can return HTTP 422 when no complete pre-merge snapshot exists or
HTTP 503 when the model has not been trained.

## Admin routes

| Method | Endpoint | Request |
|---|---|---|
| POST | `/repositories` | `RepositoryCreate` JSON body |
| POST | `/github/repositories/import` | None |
| POST | `/pull-requests/import/{repository_id}` | Path integer ID |
| POST | `/pull-requests/{pull_request_id}/refresh` | Path integer ID |
| POST | `/commits/import/{pull_request_id}` | Path integer ID |
| POST | `/changed-files/import/{commit_id}` | Query `owner`, `repository`, `pull_number` |
| POST | `/reviews/import/{pull_request_id}` | Path integer ID |
| POST | `/check-runs/import/{pull_request_id}` | Path integer ID |
| POST | `/risk/pull-request/{pull_request_id}/analyze` | Path integer ID |
| POST | `/features/pull-request/{pull_request_id}/snapshot` | Path integer ID |
| POST | `/outcomes/pull-request/{pull_request_id}` | Path integer ID |
| POST | `/ml/train` | None |

`POST /repositories` accepts `github_id`, `owner`, `name`, `is_private`,
optional `description`, and optional `default_branch` (default `main`).
Duplicate repositories return HTTP 409. Import and refresh routes return
HTTP 404 when their referenced record does not exist. Model training returns
HTTP 422 when the dataset is insufficient.

## Authentication errors

Protected routes return HTTP 401 for missing or invalid bearer credentials,
HTTP 403 when a read token attempts an admin operation, and HTTP 503 when the
configured API credentials are absent, empty, or identical. The shared-token
model does not provide named operator identity or per-resource authorization.
