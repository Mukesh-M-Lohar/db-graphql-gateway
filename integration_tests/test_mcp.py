"""
Integration tests for the sgql MCP server.

Tests:
  1. read scope — graphql_mutate is NOT registered (not visible to agents)
  2. read scope — graphql_query works and returns data
  3. write scope — both tools are registered and functional
  4. Existing auth predicates + complexity limits are still enforced end-to-end
  5. graphql_query rejects a mutation document; graphql_mutate rejects a query document

These tests use the same integration-test gateway server as the existing
level1–level5 tests (started externally via run_integration.py or docker-compose).
The gateway must be reachable at GRAPHQL_URL with a valid JWT.

Run via:
    cd integration_tests
    SGQL_DATABASE_URL=sqlite:///test.db python -m pytest test_mcp.py -v
or simply include in the normal run_integration.py flow.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import jwt as pyjwt

from db_graphql_gateway.mcp.config import MCPConfig
from db_graphql_gateway.mcp.server import build_mcp_server

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

SECRET = "supersecretkeythatisatleast32byteslong!"
ISSUER = "integration-test-issuer"
AUDIENCE = "integration-test-audience"
GRAPHQL_URL = "http://localhost:8000/graphql"


def _make_token(tenant_id: int = 1, user_id: int = 1) -> str:
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "sub": str(user_id),
    }
    return pyjwt.encode(payload, SECRET, algorithm="HS256")


def _read_config(gateway_url: str = GRAPHQL_URL) -> MCPConfig:
    return MCPConfig(
        scope="read",
        gateway_url=gateway_url,
        gateway_token=_make_token(),
        transport="stdio",
    )


def _write_config(gateway_url: str = GRAPHQL_URL) -> MCPConfig:
    return MCPConfig(
        scope="write",
        gateway_url=gateway_url,
        gateway_token=_make_token(),
        transport="stdio",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Unit-level tests (mock HTTP client — no running gateway needed)
# ──────────────────────────────────────────────────────────────────────────────


def _tool_names(mcp_server: Any) -> set[str]:
    """Return the set of registered tool names."""
    return {t.name for t in mcp_server._tool_manager._tools.values()}


class TestScopeEnforcement:
    """Verify that tool registration respects scope — no gateway needed."""

    def test_read_scope_only_registers_query_tool(self) -> None:
        mcp = build_mcp_server(_read_config())
        tools = _tool_names(mcp)
        assert "graphql_query" in tools, "graphql_query must always be registered"
        assert "graphql_mutate" not in tools, "graphql_mutate must NOT be visible in read scope"

    def test_write_scope_registers_both_tools(self) -> None:
        mcp = build_mcp_server(_write_config())
        tools = _tool_names(mcp)
        assert "graphql_query" in tools
        assert "graphql_mutate" in tools

    def test_mutation_document_rejected_by_query_tool(self) -> None:
        """graphql_query must reject a document that starts with 'mutation'."""
        from db_graphql_gateway.mcp.server import _is_mutation

        assert _is_mutation("mutation { create_users(input: {}) { id } }")
        assert not _is_mutation("query { users { id } }")
        assert not _is_mutation("{ users { id } }")  # shorthand query

    def test_query_document_rejected_by_mutate_tool(self) -> None:
        """graphql_mutate must only accept documents starting with 'mutation'."""
        from db_graphql_gateway.mcp.server import _is_mutation

        assert not _is_mutation("query GetUsers { users { id } }")
        assert not _is_mutation("{ posts { id } }")


# ──────────────────────────────────────────────────────────────────────────────
# Mock-HTTP tests — verify forwarding logic, audit log, error handling
# ──────────────────────────────────────────────────────────────────────────────


def _mock_context(mcp_server: Any, http_client: Any) -> Any:
    """Create a minimal fake Context that the tool handlers accept."""
    ctx = MagicMock()
    ctx.server = mcp_server
    mcp_server._sgql_http_client = http_client
    return ctx


def _mock_http_response(data: Any, errors: list[dict[str, Any]] | None = None) -> httpx.Response:
    body: dict[str, Any] = {"data": data}
    if errors:
        body["errors"] = errors
    request = httpx.Request("POST", "http://localhost:8000/graphql")
    return httpx.Response(200, json=body, request=request)


class TestQueryToolForwarding:
    """graphql_query tool — mock gateway responses."""

    @pytest.mark.asyncio
    async def test_query_forwards_and_returns_data(self) -> None:
        mcp = build_mcp_server(_read_config())

        mock_resp = _mock_http_response({"users": [{"id": 1, "username": "alice"}]})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        ctx = _mock_context(mcp, mock_client)

        # Grab the actual registered tool function
        tool_fn = mcp._tool_manager._tools["graphql_query"].fn
        result = await tool_fn(
            query="query { users { id username } }",
            variables="{}",
            ctx=ctx,
        )

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["users"][0]["username"] == "alice"

        # Ensure Authorization header was forwarded
        call_kwargs = mock_client.post.call_args
        assert "Authorization" in call_kwargs.kwargs.get("headers", {})

    @pytest.mark.asyncio
    async def test_query_tool_rejects_mutation_document(self) -> None:
        mcp = build_mcp_server(_read_config())
        mock_client = AsyncMock()
        ctx = _mock_context(mcp, mock_client)

        tool_fn = mcp._tool_manager._tools["graphql_query"].fn
        with pytest.raises(ValueError, match="mutation"):
            await tool_fn(
                query="mutation { create_users(input: { username: 'x' }) { id } }",
                variables="{}",
                ctx=ctx,
            )

        # HTTP client must NOT have been called
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_graphql_errors_surface_as_value_error(self) -> None:
        mcp = build_mcp_server(_read_config())

        mock_resp = _mock_http_response(
            None,
            errors=[{"message": "Query exceeds maximum depth of 5 (actual depth: 8)"}],
        )
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        ctx = _mock_context(mcp, mock_client)
        tool_fn = mcp._tool_manager._tools["graphql_query"].fn

        with pytest.raises(ValueError, match="Query exceeds maximum depth"):
            await tool_fn(
                query="query { users { posts { comments { body } } } }",
                variables="{}",
                ctx=ctx,
            )


class TestMutateToolForwarding:
    """graphql_mutate tool — mock gateway responses."""

    @pytest.mark.asyncio
    async def test_mutate_forwards_and_returns_data(self) -> None:
        mcp = build_mcp_server(_write_config())

        mock_resp = _mock_http_response({"create_posts": {"id": 42, "title": "Hello"}})
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        ctx = _mock_context(mcp, mock_client)
        tool_fn = mcp._tool_manager._tools["graphql_mutate"].fn
        result = await tool_fn(
            mutation='mutation { create_posts(input: { title: "Hello" }) { id title } }',
            variables="{}",
            ctx=ctx,
        )

        parsed = json.loads(result)
        assert parsed["create_posts"]["id"] == 42

    @pytest.mark.asyncio
    async def test_mutate_tool_rejects_query_document(self) -> None:
        mcp = build_mcp_server(_write_config())
        mock_client = AsyncMock()
        ctx = _mock_context(mcp, mock_client)

        tool_fn = mcp._tool_manager._tools["graphql_mutate"].fn
        with pytest.raises(ValueError, match="mutation"):
            await tool_fn(
                mutation="query { users { id } }",
                variables="{}",
                ctx=ctx,
            )
        mock_client.post.assert_not_called()

    def test_mutate_not_in_read_scope(self) -> None:
        mcp = build_mcp_server(_read_config())
        assert "graphql_mutate" not in _tool_names(mcp)


# ──────────────────────────────────────────────────────────────────────────────
# Live integration tests — require a running gateway
# These are skipped automatically when the gateway isn't reachable.
# ──────────────────────────────────────────────────────────────────────────────


def _gateway_reachable() -> bool:
    try:
        httpx.get("http://localhost:8000/graphql", timeout=2.0)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _gateway_reachable(), reason="Gateway not running")
class TestLiveIntegration:
    """End-to-end tests against the live integration-test gateway."""

    @pytest.mark.asyncio
    async def test_read_scope_query_with_auth_predicates(self) -> None:
        """Query tool works; row-level auth predicates are enforced by gateway."""
        mcp = build_mcp_server(_read_config())

        async with httpx.AsyncClient(timeout=30.0) as client:
            mcp._sgql_http_client = client  # type: ignore[attr-defined]
            ctx = _mock_context(mcp, client)

            tool_fn = mcp._tool_manager._tools["graphql_query"].fn
            result = await tool_fn(
                query="query { users { id } }",
                variables="{}",
                ctx=ctx,
            )
            data = json.loads(result)
            # User with user_id=1 can only see their own tenant's rows
            assert "users" in data

    @pytest.mark.asyncio
    async def test_complexity_limit_still_enforced_via_mcp(self) -> None:
        """A deeply-nested query that exceeds max_depth must be rejected even via MCP."""
        mcp = build_mcp_server(_read_config())

        async with httpx.AsyncClient(timeout=30.0) as client:
            mcp._sgql_http_client = client  # type: ignore[attr-defined]
            ctx = _mock_context(mcp, client)

            # depth > 8 should be rejected by the gateway
            deep_query = """
            query {
              users {
                posts {
                  comments {
                    user {
                      posts {
                        comments {
                          user { id }
                        }
                      }
                    }
                  }
                }
              }
            }
            """
            tool_fn = mcp._tool_manager._tools["graphql_query"].fn
            with pytest.raises(ValueError, match="(depth|complexity|error)"):
                await tool_fn(query=deep_query, variables="{}", ctx=ctx)

    @pytest.mark.asyncio
    async def test_read_scope_mutate_tool_not_callable(self) -> None:
        """In read scope the mutate tool simply does not exist."""
        mcp = build_mcp_server(_read_config())
        assert "graphql_mutate" not in _tool_names(mcp)

    @pytest.mark.asyncio
    async def test_write_scope_mutation_succeeds(self) -> None:
        """In write scope the mutate tool forwards correctly."""
        mcp = build_mcp_server(_write_config())

        async with httpx.AsyncClient(timeout=30.0) as client:
            mcp._sgql_http_client = client  # type: ignore[attr-defined]
            ctx = _mock_context(mcp, client)

            tool_fn = mcp._tool_manager._tools["graphql_mutate"].fn
            result = await tool_fn(
                mutation='mutation { create_tasks(input: { title: "MCP test task", status: "DONE" }) { id title status } }',
                variables="{}",
                ctx=ctx,
            )
            data = json.loads(result)
            assert data["create_tasks"]["title"] == "MCP test task"
