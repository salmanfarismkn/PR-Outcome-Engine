import httpx
import pytest

import app.main  # noqa: F401
from app.github.client import GitHubClient


def _review(review_id: int) -> dict:
    return {
        "id": review_id,
        "user": {"login": "reviewer"},
        "state": "APPROVED",
        "body": "Approved",
        "submitted_at": "2026-10-12T00:00:00Z",
    }


def _client(handler) -> GitHubClient:
    client = GitHubClient(
        base_url="https://api.github.com",
        token="test-token",
    )
    client._client.close()
    client._client = httpx.Client(
        base_url="https://api.github.com",
        transport=httpx.MockTransport(handler),
    )
    return client


def test_list_reviews_fetches_all_pages() -> None:
    requested_pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested_pages.append(page)
        items = (
            [_review(review_id) for review_id in range(1, 101)]
            if page == 1
            else [_review(101)]
        )
        return httpx.Response(200, json=items, request=request)

    client = _client(handler)
    try:
        reviews = client.list_reviews("owner", "repo", 12)
    finally:
        client.close()

    assert requested_pages == [1, 2]
    assert [review.id for review in reviews] == list(range(1, 102))


def test_list_reviews_handles_empty_response() -> None:
    client = _client(
        lambda request: httpx.Response(200, json=[], request=request)
    )
    try:
        assert client.list_reviews("owner", "repo", 12) == []
    finally:
        client.close()


def test_list_reviews_raises_for_github_api_error() -> None:
    client = _client(
        lambda request: httpx.Response(
            503,
            json={"message": "Service unavailable"},
            request=request,
        )
    )
    try:
        with pytest.raises(httpx.HTTPStatusError):
            client.list_reviews("owner", "repo", 12)
    finally:
        client.close()
