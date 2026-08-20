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
async def pg_adapter_qp_data(postgres_container: Any) -> AsyncGenerator[Any, None]:
    connection_url = postgres_container.get_connection_url(driver=None)
    adapter = PostgresAdapter(dsn=connection_url)
    await adapter.connect()

    assert adapter.pool
    async with adapter.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS employees;")
        await conn.execute(
            """
            CREATE TABLE employees (
                id SERIAL PRIMARY KEY,
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL,
                salary NUMERIC(10, 2) NOT NULL
            );
            """
        )
        await conn.execute(
            """
            INSERT INTO employees (first_name, last_name, email, salary) VALUES
            ('John', 'Doe', 'john@example.com', 75000.00),
            ('Jane', 'Smith', 'jane@example.com', 85000.00);
            """
        )

    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_query_planner_selective_columns(pg_adapter_qp_data: Any) -> None:
    # 1. Inspect schema & build IR
    inspector = PostgresSchemaInspector(pg_adapter_qp_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_qp_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    # 2. Build GraphQL Schema
    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_qp_data)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    # 3. Intercept executed SQL queries
    executed_queries: list[str] = []
    original_execute = pg_adapter_qp_data.execute

    async def tracking_execute(compiled_query):
        executed_queries.append(compiled_query.sql)
        return await original_execute(compiled_query)

    pg_adapter_qp_data.execute = tracking_execute

    # 4. Query only first_name and email (leaving last_name and salary unrequested)
    query = """
    query {
        employeess {
            first_name
            email
        }
    }
    """

    res = await schema.execute(query)

    assert res.errors is None, f"Query errors: {res.errors}"
    assert res.data is not None
    employees = res.data["employeess"]
    assert len(employees) == 2
    assert employees[0]["first_name"] == "John"
    assert employees[0]["email"] == "john@example.com"

    # 5. Verify SQL compiler generated targeted column selection instead of SELECT *
    assert len(executed_queries) == 1
    sql = executed_queries[0]
    assert "SELECT *" not in sql
    assert '"first_name"' in sql
    assert '"email"' in sql
    assert '"salary"' not in sql
