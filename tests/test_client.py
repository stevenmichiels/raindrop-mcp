from __future__ import annotations

import json

import httpx
import pytest

from raindrop_mcp.client import (
    ACCESS_TOKEN_ENV,
    RaindropAPIError,
    RaindropClient,
)

TEST_TOKEN = "test-token-that-must-stay-private"


def make_client(handler: httpx.MockTransport) -> RaindropClient:
    return RaindropClient(TEST_TOKEN, transport=handler)


def test_from_environment_requires_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ACCESS_TOKEN_ENV, raising=False)

    with pytest.raises(RuntimeError, match=ACCESS_TOKEN_ENV):
        RaindropClient.from_environment()


@pytest.mark.asyncio
async def test_list_collections_combines_root_and_children() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        items = (
            [{"_id": 1, "title": "Root"}]
            if request.url.path.endswith("/collections")
            else [{"_id": 2, "title": "Child", "parent": {"$id": 1}}]
        )
        return httpx.Response(200, json={"result": True, "items": items})

    async with make_client(httpx.MockTransport(handler)) as client:
        result = await client.list_collections()

    assert result["count"] == 2
    assert [item["_id"] for item in result["items"]] == [1, 2]
    assert [request.url.path for request in requests] == [
        "/rest/v1/collections",
        "/rest/v1/collections/childrens",
    ]
    assert all(
        request.headers["Authorization"] == f"Bearer {TEST_TOKEN}"
        for request in requests
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_path"),
    [
        ({}, "/rest/v1/tags"),
        ({"collection_id": 0}, "/rest/v1/tags"),
        ({"collection_id": 123}, "/rest/v1/tags/123"),
        ({"collection_id": -1}, "/rest/v1/tags/-1"),
    ],
)
async def test_list_tags_uses_optional_collection_endpoint(
    kwargs: dict[str, int],
    expected_path: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == expected_path
        assert not request.url.params
        return httpx.Response(
            200, json={"result": True, "items": [{"_id": "api", "count": 100}]}
        )

    async with make_client(httpx.MockTransport(handler)) as client:
        result = await client.list_tags(**kwargs)

    assert result["items"] == [{"_id": "api", "count": 100}]
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_search_bookmarks_sends_supported_query_parameters() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json={"result": True, "items": [{"_id": 42}]})

    async with make_client(httpx.MockTransport(handler)) as client:
        result = await client.search_bookmarks(
            "tag:python",
            collection_id=123,
            page=2,
            per_page=25,
            sort="-created",
            nested=False,
        )

    assert result["items"] == [{"_id": 42}]
    assert seen_request is not None
    assert seen_request.url.path == "/rest/v1/raindrops/123"
    assert dict(seen_request.url.params) == {
        "search": "tag:python",
        "page": "2",
        "perpage": "25",
        "sort": "-created",
        "nested": "false",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [None, "   "])
async def test_search_bookmarks_omits_blank_query_and_defaults_to_twenty(
    query: str | None,
) -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json={"result": True, "items": []})

    async with make_client(httpx.MockTransport(handler)) as client:
        await client.search_bookmarks(query)

    assert seen_request is not None
    assert dict(seen_request.url.params) == {
        "page": "0",
        "perpage": "20",
        "sort": "-created",
        "nested": "true",
    }


@pytest.mark.asyncio
async def test_search_bookmarks_defaults_to_relevance_for_a_query() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json={"result": True, "items": []})

    async with make_client(httpx.MockTransport(handler)) as client:
        await client.search_bookmarks("python")

    assert seen_request is not None
    assert seen_request.url.params["search"] == "python"
    assert seen_request.url.params["sort"] == "score"


@pytest.mark.asyncio
async def test_get_bookmark_uses_single_raindrop_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/rest/v1/raindrop/42"
        return httpx.Response(200, json={"result": True, "item": {"_id": 42}})

    async with make_client(httpx.MockTransport(handler)) as client:
        result = await client.get_bookmark(42)

    assert result["item"]["_id"] == 42


@pytest.mark.asyncio
async def test_create_bookmark_builds_official_payload() -> None:
    seen_payload: dict[str, object] | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_payload
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/raindrop"
        seen_payload = json.loads(request.content)
        return httpx.Response(200, json={"result": True, "item": {"_id": 42}})

    async with make_client(httpx.MockTransport(handler)) as client:
        await client.create_bookmark(
            "https://example.com",
            title="Example",
            collection_id=123,
            tags=["reference"],
            important=False,
        )

    assert seen_payload == {
        "link": "https://example.com",
        "title": "Example",
        "tags": ["reference"],
        "important": False,
        "collection": {"$id": 123},
        "pleaseParse": {},
    }


@pytest.mark.asyncio
async def test_update_bookmark_preserves_empty_and_false_values() -> None:
    seen_payload: dict[str, object] | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_payload
        assert request.method == "PUT"
        assert request.url.path == "/rest/v1/raindrop/42"
        seen_payload = json.loads(request.content)
        return httpx.Response(200, json={"result": True})

    async with make_client(httpx.MockTransport(handler)) as client:
        await client.update_bookmark(
            42,
            tags=[],
            note="",
            important=False,
            reparse_metadata=True,
        )

    assert seen_payload == {
        "tags": [],
        "note": "",
        "important": False,
        "pleaseParse": {},
    }


@pytest.mark.asyncio
async def test_api_errors_do_not_expose_token_or_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": f"Authorization was Bearer {TEST_TOKEN}"},
        )

    async with make_client(httpx.MockTransport(handler)) as client:
        with pytest.raises(RaindropAPIError) as exc_info:
            await client.get_bookmark(42)

    error_text = str(exc_info.value)
    assert TEST_TOKEN not in error_text
    assert "Authorization was" not in error_text
    assert error_text == "Raindrop.io API request failed with status 401."


@pytest.mark.asyncio
async def test_update_requires_at_least_one_field() -> None:
    async with make_client(
        httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        with pytest.raises(ValueError, match="At least one"):
            await client.update_bookmark(42)
