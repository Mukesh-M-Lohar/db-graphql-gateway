"""Security hardening tests.

Originally these tests used PostgresAdapter + testcontainers.  They are
refactored to use SQLiteAdapter with an in-memory database, so no Docker
container or asyncpg installation is required.

The security rules (max depth, max aliases, complexity, introspection
lockdown) are GraphQL-layer rules that operate entirely on the query
document.  They are completely independent of the underlying database
adapter, so SQLite is a perfect fit for this test suite.
"""

from typing import Any

import pytest
import pytest_asyncio
import strawberry

from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder
from db_graphql_gateway.security.error_masking import mask_error_in_production
from db_graphql_gateway.security.validation import create_max_aliases_rule, create_max_depth_rule


@pytest_asyncio.fixture
async def sqlite_sec_adapter() -> Any:
    """In-memory SQLite adapter with a minimal schema for security tests."""
    adapter = SQLiteAdapter(":memory:")
    await adapter.connect()

    conn = adapter._conn
    assert conn is not None
    await conn.execute(
        """
        CREATE TABLE items (
            id   INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
    )
    await conn.execute("INSERT INTO items (name) VALUES ('Item 1')")
    await conn.commit()

    yield adapter
    await adapter.close()


@pytest_asyncio.fixture
async def sqlite_gql_schema(sqlite_sec_adapter: SQLiteAdapter) -> Any:
    """Convenience fixture: fully built Strawberry schema from SQLite adapter."""
    inspector = sqlite_sec_adapter.inspector()
    db_schema = await inspector.discover_schema()
    config = GatewayConfig()
    ir_types = IRBuilder(type_mapper=sqlite_sec_adapter.type_mapper()).build(db_schema, config)
    return sqlite_sec_adapter, db_schema, ir_types


@pytest.mark.asyncio
async def test_max_depth_rule_rejection(sqlite_gql_schema: Any) -> None:
    adapter, db_schema, ir_types = sqlite_gql_schema

    def depth_extension() -> Any:
        return strawberry.extensions.AddValidationRules([create_max_depth_rule(max_depth=1)])

    builder = GraphQLSchemaBuilder(db_adapter=adapter)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema, extensions=[depth_extension])

    deep_query = """
    query {
        itemss {
            id
            name
        }
    }
    """

    res = await schema.execute(deep_query)
    assert res.errors is not None
    assert "exceeds maximum depth of 1" in res.errors[0].message


@pytest.mark.asyncio
async def test_max_aliases_rule_rejection(sqlite_gql_schema: Any) -> None:
    adapter, db_schema, ir_types = sqlite_gql_schema

    def alias_extension() -> Any:
        return strawberry.extensions.AddValidationRules([create_max_aliases_rule(max_aliases=1)])

    builder = GraphQLSchemaBuilder(db_adapter=adapter)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema, extensions=[alias_extension])

    many_aliases_query = """
    query {
        a1: itemss { id }
        a2: itemss { id }
    }
    """

    res = await schema.execute(many_aliases_query)
    assert res.errors is not None
    assert "exceeds maximum alias limit of 1" in res.errors[0].message


@pytest.mark.asyncio
async def test_error_masking_in_production() -> None:
    """Error masking must strip internal DB details regardless of which driver raised the error."""
    from graphql import GraphQLError

    # Simulate a database error message — deliberately generic (not driver-specific)
    raw_error = GraphQLError("An internal database error occurred: syntax error near 'secret'")

    # Debug = True → returns unmasked message
    unmasked = mask_error_in_production(raw_error, debug=True)
    assert "syntax error" in unmasked["message"]

    # Debug = False → masks internal DB error
    masked = mask_error_in_production(raw_error, debug=False)
    assert masked["message"] == "Internal server error"
    assert "syntax error" not in masked["message"]


@pytest.mark.asyncio
async def test_max_complexity_rule_rejection(sqlite_gql_schema: Any) -> None:
    from db_graphql_gateway.security.complexity import create_max_complexity_rule

    adapter, db_schema, ir_types = sqlite_gql_schema

    def complexity_extension() -> Any:
        # A simple query `itemss { id name }` has complexity 2.
        # Setting max to 1 should reject it.
        return strawberry.extensions.AddValidationRules(
            [create_max_complexity_rule(max_complexity=1)]
        )

    builder = GraphQLSchemaBuilder(db_adapter=adapter)
    schema = builder.build(
        ir_types=ir_types, db_schema=db_schema, extensions=[complexity_extension]
    )

    query = """
    query {
        itemss {
            id
            name
        }
    }
    """

    res = await schema.execute(query)
    assert res.errors is not None
    assert "exceeds maximum complexity" in res.errors[0].message


@pytest.mark.asyncio
async def test_introspection_lockdown_rule_rejection(sqlite_gql_schema: Any) -> None:
    from db_graphql_gateway.security.validation import create_introspection_lockdown_rule

    adapter, db_schema, ir_types = sqlite_gql_schema

    def lockdown_extension() -> Any:
        return strawberry.extensions.AddValidationRules([create_introspection_lockdown_rule()])

    builder = GraphQLSchemaBuilder(db_adapter=adapter)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema, extensions=[lockdown_extension])

    query = """
    query {
        __schema {
            types {
                name
            }
        }
    }
    """

    res = await schema.execute(query)
    assert res.errors is not None
    assert "Introspection queries are disabled" in res.errors[0].message
