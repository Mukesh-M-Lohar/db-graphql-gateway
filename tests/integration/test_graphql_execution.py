import asyncpg
import pytest

from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder


@pytest.mark.asyncio
async def test_graphql_execution_end_to_end(db_pool: asyncpg.Pool) -> None:
    # 1. Database Adapter setup
    adapter = PostgresAdapter(
        dsn=""
    )  # DSN not needed since we already have the pool in the test, wait
    adapter.pool = db_pool  # inject the pool manually for testing

    # 2. Introspection
    inspector = PostgresSchemaInspector(db_pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    # 3. Insert some test data directly
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (username) VALUES ('graphql_tester') ON CONFLICT DO NOTHING"
        )

    # 4. IR Generation
    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=adapter.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    # 5. GraphQL Schema Generation
    gql_builder = GraphQLSchemaBuilder(db_adapter=adapter)
    schema = gql_builder.build(ir_types)

    # 6. Execute!
    query = """
        query {
            userss {
                username
            }
        }
    """

    result = await schema.execute(query)

    assert result.errors is None
    assert result.data is not None
    assert "userss" in result.data

    users = result.data["userss"]
    assert len(users) >= 1
    assert any(u["username"] == "graphql_tester" for u in users)
