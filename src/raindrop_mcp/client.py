"""Async client for the official Raindrop.io REST API."""

from __future__ import annotations

import os
from types import TracebackType
from typing import Any

import httpx

API_BASE_URL = "https://api.raindrop.io/rest/v1/"
ACCESS_TOKEN_ENV = "RAINDROP_ACCESS_TOKEN"


class RaindropAPIError(RuntimeError):
    """An error safe to return without leaking credentials or response data."""


class RaindropClient:
    """Small, credential-safe wrapper around the Raindrop.io REST API."""

    def __init__(
        self,
        access_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        token = access_token.strip()
        if not token:
            raise ValueError("Raindrop access token must not be empty.")

        self._client = httpx.AsyncClient(
            base_url=API_BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_environment(cls) -> RaindropClient:
        """Create a client from the required process environment variable."""
        token = os.environ.get(ACCESS_TOKEN_ENV)
        if not token or not token.strip():
            raise RuntimeError(
                f"{ACCESS_TOKEN_ENV} is required to use the Raindrop MCP server."
            )
        return cls(token)

    async def __aenter__(self) -> RaindropClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json,
            )
        except httpx.RequestError:
            raise RaindropAPIError("Unable to reach the Raindrop.io API.") from None

        if response.is_error:
            raise RaindropAPIError(
                f"Raindrop.io API request failed with status {response.status_code}."
            ) from None

        try:
            payload = response.json()
        except ValueError:
            raise RaindropAPIError(
                "Raindrop.io API returned an invalid JSON response."
            ) from None

        if not isinstance(payload, dict):
            raise RaindropAPIError(
                "Raindrop.io API returned an unexpected response."
            )
        if payload.get("result") is False:
            raise RaindropAPIError("Raindrop.io API rejected the request.")

        return payload

    async def list_collections(
        self,
        *,
        include_children: bool = True,
    ) -> dict[str, Any]:
        """Return root collections and, optionally, nested collections."""
        root_payload = await self._request("GET", "collections")
        items = self._items_from(root_payload)

        if include_children:
            child_payload = await self._request("GET", "collections/childrens")
            items.extend(self._items_from(child_payload))

        return {"result": True, "items": items, "count": len(items)}

    async def list_tags(self, collection_id: int = 0) -> dict[str, Any]:
        """Return tag names and bookmark counts, optionally by collection."""
        path = "tags" if collection_id == 0 else f"tags/{collection_id}"
        return await self._request("GET", path)

    async def search_bookmarks(
        self,
        query: str | None = None,
        *,
        collection_id: int = 0,
        page: int = 0,
        per_page: int = 20,
        sort: str | None = None,
        nested: bool = True,
    ) -> dict[str, Any]:
        """List bookmarks or search with Raindrop.io's native syntax."""
        if page < 0:
            raise ValueError("Page must be zero or greater.")
        if not 1 <= per_page <= 50:
            raise ValueError("per_page must be between 1 and 50.")

        normalized_query = query.strip() if query is not None else ""
        effective_sort = sort or ("score" if normalized_query else "-created")
        params: dict[str, Any] = {
            "page": page,
            "perpage": per_page,
            "sort": effective_sort,
            "nested": nested,
        }
        if normalized_query:
            params["search"] = normalized_query

        return await self._request(
            "GET",
            f"raindrops/{collection_id}",
            params=params,
        )

    async def get_bookmark(self, bookmark_id: int) -> dict[str, Any]:
        """Return one bookmark by its Raindrop.io ID."""
        self._validate_bookmark_id(bookmark_id)
        return await self._request("GET", f"raindrop/{bookmark_id}")

    async def create_bookmark(
        self,
        link: str,
        *,
        title: str | None = None,
        collection_id: int | None = None,
        tags: list[str] | None = None,
        excerpt: str | None = None,
        note: str | None = None,
        important: bool | None = None,
        cover: str | None = None,
        parse_metadata: bool = True,
    ) -> dict[str, Any]:
        """Create one bookmark and return the API response."""
        if not link.strip():
            raise ValueError("Bookmark link must not be empty.")

        payload = self._bookmark_payload(
            link=link,
            title=title,
            collection_id=collection_id,
            tags=tags,
            excerpt=excerpt,
            note=note,
            important=important,
            cover=cover,
        )
        if parse_metadata:
            payload["pleaseParse"] = {}

        return await self._request("POST", "raindrop", json=payload)

    async def update_bookmark(
        self,
        bookmark_id: int,
        *,
        link: str | None = None,
        title: str | None = None,
        collection_id: int | None = None,
        tags: list[str] | None = None,
        excerpt: str | None = None,
        note: str | None = None,
        important: bool | None = None,
        cover: str | None = None,
        reparse_metadata: bool = False,
    ) -> dict[str, Any]:
        """Update selected fields on one bookmark."""
        self._validate_bookmark_id(bookmark_id)
        if link is not None and not link.strip():
            raise ValueError("Bookmark link must not be empty.")

        payload = self._bookmark_payload(
            link=link,
            title=title,
            collection_id=collection_id,
            tags=tags,
            excerpt=excerpt,
            note=note,
            important=important,
            cover=cover,
        )
        if reparse_metadata:
            payload["pleaseParse"] = {}
        if not payload:
            raise ValueError("At least one bookmark field must be provided.")

        return await self._request(
            "PUT",
            f"raindrop/{bookmark_id}",
            json=payload,
        )

    @staticmethod
    def _items_from(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items")
        if not isinstance(items, list) or not all(
            isinstance(item, dict) for item in items
        ):
            raise RaindropAPIError(
                "Raindrop.io API returned an unexpected collections response."
            )
        return list(items)

    @staticmethod
    def _validate_bookmark_id(bookmark_id: int) -> None:
        if bookmark_id <= 0:
            raise ValueError("bookmark_id must be a positive integer.")

    @staticmethod
    def _bookmark_payload(
        *,
        link: str | None,
        title: str | None,
        collection_id: int | None,
        tags: list[str] | None,
        excerpt: str | None,
        note: str | None,
        important: bool | None,
        cover: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        fields: dict[str, Any] = {
            "link": link,
            "title": title,
            "tags": tags,
            "excerpt": excerpt,
            "note": note,
            "important": important,
            "cover": cover,
        }
        payload.update({key: value for key, value in fields.items() if value is not None})
        if collection_id is not None:
            payload["collection"] = {"$id": collection_id}
        return payload
