from typing import Any, AsyncGenerator
import pytest
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer

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
        await conn.execute("DROP TABLE IF EXISTS products;")
        await conn.execute(
            """
            CREATE TABLE products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                price NUMERIC(10, 2) NOT NULL,
                in_stock BOOLEAN NOT NULL DEFAULT true
            );
            """
        )
        await conn.execute(
            """
            INSERT INTO products (name, price, in_stock) VALUES
            ('Keyboard', 49.99, true),
            ('Mouse', 19.99, true),
            ('Monitor', 199.99, false),
            ('Laptop', 999.99, true),
            ('Desk Lamp', 25.50, false);
            """
        )

    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_filtering_and_sorting(pg_adapter_with_data: Any) -> None:
    inspector = PostgresSchemaInspector(pg_adapter_with_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_with_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_with_data)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    # Test filtering with eq & ordering
    query_eq = """
    query {
        productss(where: { in_stock: { eq: true } }, order_by: [{ price: DESC }]) {
            id
            name
            price
            in_stock
        }
    }
    """
    res = await schema.execute(query_eq)
    assert res.errors is None, f"Query errors: {res.errors}"
    assert res.data is not None
    products = (res.data or {})["productss"]
    assert len(products) == 3
    assert products[0]["name"] == "Laptop"
    assert products[1]["name"] == "Keyboard"
    assert products[2]["name"] == "Mouse"

    # Test gt filter
    query_gt = """
    query {
        productss(where: { price: { gt: 50.0 } }) {
            name
            price
        }
    }
    """
    res_gt = await schema.execute(query_gt)
    assert res_gt.errors is None
    assert res_gt.data is not None
    assert len(res_gt.data["productss"]) == 2

    # Test ilike filter
    query_ilike = """
    query {
        productss(where: { name: { ilike: "%mo%" } }) {
            name
        }
    }
    """
    res_ilike = await schema.execute(query_ilike)
    assert res_ilike.errors is None
    assert res_ilike.data is not None
    names = [p["name"] for p in res_ilike.data["productss"]]
    assert "Mouse" in names
    assert "Monitor" in names


@pytest.mark.asyncio
async def test_pagination_and_max_page_size(pg_adapter_with_data: Any) -> None:
    inspector = PostgresSchemaInspector(pg_adapter_with_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_with_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_with_data, max_page_size=2)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    # Offset & limit capped by max_page_size=2
    query_list = """
    query {
        productss(limit: 10, offset: 1, order_by: [{ id: ASC }]) {
            id
            name
        }
    }
    """
    res = await schema.execute(query_list)
    assert res.errors is None, f"Query errors: {res.errors}"
    # Capped at max_page_size=2
    assert len((res.data or {})["productss"]) == 2
    assert (res.data or {})["productss"][0]["name"] == "Mouse"
    assert (res.data or {})["productss"][1]["name"] == "Monitor"

    # Cursor-based Relay Connection pagination
    query_conn_1 = """
    query {
        productss_connection(first: 2, order_by: [{ id: ASC }]) {
            edges {
                node {
                    name
                }
                cursor
            }
            page_info {
                has_next_page
                has_previous_page
                start_cursor
                end_cursor
            }
        }
    }
    """
    res_conn_1 = await schema.execute(query_conn_1)
    assert res_conn_1.errors is None, f"Query errors: {res_conn_1.errors}"
    assert res_conn_1.data is not None
    conn_data = res_conn_1.data["productss_connection"]
    assert len(conn_data["edges"]) == 2
    assert conn_data["edges"][0]["node"]["name"] == "Keyboard"
    assert conn_data["edges"][1]["node"]["name"] == "Mouse"
    assert conn_data["page_info"]["has_next_page"] is True
    assert conn_data["page_info"]["has_previous_page"] is False

    end_cursor = conn_data["page_info"]["end_cursor"]

    # Fetch next page using after cursor (after 2 items -> offset 2)
    query_conn_2 = f"""
    query {{
        productss_connection(first: 2, after: "{end_cursor}", order_by: [{{ id: ASC }}]) {{
            edges {{
                node {{
                    name
                }}
                cursor
            }}
            page_info {{
                has_next_page
                has_previous_page
            }}
        }}
    }}
    """
    res_conn_2 = await schema.execute(query_conn_2)
    assert res_conn_2.errors is None, f"Query errors: {res_conn_2.errors}"
    assert res_conn_2.data is not None
    conn_data_2 = res_conn_2.data["productss_connection"]
    assert len(conn_data_2["edges"]) == 2
    assert conn_data_2["edges"][0]["node"]["name"] == "Monitor"
    assert conn_data_2["edges"][1]["node"]["name"] == "Laptop"
    assert conn_data_2["page_info"]["has_previous_page"] is True
