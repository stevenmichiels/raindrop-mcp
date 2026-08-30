"""MCP tool definitions and stdio entry point."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from mcp.server import MCPServer
from mcp_types import ToolAnnotations
from typing_extensions import TypedDict

from raindrop_mcp.client import RaindropAPIError, RaindropClient

ClientFactory = Callable[[], RaindropClient]
BookmarkSort = Literal[
    "-created",
    "created",
    "score",
    "-sort",
    "title",
    "-title",
    "domain",
    "-domain",
]

READ_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=True,
    open_world_hint=True,
)
CREATE_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
UPDATE_TOOL_ANNOTATIONS = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=True,
)


class CollectionSummary(TypedDict):
    """Compact collection data exposed to MCP clients."""

    id: int
    title: str
    count: int
    parent_id: int | None


class CollectionListResult(TypedDict):
    """Collection list returned by the MCP tool."""

    items: list[CollectionSummary]
    count: int


class TagSummary(TypedDict):
    """A tag name and its bookmark count."""

    tag: str
    count: int


class TagListResult(TypedDict):
    """Tag summaries and the number of tags returned."""

    items: list[TagSummary]
    count: int


class BookmarkSummary(TypedDict):
    """Compact bookmark data suitable for search result lists."""

    id: int
    title: str
    link: str
    tags: list[str]
    collection_id: int
    important: bool


class BookmarkDetail(BookmarkSummary, total=False):
    """Useful single-bookmark fields, omitting heavy API metadata."""

    excerpt: str
    note: str
    created: str
    last_update: str
    cover: str
    domain: str
    type: str


class BookmarkItemResult(TypedDict):
    """Single normalized bookmark result."""

    item: BookmarkDetail


class BookmarkSearchResult(TypedDict):
    """Normalized, paginated bookmark summaries."""

    items: list[BookmarkSummary]
    count: int
    page: int
    per_page: int


class BookmarkUpdateResult(TypedDict):
    """Compact confirmation for a successful bookmark update."""

    id: int
    updated: bool
    updated_fields: list[str]


def _response_items(
    payload: dict[str, Any],
    *,
    resource: str,
) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or not all(
        isinstance(item, dict) for item in items
    ):
        raise RaindropAPIError(
            f"Raindrop.io API returned an unexpected {resource} response."
        )
    return items


def _response_item(
    payload: dict[str, Any],
    *,
    resource: str,
) -> dict[str, Any]:
    item = payload.get("item")
    if not isinstance(item, dict):
        raise RaindropAPIError(
            f"Raindrop.io API returned an unexpected {resource} response."
        )
    return item


def _collection_summary(item: dict[str, Any]) -> CollectionSummary:
    collection_id = item.get("_id")
    title = item.get("title")
    count = item.get("count")
    parent = item.get("parent")

    if type(collection_id) is not int or not isinstance(title, str):
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected collections response."
        )
    if type(count) is not int:
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected collections response."
        )
    if parent is None:
        parent_id = None
    elif isinstance(parent, dict) and type(parent.get("$id")) is int:
        parent_id = parent["$id"]
    else:
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected collections response."
        )

    return {
        "id": collection_id,
        "title": title,
        "count": count,
        "parent_id": parent_id,
    }


def _tag_summary(item: dict[str, Any]) -> TagSummary:
    tag = item.get("_id")
    count = item.get("count")

    if not isinstance(tag, str) or type(count) is not int or count < 0:
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected tags response."
        )

    return {"tag": tag, "count": count}


def _bookmark_summary(item: dict[str, Any]) -> BookmarkSummary:
    bookmark_id = item.get("_id")
    title = item.get("title")
    link = item.get("link")
    tags = item.get("tags")
    collection = item.get("collection")
    important = item.get("important", False)

    if type(bookmark_id) is not int or not isinstance(title, str):
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected bookmark response."
        )
    if not isinstance(link, str):
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected bookmark response."
        )
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected bookmark response."
        )
    if not isinstance(collection, dict) or type(collection.get("$id")) is not int:
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected bookmark response."
        )
    if not isinstance(important, bool):
        raise RaindropAPIError(
            "Raindrop.io API returned an unexpected bookmark response."
        )

    return {
        "id": bookmark_id,
        "title": title,
        "link": link,
        "tags": list(tags),
        "collection_id": collection["$id"],
        "important": important,
    }


def _bookmark_detail(item: dict[str, Any]) -> BookmarkDetail:
    detail: BookmarkDetail = {**_bookmark_summary(item)}
    optional_fields = {
        "excerpt": "excerpt",
        "note": "note",
        "created": "created",
        "lastUpdate": "last_update",
        "cover": "cover",
        "domain": "domain",
        "type": "type",
    }
    for api_name, output_name in optional_fields.items():
        value = item.get(api_name)
        if isinstance(value, str) and value:
            detail[output_name] = value
    return detail


def create_server(client_factory: ClientFactory | None = None) -> MCPServer:
    """Build the server, allowing an injected client factory for tests."""
    factory = client_factory or RaindropClient.from_environment
    server = MCPServer(
        "Raindrop.io",
        instructions=(
            "Search and manage Raindrop.io bookmarks through the official REST API."
        ),
    )

    @server.tool(annotations=READ_TOOL_ANNOTATIONS)
    async def list_collections(
        include_children: bool = True,
    ) -> CollectionListResult:
        """List Raindrop.io collections, including nested collections by default."""
        async with factory() as client:
            payload = await client.list_collections(include_children=include_children)
        items = [
            _collection_summary(item)
            for item in _response_items(payload, resource="collections")
        ]
        return {"items": items, "count": len(items)}

    @server.tool(annotations=READ_TOOL_ANNOTATIONS)
    async def list_tags(collection_id: int = 0) -> TagListResult:
        """List tags with bookmark counts; collection_id 0 lists all tags.

        A nonzero ID scopes the request to that collection. No child
        collections are fetched separately. The top-level count is the
        number of tags, not the number of bookmarks.
        """
        async with factory() as client:
            payload = await client.list_tags(collection_id)
        items = [
            _tag_summary(item)
            for item in _response_items(payload, resource="tags")
        ]
        return {"items": items, "count": len(items)}

    @server.tool(annotations=READ_TOOL_ANNOTATIONS)
    async def search_bookmarks(
        query: str | None = None,
        collection_id: int = 0,
        page: int = 0,
        per_page: int = 20,
        sort: BookmarkSort | None = None,
        nested: bool = True,
    ) -> BookmarkSearchResult:
        """List bookmarks or search with native Raindrop.io syntax.

        collection_id 0 searches all bookmarks; page numbering starts at zero.
        Results default to relevance for searches and newest first for listings.
        """
        async with factory() as client:
            payload = await client.search_bookmarks(
                query,
                collection_id=collection_id,
                page=page,
                per_page=per_page,
                sort=sort,
                nested=nested,
            )
        items = [
            _bookmark_summary(item)
            for item in _response_items(payload, resource="bookmarks")
        ]
        return {
            "items": items,
            "count": len(items),
            "page": page,
            "per_page": per_page,
        }

    @server.tool(annotations=READ_TOOL_ANNOTATIONS)
    async def get_bookmark(bookmark_id: int) -> BookmarkItemResult:
        """Get one bookmark by its positive Raindrop.io ID."""
        async with factory() as client:
            payload = await client.get_bookmark(bookmark_id)
        return {
            "item": _bookmark_detail(
                _response_item(payload, resource="bookmark")
            )
        }

    @server.tool(annotations=CREATE_TOOL_ANNOTATIONS)
    async def create_bookmark(
        link: str,
        title: str | None = None,
        collection_id: int | None = None,
        tags: list[str] | None = None,
        excerpt: str | None = None,
        note: str | None = None,
        important: bool | None = None,
        cover: str | None = None,
        parse_metadata: bool = True,
    ) -> BookmarkItemResult:
        """Create a bookmark; link is required and metadata parsing is enabled."""
        async with factory() as client:
            payload = await client.create_bookmark(
                link,
                title=title,
                collection_id=collection_id,
                tags=tags,
                excerpt=excerpt,
                note=note,
                important=important,
                cover=cover,
                parse_metadata=parse_metadata,
            )
        return {
            "item": _bookmark_detail(
                _response_item(payload, resource="bookmark")
            )
        }

    @server.tool(annotations=UPDATE_TOOL_ANNOTATIONS)
    async def update_bookmark(
        bookmark_id: int,
        link: str | None = None,
        title: str | None = None,
        collection_id: int | None = None,
        tags: list[str] | None = None,
        excerpt: str | None = None,
        note: str | None = None,
        important: bool | None = None,
        cover: str | None = None,
        reparse_metadata: bool = False,
    ) -> BookmarkUpdateResult:
        """Update only the supplied fields on one bookmark."""
        async with factory() as client:
            await client.update_bookmark(
                bookmark_id,
                link=link,
                title=title,
                collection_id=collection_id,
                tags=tags,
                excerpt=excerpt,
                note=note,
                important=important,
                cover=cover,
                reparse_metadata=reparse_metadata,
            )
        updated_values = {
            "link": link,
            "title": title,
            "collection_id": collection_id,
            "tags": tags,
            "excerpt": excerpt,
            "note": note,
            "important": important,
            "cover": cover,
        }
        updated_fields = [
            name for name, value in updated_values.items() if value is not None
        ]
        if reparse_metadata:
            updated_fields.append("reparse_metadata")
        return {
            "id": bookmark_id,
            "updated": True,
            "updated_fields": updated_fields,
        }

    return server


mcp = create_server()


def main() -> None:
    """Run the local server over the MCP SDK's default stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
