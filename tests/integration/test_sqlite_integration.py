"""SQLite end-to-end integration tests.

These tests run entirely in-memory (no Docker container required) and cover
the full pipeline from database connection through GraphQL execution.

Exit criteria (Phase 18):
- Full lifecycle: connect → DDL → introspect → IR build → GraphQL schema build
  → list query → create/update/delete mutations
- Soft-delete: list query automatically appends WHERE deleted_at IS NULL
- Optimistic locking: conflicting update raises GraphQLError
- Zero-memory-filtering: auth policy compiles to WHERE "owner_id" = ? in SQL
"""

import pytest
import pytest_asyncio
from typing import Any

from db_graphql_gateway.auth.authorization import AuthorizationEngine, PolicyRule, TablePolicy
from db_graphql_gateway.auth.interfaces import AuthContext
from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sqlite_schema():
    """In-memory SQLite adapter with a multi-table schema for integration tests."""
    adapter = SQLiteAdapter(":memory:")
    await adapter.connect()

    conn = adapter._conn
    assert conn is not None

    # Standard table
    await conn.execute(
        """
        CREATE TABLE items (
            id      INTEGER PRIMARY KEY,
            name    TEXT NOT NULL,
            owner_id INTEGER
        )
        """
    )
    # Table with soft-delete support
    await conn.execute(
        """
        CREATE TABLE articles (
            id         INTEGER PRIMARY KEY,
            title      TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    # Table with optimistic locking
    await conn.execute(
        """
        CREATE TABLE tasks (
            id      INTEGER PRIMARY KEY,
            summary TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    await conn.commit()

    yield adapter
    await adapter.close()


@pytest_asyncio.fixture
async def gql_schema(sqlite_schema: SQLiteAdapter) -> tuple[Any, SQLiteAdapter]:
    """Build a Strawberry GraphQL schema from the SQLite adapter."""
    inspector = sqlite_schema.inspector()
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=sqlite_schema.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    builder = GraphQLSchemaBuilder(db_adapter=sqlite_schema)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)
    return schema, sqlite_schema


# ---------------------------------------------------------------------------
# Phase 18 — Full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_query_returns_empty_initially(gql_schema: tuple[Any, SQLiteAdapter]) -> None:
    schema, adapter = gql_schema
    result = await schema.execute("query { itemss { id name } }")
    assert result.errors is None
    assert result.data is not None
    assert result.data["itemss"] == []


@pytest.mark.asyncio
async def test_create_mutation(gql_schema: tuple[Any, SQLiteAdapter]) -> None:
    schema, adapter = gql_schema
    result = await schema.execute(
        'mutation { create_items(input: { name: "Widget" }) { id name } }'
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    assert result.data is not None
    item = result.data["create_items"]
    assert item["name"] == "Widget"
    assert item["id"] is not None


@pytest.mark.asyncio
async def test_list_after_create(gql_schema: tuple[Any, SQLiteAdapter]) -> None:
    schema, adapter = gql_schema
    await schema.execute('mutation { create_items(input: { name: "Alpha" }) { id } }')
    result = await schema.execute("query { itemss { id name } }")
    assert result.errors is None
    assert result.data is not None
    assert result.data is not None
    names = [r["name"] for r in result.data["itemss"]]
    assert "Alpha" in names


@pytest.mark.asyncio
async def test_update_mutation(gql_schema: tuple[Any, SQLiteAdapter]) -> None:
    schema, adapter = gql_schema
    create_res = await schema.execute('mutation { create_items(input: { name: "Beta" }) { id } }')
    assert create_res.data is not None
    item_id = create_res.data["create_items"]["id"]

    update_res = await schema.execute(
        f'mutation {{ update_items(id: {item_id}, input: {{ name: "Beta Updated" }}) {{ id name }} }}'
    )
    assert update_res.errors is None, update_res.errors
    assert update_res.data["update_items"]["name"] == "Beta Updated"


@pytest.mark.asyncio
async def test_delete_mutation(gql_schema: tuple[Any, SQLiteAdapter]) -> None:
    schema, adapter = gql_schema
    create_res = await schema.execute(
        'mutation { create_items(input: { name: "ToDelete" }) { id } }'
    )
    assert create_res.data is not None
    item_id = create_res.data["create_items"]["id"]

    del_res = await schema.execute(f"mutation {{ delete_items(id: {item_id}) {{ id }} }}")
    assert del_res.errors is None, del_res.errors

    list_res = await schema.execute("query { itemss { id } }")
    assert list_res.data is not None
    ids = [r["id"] for r in list_res.data["itemss"]]
    assert item_id not in ids


# ---------------------------------------------------------------------------
# Soft-delete test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_filter_applied(sqlite_schema: SQLiteAdapter) -> None:
    """List query must automatically append WHERE deleted_at IS NULL for tables
    that have a deleted_at column.  This is enforced without any explicit filter
    from the caller — the resolver detects the field in the IR."""
    inspector = sqlite_schema.inspector()
    db_schema = await inspector.discover_schema()

    ir_types = IRBuilder(type_mapper=sqlite_schema.type_mapper()).build(db_schema, GatewayConfig())
    schema = GraphQLSchemaBuilder(db_adapter=sqlite_schema).build(ir_types=ir_types)

    # Create two articles: one visible, one soft-deleted
    conn = sqlite_schema._conn
    assert conn is not None
    await conn.execute("INSERT INTO articles (title, deleted_at) VALUES ('Live', NULL)")
    await conn.execute("INSERT INTO articles (title, deleted_at) VALUES ('Dead', '2024-01-01')")
    await conn.commit()

    result = await schema.execute("query { articless { id title } }")
    assert result.errors is None, result.errors
    assert result.data is not None
    assert result.data is not None
    titles = [r["title"] for r in result.data["articless"]]
    assert "Live" in titles
    assert "Dead" not in titles, "Soft-deleted article must not appear in list"


# ---------------------------------------------------------------------------
# Optimistic locking test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optimistic_locking_conflict(sqlite_schema: SQLiteAdapter) -> None:
    """An update with wrong expected_version must raise a GraphQL concurrency error."""
    inspector = sqlite_schema.inspector()
    db_schema = await inspector.discover_schema()

    ir_types = IRBuilder(type_mapper=sqlite_schema.type_mapper()).build(db_schema, GatewayConfig())
    schema = GraphQLSchemaBuilder(db_adapter=sqlite_schema).build(ir_types=ir_types)

    # Create a task (version=0 must be supplied because version is NOT NULL in schema)
    create_res = await schema.execute(
        'mutation { create_tasks(input: { summary: "Do work", version: 0 }) { id version } }'
    )
    assert create_res.errors is None, create_res.errors
    assert create_res.data is not None
    task_id = create_res.data["create_tasks"]["id"]

    # First update with correct expected_version=0 → should succeed
    ok_res = await schema.execute(
        f'mutation {{ update_tasks(id: {task_id}, input: {{ summary: "Done" }}, expected_version: 0) '
        f"{{ id version }} }}"
    )
    assert ok_res.errors is None, ok_res.errors

    # Second update with stale expected_version=0 again → should fail
    fail_res = await schema.execute(
        f'mutation {{ update_tasks(id: {task_id}, input: {{ summary: "Redo" }}, expected_version: 0) '
        f"{{ id }} }}"
    )
    assert fail_res.errors is not None
    assert "Optimistic concurrency failure" in fail_res.errors[0].message


# ---------------------------------------------------------------------------
# Zero-memory-filtering / auth predicate pushdown test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_predicate_pushed_to_sql(sqlite_schema: SQLiteAdapter) -> None:
    """Authorization policy must compile into SQL WHERE clause, not applied in Python.

    The test verifies that a user with owner_id=1 cannot see items owned by owner_id=2,
    and that the SQL compiler emits ? placeholders (not Postgres $N style).
    """
    inspector = sqlite_schema.inspector()
    db_schema = await inspector.discover_schema()

    # Set up authorization: only show items where owner_id matches current user
    auth_engine = AuthorizationEngine(
        policies=[
            TablePolicy(
                table="items",
                read_rules=[PolicyRule(column="owner_id", op="eq", value_template="$user_id")],
            )
        ]
    )

    ir_types = IRBuilder(type_mapper=sqlite_schema.type_mapper()).build(db_schema, GatewayConfig())
    schema = GraphQLSchemaBuilder(db_adapter=sqlite_schema, auth_engine=auth_engine).build(
        ir_types=ir_types
    )

    # Insert items owned by two different users
    conn = sqlite_schema._conn
    assert conn is not None
    await conn.execute("INSERT INTO items (name, owner_id) VALUES ('My Item', 1)")
    await conn.execute("INSERT INTO items (name, owner_id) VALUES ('Their Item', 2)")
    await conn.commit()

    # Query as user_id=1 — should only see 'My Item'
    auth_ctx_user1 = AuthContext(
        is_authenticated=True,
        user_id="1",
        roles=[],
        claims={},
    )
    result = await schema.execute(
        "query { itemss { id name owner_id } }",
        context_value={"auth_context": auth_ctx_user1},
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    assert result.data is not None
    names = [r["name"] for r in result.data["itemss"]]
    assert "My Item" in names
    assert (
        "Their Item" not in names
    ), "Zero-memory-filtering violated: unauthorized item must not appear in result"

    # Confirm the compiled SQL uses ? placeholders, not $N
    from db_graphql_gateway.database.adapters.interfaces import FilterCondition, QueryPlan, TableRef

    compiler = sqlite_schema.compiler()
    plan = QueryPlan(
        table=TableRef(schema="main", name="items"),
        filter_tree=FilterCondition(column="owner_id", op="eq", value="1"),
    )
    cq = compiler.compile(plan)
    assert "?" in cq.sql
    assert "$" not in cq.sql
