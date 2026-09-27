# MCP Integration

Connect Claude Desktop, Claude Code, Cursor, Windsurf, and any other MCP-compatible agent directly to your sgql gateway — with **scoped, enforced permissions** at the MCP layer.

---

## How it works

The sgql MCP server is a **thin stdio/HTTP adapter** that sits between an MCP client and the existing sgql gateway HTTP endpoint. It exposes two tools and one resource:

| Name | Type | Scope | Description |
|---|---|---|---|
| `graphql_query` | Tool | `read` + `write` | Execute a GraphQL `query` document |
| `graphql_mutate` | Tool | `write` only | Execute a GraphQL `mutation` document |
| `sgql://schema` | Resource | always | Current GraphQL SDL (schema definition) |

**No gateway logic is reimplemented.** Every call is forwarded to the existing `/graphql` HTTP endpoint via `httpx`. This means:

- ✅ Existing JWT auth + SQL row-level predicates apply to every MCP call
- ✅ Complexity, depth, and alias limits apply to every MCP call
- ✅ DataLoader batching and field masking apply to every MCP call
- ✅ The MCP server adds zero duplication

---

## Scope enforcement

The `scope` setting controls **which tools are registered** — an agent cannot call a tool that was never registered:

```
scope: read   →  graphql_query  only  (graphql_mutate is not visible at all)
scope: write  →  graphql_query + graphql_mutate
```

> [!IMPORTANT]
> Scope is enforced at the MCP layer by **not registering** the mutation tool in read scope. The gateway's own auth is an additional, independent layer. Both apply; neither replaces the other.

---

## Auth / Identity mapping

The gateway expects a **JWT Bearer token** in the `Authorization` HTTP header. The MCP server forwards a single **config-time token** on every request.

```
MCP client
    │ (no auth required for local stdio)
    ▼
sgql MCP server
    │ adds: Authorization: Bearer <gateway_token>
    ▼
sgql gateway (validates JWT, derives AuthContext → SQL predicates)
    │ row-level security filters rows based on user_id / tenant_id claims
    ▼
Database
```

Generate a token for your service account:

```python
import jwt
payload = {
    "iss": "your-issuer",
    "aud": "your-audience",
    "sub": "mcp-service-account",
    "user_id": 1,
    "tenant_id": 42,
}
token = jwt.encode(payload, "your-hs256-secret", algorithm="HS256")
print(token)
```

> [!WARNING]
> For stdio transport, the token is stored in `sgql-mcp.yaml` on disk.  
> Set `gateway_token: null` and use the `SGQL_GATEWAY_TOKEN` environment variable in production to avoid storing secrets in config files.

---

## Installation

```bash
# Install with mcp extra
pip install "db-graphql-gateway[mcp]"

# or with uv
uv add "db-graphql-gateway[mcp]"
```

---

## Quick start

**1. Create `sgql-mcp.yaml` in your project root:**

=== "Read-only"

    ```yaml
    scope: read
    gateway_url: "http://localhost:8000/graphql"
    gateway_token: null   # use SGQL_GATEWAY_TOKEN env var
    transport: stdio
    ```

=== "Write (full access)"

    ```yaml
    scope: write
    gateway_url: "http://localhost:8000/graphql"
    gateway_token: null   # use SGQL_GATEWAY_TOKEN env var
    transport: stdio
    ```

**2. Set the gateway token:**

