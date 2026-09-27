"""Configuration model for sgql-mcp.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MCPConfig(BaseModel):
    """Configuration for the sgql MCP server (sgql-mcp.yaml)."""

    # ── scope ──────────────────────────────────────────────────────────────
    # "read"  → only graphql_query tool is registered (no graphql_mutate)
    # "write" → both graphql_query and graphql_mutate are registered
    scope: Literal["read", "write"] = "read"

    # ── gateway connection ─────────────────────────────────────────────────
    # URL of the running sgql gateway's /graphql endpoint.
    # The MCP server forwards all requests here via httpx.
    gateway_url: str = "http://localhost:8000/graphql"

    # ── identity / auth ───────────────────────────────────────────────────
    # A JWT Bearer token the MCP server sends on every forwarded HTTP request
    # to the gateway.  The gateway's existing JWTAuthenticationProvider
    # validates this token and derives the AuthContext (user_id, tenant_id,
    # etc.) that drives SQL-predicate row-level security.
    #
    # For local stdio use you can embed a long-lived service-account token
    # here.  For remote SSE/HTTP transport, the per-connection bearer token
    # is the right mechanism (see docs/mcp.md).
    gateway_token: str | None = None

    # ── transport ─────────────────────────────────────────────────────────
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio"

    # sse / streamable-http options (ignored for stdio)
    host: str = "127.0.0.1"
    port: int = 8765

    # ── schema resource ───────────────────────────────────────────────────
    # URI of the SDL resource exposed by the MCP server.
    # Clients can fetch this to understand available types/fields.
    schema_resource_uri: str = "sgql://schema"

    # ── request settings ──────────────────────────────────────────────────
    request_timeout: float = Field(default=30.0, gt=0)

    @field_validator("gateway_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")
