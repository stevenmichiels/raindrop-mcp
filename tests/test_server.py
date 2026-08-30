from __future__ import annotations

import sys

import httpx
import pytest
from mcp import Client, StdioServerParameters

from raindrop_mcp.client import RaindropClient
from raindrop_mcp.server import create_server


@pytest.mark.asyncio
async def test_server_exposes_required_tools() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"result": True, "items": []})
    )
    server = create_server(lambda: RaindropClient("test-token", transport=transport))

    async with Client(server) as client:
        tools = await client.list_tools()

    tools_by_name = {tool.name: tool for tool in tools.tools}

    assert set(tools_by_name) == {
        "list_collections",
        "search_bookmarks",
        "get_bookmark",
        "create_bookmark",
        "update_bookmark",
    }
    assert {
        name: tool.annotations.model_dump(by_alias=True, exclude_none=True)
        for name, tool in tools_by_name.items()
    } == {
        "list_collections": {"readOnlyHint": True, "openWorldHint": True},
        "search_bookmarks": {"readOnlyHint": True, "openWorldHint": True},
        "get_bookmark": {"readOnlyHint": True, "openWorldHint": True},
        "create_bookmark": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        "update_bookmark": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    }
    assert set(tools_by_name["search_bookmarks"].output_schema["properties"]) == {
        "items",
        "count",
        "page",
        "per_page",
    }
    assert set(tools_by_name["get_bookmark"].output_schema["properties"]) == {
        "item"
    }


@pytest.mark.asyncio
async def test_server_calls_tool_through_in_process_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/v1/raindrop/42"
        return httpx.Response(
            200,
            json={
                "result": True,
                "item": {
                    "_id": 42,
                    "title": "Example",
                    "link": "https://example.com",
                    "tags": ["reference"],
                    "collection": {"$id": 123},
                    "important": True,
                    "excerpt": "Useful description",
                    "note": "Remember this",
                    "created": "2026-08-30T10:00:00.000Z",
                    "lastUpdate": "2026-08-30T11:00:00.000Z",
                    "cover": "https://example.com/cover.jpg",
                    "domain": "example.com",
                    "type": "article",
                    "media": [{"link": "https://example.com/heavy.jpg"}],
                    "cache": {"status": "ready", "size": 100000},
                    "highlights": [{"text": "Large highlight"}],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    server = create_server(lambda: RaindropClient("test-token", transport=transport))

    async with Client(server) as client:
        result = await client.call_tool("get_bookmark", {"bookmark_id": 42})

    assert result.structured_content == {
        "item": {
            "id": 42,
            "title": "Example",
            "link": "https://example.com",
            "tags": ["reference"],
            "collection_id": 123,
            "important": True,
            "excerpt": "Useful description",
            "note": "Remember this",
            "created": "2026-08-30T10:00:00.000Z",
            "last_update": "2026-08-30T11:00:00.000Z",
            "cover": "https://example.com/cover.jpg",
            "domain": "example.com",
            "type": "article",
        },
    }


@pytest.mark.asyncio
async def test_server_compacts_search_results_and_supports_listing() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(
            200,
            json={
                "result": True,
                "items": [
                    {
                        "_id": 42,
                        "title": "Example",
                        "link": "https://example.com",
                        "tags": ["reference"],
                        "collection": {"$id": 123},
                        "important": True,
                        "excerpt": "Excluded from summaries",
                        "media": [{"link": "https://example.com/heavy.jpg"}],
                        "cache": {"status": "ready"},
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    server = create_server(lambda: RaindropClient("test-token", transport=transport))

    async with Client(server) as client:
        result = await client.call_tool("search_bookmarks", {})

    assert result.structured_content == {
        "items": [
            {
                "id": 42,
                "title": "Example",
                "link": "https://example.com",
                "tags": ["reference"],
                "collection_id": 123,
                "important": True,
            }
        ],
        "count": 1,
        "page": 0,
        "per_page": 20,
    }
    assert seen_request is not None
    assert dict(seen_request.url.params) == {
        "page": "0",
        "perpage": "20",
        "sort": "-created",
        "nested": "true",
    }


@pytest.mark.asyncio
async def test_server_compacts_collections() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        item = (
            {
                "_id": 1,
                "title": "Root",
                "count": 3,
                "cover": ["https://example.com/root.jpg"],
                "user": {"$id": 99},
            }
            if request.url.path.endswith("/collections")
            else {
                "_id": 2,
                "title": "Child",
                "count": 1,
                "parent": {"$id": 1},
                "access": {"level": 4},
            }
        )
        return httpx.Response(200, json={"result": True, "items": [item]})

    transport = httpx.MockTransport(handler)
    server = create_server(lambda: RaindropClient("test-token", transport=transport))

    async with Client(server) as client:
        result = await client.call_tool("list_collections", {})

    assert result.structured_content == {
        "items": [
            {"id": 1, "title": "Root", "count": 3, "parent_id": None},
            {"id": 2, "title": "Child", "count": 1, "parent_id": 1},
        ],
        "count": 2,
    }


@pytest.mark.asyncio
async def test_server_returns_compact_create_and_update_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "result": True,
                    "item": {
                        "_id": 42,
                        "title": "Example",
                        "link": "https://example.com",
                        "tags": [],
                        "collection": {"$id": 123},
                        "important": False,
                        "media": [{"link": "https://example.com/heavy.jpg"}],
                    },
                },
            )
        return httpx.Response(200, json={"result": True})

    transport = httpx.MockTransport(handler)
    server = create_server(lambda: RaindropClient("test-token", transport=transport))

    async with Client(server) as client:
        created = await client.call_tool(
            "create_bookmark",
            {"link": "https://example.com", "collection_id": 123},
        )
        updated = await client.call_tool(
            "update_bookmark",
            {
                "bookmark_id": 42,
                "tags": [],
                "note": "",
                "important": False,
                "reparse_metadata": True,
            },
        )

    assert created.structured_content == {
        "item": {
            "id": 42,
            "title": "Example",
            "link": "https://example.com",
            "tags": [],
            "collection_id": 123,
            "important": False,
        }
    }
    assert updated.structured_content == {
        "id": 42,
        "updated": True,
        "updated_fields": ["tags", "note", "important", "reparse_metadata"],
    }


@pytest.mark.asyncio
async def test_module_entry_point_serves_tools_over_stdio() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "raindrop_mcp"],
        env={"RAINDROP_ACCESS_TOKEN": "fake-test-token"},
    )

    async with Client(parameters) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools.tools} == {
        "list_collections",
        "search_bookmarks",
        "get_bookmark",
        "create_bookmark",
        "update_bookmark",
    }
