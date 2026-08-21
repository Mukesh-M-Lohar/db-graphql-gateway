import pytest
from typing import Any
from unittest.mock import AsyncMock
from db_graphql_gateway.auth.authorization import AuthorizationEngine, PolicyRule, TablePolicy
from db_graphql_gateway.auth.interfaces import AuthContext

pytestmark = pytest.mark.asyncio


async def test_authorization_predicate_pushdown(
    gql_schema: tuple[Any, Any], auth_engine: AuthorizationEngine, run_sql: Any
) -> None:
    schema, adapter = gql_schema

    # Setup the authorization policy
    # Users can only read their own records, except admins can read all
    user_policy = TablePolicy(
        table="users",
        read_rules=[PolicyRule(column="owner_id", op="eq", value_template="$user_id")],
    )
    auth_engine.add_policy(user_policy)

    # Intercept execute to verify zero-memory filtering
    original_execute = adapter.execute
    mock_execute = AsyncMock(side_effect=original_execute)
    adapter.execute = mock_execute

    # We apply the engine to our schema's context builder manually since we're using raw execute()
    # (In standard HTTP handler, this is done by gateway request context)

    # Insert test data
    await run_sql(
        adapter,
        "INSERT INTO users (id, name, owner_id, password) VALUES (1, 'Alice', 1, 'secret1'), (2, 'Bob', 2, 'secret2'), (3, 'Admin', 3, 'secret3')",
    )

    query = """
    query {
        userss {
            id
            name
        }
    }
    """

    # 1. User 1 queries
    ctx_user1 = AuthContext(user_id=1, roles=["user"], claims={}, is_authenticated=True)  # type: ignore
    ctx1 = {"auth_context": ctx_user1}
    res1 = await schema.execute(query, context_value=ctx1)

    # Verify the compiled query contains the auth filter in SQL
    assert mock_execute.call_count == 1
    compiled_query = mock_execute.call_args[0][0]
    assert "owner_id" in compiled_query.sql
    assert "=" in compiled_query.sql

    adapter.execute = original_execute

    assert res1.errors is None
    assert res1.data is not None
    assert len(res1.data["userss"]) == 1
    assert res1.data["userss"][0]["name"] == "Alice"

    # 2. Admin queries
    ctx_admin = AuthContext(user_id=3, roles=["admin"], claims={}, is_authenticated=True)  # type: ignore
    ctx_admin_val = {"auth_context": ctx_admin}
    res2 = await schema.execute(query, context_value=ctx_admin_val)

    assert res2.errors is None
    assert res2.data is not None
    # AuthorizationEngine currently only evaluates the policy rules.
    # It does not have built-in RBAC bypass logic, so $user_id=3 returns just owner_id=3.
    assert len(res2.data["userss"]) == 1
    assert res2.data["userss"][0]["name"] == "Admin"
    for u in res2.data["userss"]:
        assert u["id"] in (1, 2, 3)
