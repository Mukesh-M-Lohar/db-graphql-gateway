from typing import Any, AsyncGenerator
import pytest
import pytest_asyncio
import strawberry
from testcontainers.community.postgres import PostgresContainer

from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.security.error_masking import mask_error_in_production
from db_graphql_gateway.security.validation import create_max_aliases_rule, create_max_depth_rule
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder


@pytest.fixture(scope="module")
def postgres_container() -> Any:
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture
async def pg_adapter_sec_data(postgres_container: Any) -> AsyncGenerator[Any, None]:
    connection_url = postgres_container.get_connection_url(driver=None)
    adapter = PostgresAdapter(dsn=connection_url)
    await adapter.connect()

    assert adapter.pool
    async with adapter.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS items;")
        await conn.execute(
            """
            CREATE TABLE items (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            );
            """
        )
        await conn.execute("INSERT INTO items (name) VALUES ('Item 1');")

    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_max_depth_rule_rejection(pg_adapter_sec_data: Any) -> None:
    inspector = PostgresSchemaInspector(pg_adapter_sec_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_sec_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    def depth_extension() -> Any:
        return strawberry.extensions.AddValidationRules([create_max_depth_rule(max_depth=1)])

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_sec_data)
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
async def test_max_aliases_rule_rejection(pg_adapter_sec_data: Any) -> None:
    inspector = PostgresSchemaInspector(pg_adapter_sec_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_sec_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    def alias_extension() -> Any:
        return strawberry.extensions.AddValidationRules([create_max_aliases_rule(max_aliases=1)])

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_sec_data)
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
    from graphql import GraphQLError

    raw_error = GraphQLError(
        "asyncpg.exceptions.PostgresSyntaxError: column 'secret' does not exist"
    )

    # Debug = True -> returns unmasked message
    unmasked = mask_error_in_production(raw_error, debug=True)
    assert "PostgresSyntaxError" in unmasked["message"]

    # Debug = False -> masks internal DB error
    masked = mask_error_in_production(raw_error, debug=False)
    assert masked["message"] == "Internal server error"
    assert "PostgresSyntaxError" not in masked["message"]


@pytest.mark.asyncio
async def test_max_complexity_rule_rejection(pg_adapter_sec_data: Any) -> None:
    from db_graphql_gateway.security.complexity import create_max_complexity_rule

    inspector = PostgresSchemaInspector(pg_adapter_sec_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_sec_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    def complexity_extension() -> Any:
        # A simple query `itemss { id name }` has complexity 2. Setting max to 1 should reject it.
        return strawberry.extensions.AddValidationRules(
            [create_max_complexity_rule(max_complexity=1)]
        )

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_sec_data)
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
async def test_introspection_lockdown_rule_rejection(pg_adapter_sec_data: Any) -> None:
    from db_graphql_gateway.security.validation import create_introspection_lockdown_rule

    inspector = PostgresSchemaInspector(pg_adapter_sec_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_sec_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    def lockdown_extension() -> Any:
        return strawberry.extensions.AddValidationRules([create_introspection_lockdown_rule()])

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_sec_data)
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
