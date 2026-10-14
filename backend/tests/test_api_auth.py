from datetime import UTC, datetime
import hashlib
import hmac
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import app.main  # noqa: F401

from app.api import dependencies as api_dependencies
from app.dataset.service import TrainingDatasetService
from app.db.session import get_db
from app.main import app
from app.repository.router import repository_service
from app.repository.schemas import RepositoryResponse
from app.webhook import router as webhook_router_module


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        api_dependencies,
        "get_settings",
        lambda: SimpleNamespace(
            api_read_token="read-test-secret",
            api_admin_token="admin-test-secret",
        ),
    )

    def override_get_db():
        yield object()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def test_business_read_route_requires_bearer_credentials(client) -> None:
    response = client.get("/repositories")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_bearer_credentials_are_rejected(client) -> None:
    response = client.get(
        "/repositories",
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401
    assert "invalid" not in response.text


@pytest.mark.parametrize(
    ("read_token", "admin_token"),
    [
        ("", "configured-admin-secret"),
        ("configured-read-secret", ""),
        (" ", "configured-admin-secret"),
        ("same-configured-secret", "same-configured-secret"),
    ],
)
def test_missing_or_empty_configured_credentials_fail_closed(
    client,
    monkeypatch,
    read_token: str,
    admin_token: str,
) -> None:
    monkeypatch.setattr(
        api_dependencies,
        "get_settings",
        lambda: SimpleNamespace(
            api_read_token=read_token,
            api_admin_token=admin_token,
        ),
    )

    response = client.get(
        "/repositories",
        headers={"Authorization": "Bearer supplied-secret"},
    )

    assert response.status_code == 503
    assert "supplied-secret" not in response.text


def test_read_token_can_access_read_route(client, monkeypatch) -> None:
    monkeypatch.setattr(TrainingDatasetService, "build_dataset", lambda *_: [])

    response = client.get(
        "/dataset/training",
        headers={"Authorization": "Bearer read-test-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"count": 0, "data": []}


def test_read_token_cannot_create_repository(client) -> None:
    response = client.post(
        "/repositories",
        headers={"Authorization": "Bearer read-test-secret"},
        json={
            "github_id": 500,
            "owner": "owner",
            "name": "repo",
            "is_private": False,
        },
    )

    assert response.status_code == 403


def test_admin_token_can_create_repository(client, monkeypatch) -> None:
    repository = RepositoryResponse(
        id=1,
        github_id=500,
        owner="owner",
        name="repo",
        description=None,
        default_branch="main",
        is_private=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        repository_service,
        "create_repository",
        lambda _db, _payload: repository,
    )

    response = client.post(
        "/repositories",
        headers={"Authorization": "Bearer admin-test-secret"},
        json={
            "github_id": 500,
            "owner": "owner",
            "name": "repo",
            "is_private": False,
        },
    )

    assert response.status_code == 201
    assert response.json()["github_id"] == 500


def test_health_endpoint_remains_public(client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_every_business_route_is_documented_as_bearer_protected() -> None:
    public_paths = {"/", "/health", "/ready"}
    hmac_only_paths = {"/webhooks/github"}

    for path, operations in app.openapi()["paths"].items():
        for operation in operations.values():
            if path in public_paths:
                assert "security" not in operation
            elif path in hmac_only_paths:
                assert "security" not in operation
            else:
                assert operation["security"] == [{"HTTPBearer": []}]


def test_webhook_uses_hmac_without_api_bearer_token(
    client,
    monkeypatch,
) -> None:
    payload = b'{"action":"submitted"}'
    secret = "webhook-test-secret"
    signature = "sha256=" + hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    monkeypatch.setattr(
        webhook_router_module,
        "get_settings",
        lambda: SimpleNamespace(github_webhook_secret=secret),
    )
    monkeypatch.setattr(
        webhook_router_module.webhook_service,
        "get_event",
        lambda **_: SimpleNamespace(status="processed"),
    )

    response = client.post(
        "/webhooks/github",
        content=payload,
        headers={
            "X-GitHub-Event": "pull_request_review",
            "X-GitHub-Delivery": "delivery-1",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "already_processed"}


@pytest.mark.parametrize("secret", ["webhook-test-secret", ""])
def test_webhook_rejects_invalid_signature_or_missing_secret(
    client,
    monkeypatch,
    secret: str,
) -> None:
    monkeypatch.setattr(
        webhook_router_module,
        "get_settings",
        lambda: SimpleNamespace(github_webhook_secret=secret),
    )

    response = client.post(
        "/webhooks/github",
        content=b'{"action":"submitted"}',
        headers={
            "X-GitHub-Event": "pull_request_review",
            "X-GitHub-Delivery": "delivery-invalid",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )

    assert response.status_code == 401
