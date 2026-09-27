"""
sgql MCP Server — thin adapter over the existing GraphQL gateway.

Design (Option A):
  • graphql_query  — forwards Query operations to the gateway (always registered)
  • graphql_mutate — forwards Mutation operations (registered in 'write' scope only)
  • sgql://schema  — MCP Resource exposing the current SDL for schema introspection

Auth/identity:
  Every forwarded HTTP request carries the same JWT Bearer token that is
  configured in sgql-mcp.yaml (gateway_token).  The gateway's existing
  JWTAuthenticationProvider validates it and populates the AuthContext that
  drives SQL-predicate row-level security.  MCP scope (read/write) controls
  WHICH OPERATIONS are visible; SQL predicates control WHICH ROWS are visible.

Audit:
  Every tool call is logged with timestamp, scope, resolved identity (sub claim),
  and the full GraphQL document sent.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
import jwt as pyjwt
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

from db_graphql_gateway.mcp.config import MCPConfig

logger = logging.getLogger("sgql.mcp")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_MUTATION_PATTERN = re.compile(
    r"^\s*mutation\b",
    re.IGNORECASE | re.MULTILINE,
)


def _is_mutation(query: str) -> bool:
    """Return True if the GraphQL document starts with 'mutation'."""
    return bool(_MUTATION_PATTERN.match(query.strip()))


def _resolved_identity(token: str | None) -> str:
    """Best-effort: decode JWT without verification to get the 'sub' claim."""
    if not token:
        return "<no-token>"
    try:
        payload = pyjwt.decode(token, options={"verify_signature": False})
        return str(payload.get("sub", "<no-sub>"))
    except Exception:
        return "<decode-error>"


def _audit_log(
    *,
    scope: str,
    operation: str,
    identity: str,
    query: str,
    variables: dict[str, Any] | None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(
        "MCP_AUDIT ts=%s scope=%s operation=%s identity=%s query=%r variables=%s",
        ts,
        scope,
        operation,
        identity,
        query,
        json.dumps(variables or {}),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Server factory
# ──────────────────────────────────────────────────────────────────────────────


def build_mcp_server(config: MCPConfig) -> MCPServer:
    """Construct and return a configured MCPServer instance.

    Tools are registered based on the configured scope:
      - "read"  → only graphql_query
      - "write" → graphql_query + graphql_mutate
    """

    identity = _resolved_identity(config.gateway_token)

    # ── shared HTTP client ──────────────────────────────────────────────────
    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=config.request_timeout) as client:
            server._sgql_http_client = client  # type: ignore[attr-defined]
            yield

    mcp = MCPServer(
        name="sgql",
        title="sgql GraphQL Gateway",
        description=(
            "Exposes the auto-generated sgql GraphQL API to MCP agents. " f"Scope: {config.scope}."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # ── helper: forward to gateway ─────────────────────────────────────────
    async def _call_gateway(
        query: str,
        variables: dict[str, Any] | None,
        ctx: Context,
        operation: str,
    ) -> str:
        client: httpx.AsyncClient = ctx.server._sgql_http_client  # type: ignore[attr-defined]

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if config.gateway_token:
            headers["Authorization"] = f"Bearer {config.gateway_token}"

        _audit_log(
            scope=config.scope,
            operation=operation,
            identity=identity,
            query=query,
            variables=variables,
        )

        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await client.post(
                config.gateway_url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ValueError(
                f"Gateway returned HTTP {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"Could not reach gateway at {config.gateway_url}: {exc}") from exc

        body = response.json()

        # Surface GraphQL-level errors as a tool error so the agent sees them
        if body.get("errors"):
            error_msgs = "; ".join(e.get("message", str(e)) for e in body["errors"])
            raise ValueError(f"GraphQL error(s): {error_msgs}")

        return json.dumps(body.get("data"), indent=2)

    # ── graphql_query tool ─────────────────────────────────────────────────
    @mcp.tool(
        name="graphql_query",
        description=(
            "Execute a GraphQL **query** against the sgql gateway. "
            "Only `query { ... }` operations are accepted — mutations are rejected. "
            "The gateway enforces auth predicates and complexity/depth limits. "
            "Returns the GraphQL `data` field as JSON."
        ),
    )
    async def graphql_query(
        query: str,
        variables: str = "{}",
        ctx: Context = ...,  # type: ignore[assignment]
    ) -> str:
        """
        Args:
            query:     A valid GraphQL query string (must start with 'query').
            variables: JSON-encoded variables object (optional, default '{}').
        """
        if _is_mutation(query):
            raise ValueError(
                "graphql_query only accepts query operations. " "Use graphql_mutate for mutations."
            )

        try:
            parsed_vars: dict[str, Any] = json.loads(variables) if variables.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"variables must be valid JSON: {exc}") from exc

        return await _call_gateway(query, parsed_vars or None, ctx, "query")

    # ── graphql_mutate tool (write scope only) ─────────────────────────────
    if config.scope == "write":

        @mcp.tool(
            name="graphql_mutate",
            description=(
                "Execute a GraphQL **mutation** against the sgql gateway. "
                "Only `mutation { ... }` operations are accepted — queries are rejected. "
                "The gateway enforces auth predicates and complexity/depth limits. "
                "Returns the GraphQL `data` field as JSON. "
                "⚠️  This tool is only available in 'write' scope."
            ),
        )
        async def graphql_mutate(
            mutation: str,
            variables: str = "{}",
            ctx: Context = ...,  # type: ignore[assignment]
        ) -> str:
            """
            Args:
                mutation:  A valid GraphQL mutation string (must start with 'mutation').
                variables: JSON-encoded variables object (optional, default '{}').
            """
            if not _is_mutation(mutation):
                raise ValueError(
                    "graphql_mutate only accepts mutation operations. "
                    "Use graphql_query for queries."
                )

            try:
                parsed_vars: dict[str, Any] = json.loads(variables) if variables.strip() else {}
            except json.JSONDecodeError as exc:
                raise ValueError(f"variables must be valid JSON: {exc}") from exc

            return await _call_gateway(mutation, parsed_vars or None, ctx, "mutation")

    # ── schema resource ────────────────────────────────────────────────────
    @mcp.resource(
        uri=config.schema_resource_uri,
        name="GraphQL Schema (SDL)",
        description=(
            "The current SDL (Schema Definition Language) of the sgql gateway. "
            "Fetch this to discover available types, fields, queries, and mutations "
            "before constructing GraphQL documents."
        ),
        mime_type="text/plain",
    )
    async def graphql_schema() -> str:
        """Return the gateway's SDL via introspection.

        Note: static resources cannot inject Context in MCP 2.x, so we create
        a short-lived httpx client here.  Schema fetches are infrequent (once
        per agent session startup) so the per-call overhead is negligible.
        """
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if config.gateway_token:
            headers["Authorization"] = f"Bearer {config.gateway_token}"

        sdl_query = """
        {
          __schema {
            types {
              kind
              name
              description
              fields(includeDeprecated: true) {
                name
                description
                type {
                  kind
                  name
                  ofType {
                    kind
                    name
                    ofType {
                      kind
                      name
                    }
                  }
                }
                isDeprecated
                deprecationReason
              }
              inputFields {
                name
                type { kind name ofType { kind name } }
              }
              enumValues(includeDeprecated: true) {
                name
              }
            }
            queryType { name }
            mutationType { name }
          }
        }
        """

        try:
            async with httpx.AsyncClient(timeout=config.request_timeout) as client:
                response = await client.post(
                    config.gateway_url,
                    json={"query": sdl_query},
                    headers=headers,
                )
                response.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            raise ValueError(f"Could not fetch schema from gateway: {exc}") from exc

        body = response.json()

        if body.get("errors"):
            # Introspection locked down in production — return a notice
            msgs = "; ".join(e.get("message", "") for e in body["errors"])
            return f"# Schema introspection is disabled on this gateway.\n# Error: {msgs}"

        # Convert raw introspection JSON → lightweight SDL summary
        return _introspection_to_sdl_summary(body.get("data", {}).get("__schema", {}))

    return mcp


# ──────────────────────────────────────────────────────────────────────────────
# SDL summary builder (raw introspection → human-readable SDL-like text)
# ──────────────────────────────────────────────────────────────────────────────

_BUILTIN_TYPES = frozenset(
    {
        "String",
        "Int",
        "Float",
        "Boolean",
        "ID",
        "__Schema",
        "__Type",
        "__Field",
        "__InputValue",
        "__EnumValue",
        "__Directive",
        "__DirectiveLocation",
    }
)


def _format_type(t: dict[str, Any] | None, depth: int = 0) -> str:
    if t is None or depth > 5:
        return "Unknown"
    kind = t.get("kind", "")
    name = t.get("name") or ""
    of_type = t.get("ofType")
    if kind == "NON_NULL":
        return f"{_format_type(of_type, depth + 1)}!"
    if kind == "LIST":
        return f"[{_format_type(of_type, depth + 1)}]"
    return name


def _introspection_to_sdl_summary(schema: dict[str, Any]) -> str:
    """Produce a concise SDL-like text from raw __schema introspection data."""
    lines: list[str] = ["# sgql Gateway — GraphQL Schema Summary", ""]

    query_type_name = (schema.get("queryType") or {}).get("name")
    mutation_type_name = (schema.get("mutationType") or {}).get("name")

    types: list[dict[str, Any]] = schema.get("types", [])

    for t in types:
        name = t.get("name", "")
        if name.startswith("__") or name in _BUILTIN_TYPES:
            continue
        kind = t.get("kind", "")
        desc = t.get("description") or ""
        fields = t.get("fields") or []
        input_fields = t.get("inputFields") or []
        enum_values = t.get("enumValues") or []

        if kind == "OBJECT":
            tag = "type"
            if name == query_type_name:
                tag = "type Query"
                name = ""
            elif name == mutation_type_name:
                tag = "type Mutation"
                name = ""
            header = f"{tag} {name}".strip()
            if desc:
                lines.append('"""')
                lines.append(desc)
                lines.append('"""')
            lines.append(f"{header} {{")
            for f in fields:
                ft = _format_type(f.get("type"))
                fdesc = f.get("description") or ""
                fdesc_part = f"  # {fdesc}" if fdesc else ""
                depr = "  @deprecated" if f.get("isDeprecated") else ""
                lines.append(f"  {f['name']}: {ft}{depr}{fdesc_part}")
            lines.append("}")
            lines.append("")

        elif kind == "INPUT_OBJECT":
            if desc:
                lines.append('"""')
                lines.append(desc)
                lines.append('"""')
            lines.append(f"input {name} {{")
            for f in input_fields:
                ft = _format_type(f.get("type"))
                lines.append(f"  {f['name']}: {ft}")
            lines.append("}")
            lines.append("")

        elif kind == "ENUM":
            if desc:
                lines.append('"""')
                lines.append(desc)
                lines.append('"""')
            lines.append(f"enum {name} {{")
            for ev in enum_values:
                lines.append(f"  {ev['name']}")
            lines.append("}")
            lines.append("")

    return "\n".join(lines)