```bash
export SGQL_GATEWAY_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**3. Start the MCP server:**

```bash
python -m db_graphql_gateway.mcp
# or, if installed as a script:
sgql-mcp
```

---

## Client configuration

### Claude Desktop

Add the following to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

=== "Read-only"

    ```json
    {
      "mcpServers": {
        "sgql": {
          "command": "python",
          "args": ["-m", "db_graphql_gateway.mcp"],
          "env": {
            "SGQL_MCP_SCOPE": "read",
            "SGQL_GATEWAY_URL": "http://localhost:8000/graphql",
            "SGQL_GATEWAY_TOKEN": "<your-jwt-token>"
          }
        }
      }
    }
    ```

=== "Write"

    ```json
    {
      "mcpServers": {
        "sgql": {
          "command": "python",
          "args": ["-m", "db_graphql_gateway.mcp"],
          "env": {
            "SGQL_MCP_SCOPE": "write",
            "SGQL_GATEWAY_URL": "http://localhost:8000/graphql",
            "SGQL_GATEWAY_TOKEN": "<your-jwt-token>"
          }
        }
      }
    }
    ```

=== "With config file"

    ```json
    {
      "mcpServers": {
        "sgql": {
          "command": "python",
          "args": ["-m", "db_graphql_gateway.mcp", "--config", "/path/to/sgql-mcp.yaml"]
        }
      }
    }
    ```

### Claude Code

Add to your project's `.mcp.json` or Claude Code's MCP settings:

```json
{
  "mcpServers": {
    "sgql": {
      "command": "python",
      "args": ["-m", "db_graphql_gateway.mcp"],
      "env": {
        "SGQL_MCP_SCOPE": "read",
        "SGQL_GATEWAY_URL": "http://localhost:8000/graphql",
        "SGQL_GATEWAY_TOKEN": "<your-jwt-token>"
      }
    }
  }
}
```

### Cursor / Windsurf / other stdio clients

Any stdio-based MCP client works identically — point the `command` to `python -m db_graphql_gateway.mcp` and pass scope/token via environment variables.

---

## Configuration reference (`sgql-mcp.yaml`)

| Key | Type | Default | Description |
|---|---|---|---|
| `scope` | `"read"` \| `"write"` | `"read"` | MCP operation scope |
| `gateway_url` | string | `"http://localhost:8000/graphql"` | GraphQL endpoint URL |
| `gateway_token` | string \| null | null | JWT Bearer token (or use `SGQL_GATEWAY_TOKEN`) |
| `transport` | `"stdio"` \| `"sse"` \| `"streamable-http"` | `"stdio"` | MCP transport |
| `host` | string | `"127.0.0.1"` | Host for SSE/HTTP transports |
| `port` | int | `8765` | Port for SSE/HTTP transports |
| `schema_resource_uri` | string | `"sgql://schema"` | URI for the schema resource |
| `request_timeout` | float | `30.0` | HTTP timeout for gateway calls (seconds) |

All settings can be overridden via CLI flags or environment variables:

| Env var | CLI flag | Overrides |
|---|---|---|
| `SGQL_MCP_CONFIG` | `--config` | config file path |
| `SGQL_MCP_SCOPE` | `--scope` | `scope` |
| `SGQL_GATEWAY_URL` | `--gateway-url` | `gateway_url` |
| `SGQL_GATEWAY_TOKEN` | `--gateway-token` | `gateway_token` |
| `SGQL_MCP_TRANSPORT` | `--transport` | `transport` |
| `SGQL_MCP_HOST` | `--host` | `host` |
| `SGQL_MCP_PORT` | `--port` | `port` |
| `SGQL_MCP_LOG_LEVEL` | `--log-level` | log verbosity |

---

## Using the schema resource

Before sending a query, fetch the schema to discover available types:

```
# In any MCP client that supports resources:
sgql://schema
```

The resource returns a human-readable SDL summary of all types, fields, queries, and mutations. This respects the gateway's field masking (hidden/sensitive fields are not returned by the gateway's introspection, so they won't appear here either).

> [!NOTE]
> If the gateway has `disable_introspection: true` set, the schema resource will return a notice explaining that introspection is disabled. This is intentional — the MCP server does not bypass production security settings.

---

## Tool usage examples

Once connected, an agent can:

```
# Discover schema
Read resource: sgql://schema

# Query data
Use tool: graphql_query
  query: "query { users { id username } }"
  variables: "{}"

# (write scope only) Create a record
Use tool: graphql_mutate
  mutation: "mutation { create_posts(input: { title: \"Hello\" }) { id title } }"
  variables: "{}"
```

---

## Audit logging

Every MCP tool call is logged (to stderr) with:

```
sgql.mcp INFO  MCP_AUDIT ts=2026-01-15T10:23:45Z scope=read operation=query identity=<sub-claim> query='query { users { id } }' variables={}
```

Set `SGQL_MCP_LOG_LEVEL=DEBUG` for verbose output including full request/response headers.

---

## Remote transport (SSE / HTTP)

For remote agents (not local stdio), use `transport: sse` or `transport: streamable-http`.

> [!CAUTION]
> Remote transports expose the MCP server over a network. You MUST put the server behind a reverse proxy with TLS and protect it with a bearer token per connection. The gateway token in `sgql-mcp.yaml` is a **shared service-account secret** — never expose it to end users; each user should have their own gateway token with appropriate claims.

```yaml
# Remote SSE example
scope: read
gateway_url: "http://internal-gateway:8000/graphql"
gateway_token: null  # use SGQL_GATEWAY_TOKEN
transport: sse
host: "0.0.0.0"
port: 8765
```

---

## Running the tests

```bash
# Unit tests (no gateway required)
cd integration_tests
uv run pytest test_mcp.py -v -k "not TestLiveIntegration"

# Full integration tests (gateway must be running)
SGQL_DATABASE_URL=sqlite:///test.db uvicorn server:app --port 8000 &
uv run pytest test_mcp.py -v
```
