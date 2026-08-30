# Raindrop.io MCP server

A small, auditable local Python MCP server for searching and managing bookmarks
through the official Raindrop.io REST API. It is an unofficial integration that
uses the MCP Python SDK, `httpx`, and stdio transport.

## Tools

| Tool | Access | Description |
| --- | --- | --- |
| `list_collections` | Read | List root and nested collections. |
| `search_bookmarks` | Read | List bookmarks or search with Raindrop.io's native syntax. |
| `get_bookmark` | Read | Get one bookmark by ID. |
| `create_bookmark` | Write | Create a bookmark. |
| `update_bookmark` | Write | Update supplied fields on a bookmark. |

## Requirements

- Python 3.10 or newer
- [uv](https://docs.astral.sh/uv/)
- A Raindrop.io test token for your own account

## Install

```bash
uv sync --extra test
cp .env.example .env
```

Open the [Raindrop.io integrations settings](https://app.raindrop.io/settings/integrations),
create an application, and select **Create test token**. Add that token to your
local `.env` file:

```dotenv
RAINDROP_ACCESS_TOKEN=your-test-token
```

Use the test token, not the Client ID or Client Secret. Never commit or share
the populated `.env` file.

## Configure Codex

Add the following to `~/.codex/config.toml`, replacing the working directory
with the absolute path to your clone:

```toml
[mcp_servers.raindrop]
command = "uv"
args = ["run", "--env-file", ".env", "raindrop-mcp"]
cwd = "/absolute/path/to/raindrop-mcp-server"
enabled = true
default_tools_approval_mode = "writes"

[mcp_servers.raindrop.tools.list_collections]
approval_mode = "approve"

[mcp_servers.raindrop.tools.search_bookmarks]
approval_mode = "approve"

[mcp_servers.raindrop.tools.get_bookmark]
approval_mode = "approve"
```

Restart Codex after saving the configuration. Read tools are approved by the
per-tool settings; create and update remain subject to write approval.

Running `uv run --env-file .env raindrop-mcp` directly starts the stdio server
and waits for an MCP host. The server must not print application output to
stdout because stdout carries MCP protocol messages.

## Tool behavior

- Collection ID `0` searches all bookmarks.
- Omit `query` to list bookmarks, or provide Raindrop.io's native search syntax.
- Search pages are zero-indexed, default to 20 items, and allow at most 50.
- Searches default to relevance; listings default to newest first.
- Search returns compact bookmark summaries; use `get_bookmark` for detail.
- Heavy API metadata such as media, cache data, and highlights is omitted from
  MCP responses.
- Create and update map `collection_id` to Raindrop.io's
  `{"collection": {"$id": ...}}` request shape.
- Write tools do not perform implicit follow-up reads. `update_bookmark`
  returns a compact acknowledgement (`id`, `updated`, and `updated_fields`)
  instead of exposing the full Raindrop.io update response.
- MCP tool annotations describe read, mutation, idempotency, and external-service
  behavior to clients. These annotations are hints, not access controls.
- `parse_metadata` and `reparse_metadata` map to the official `pleaseParse: {}`
  request field.

## Security

- The server reads credentials only from `RAINDROP_ACCESS_TOKEN`.
- `.env` and other local environment files are ignored by Git; only the empty
  `.env.example` template is tracked.
- API response bodies are not included in raised error messages.
- Tests use fake tokens and `httpx.MockTransport`; they never call Raindrop.io.

## Test

```bash
uv run pytest
```

## License

This project is licensed under the [MIT License](LICENSE).

## API references

- [Obtain an access token](https://developer.raindrop.io/v1/authentication/token)
- [Make authorized calls](https://developer.raindrop.io/v1/authentication/calls)
- [Collection methods](https://developer.raindrop.io/v1/collections/methods)
- [Multiple raindrops](https://developer.raindrop.io/v1/raindrops/multiple)
- [Single raindrop](https://developer.raindrop.io/v1/raindrops/single)
