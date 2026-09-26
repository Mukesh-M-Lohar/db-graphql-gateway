import pytest
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer
from typing import Any, AsyncGenerator

from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder


@pytest.fixture(scope="module")
def postgres_container() -> Any:
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture
async def pg_adapter_with_data(postgres_container: Any) -> AsyncGenerator[Any, None]:
    connection_url = postgres_container.get_connection_url(driver=None)
    adapter = PostgresAdapter(dsn=connection_url)
    await adapter.connect()
    assert adapter.pool
    async with adapter.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS items CASCADE;")
        await conn.execute(
            "CREATE TABLE items (id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL);"
        )
        await conn.execute(
            "INSERT INTO items (name) VALUES ('A'), ('B'), ('C'), ('D'), ('E'), ('F');"
        )
    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_backward_pagination(pg_adapter_with_data: Any) -> None:
    inspector = PostgresSchemaInspector(pg_adapter_with_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()
    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_with_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)
    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_with_data)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    # 1. Forward fetch to get cursors
    res1 = await schema.execute(
        "query { items_connection(first: 6, order_by: [{ id: ASC }]) { edges { cursor node { id name } } page_info { has_next_page has_previous_page start_cursor end_cursor } } }"
    )
    assert res1.errors is None
    assert res1.data is not None
    edges = res1.data["items_connection"]["edges"]
    assert len(edges) == 6

    # 2. Backward fetch using `last: 2, before: cursor_of_D`
    # cursor of 'D' (id=4) is at index 3
    cursor_D = edges[3]["cursor"]
    res2 = await schema.execute(
        f'query {{ items_connection(last: 2, before: "{cursor_D}", order_by: [{{ id: ASC }}]) {{ edges {{ cursor node {{ id name }} }} page_info {{ has_next_page has_previous_page start_cursor end_cursor }} }} }}'
    )
    assert res2.errors is None
    assert res2.data is not None
    edges2 = res2.data["items_connection"]["edges"]
    assert len(edges2) == 2
    assert edges2[0]["node"]["name"] == "B"
    assert edges2[1]["node"]["name"] == "C"

    # check page_info
    page_info2 = res2.data["items_connection"]["page_info"]
    print("page_info2:", page_info2)
    assert page_info2["has_previous_page"] is True  # items A before B
    assert (
        page_info2["has_next_page"] is False
    )  # in backward pagination, has_next_page is typically false unless items after 'D' exist (wait, no. has_next_page means items AFTER 'C'. Since 'D' is the boundary, in standard Relay, has_next_page is false)
