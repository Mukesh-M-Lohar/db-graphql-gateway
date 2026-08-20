from typing import Any, AsyncGenerator
import pytest
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer

from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.graphql.dataloader import DataLoaderRegistry
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder


@pytest.fixture(scope="module")
def postgres_container() -> Any:
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture
async def pg_adapter_rel_data(postgres_container: Any) -> AsyncGenerator[Any, None]:
    connection_url = postgres_container.get_connection_url(driver=None)
    adapter = PostgresAdapter(dsn=connection_url)
    await adapter.connect()

    assert adapter.pool
    async with adapter.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS posts CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS authors CASCADE;")
        await conn.execute(
            """
            CREATE TABLE authors (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE posts (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                author_id INT NOT NULL REFERENCES authors(id)
            );
            """
        )

        await conn.execute(
            """
            INSERT INTO authors (name) VALUES
            ('Alice'),
            ('Bob');
            """
        )
        await conn.execute(
            """
            INSERT INTO posts (title, author_id) VALUES
            ('Alice Post 1', 1),
            ('Alice Post 2', 1),
            ('Alice Post 3', 1),
            ('Bob Post 1', 2),
            ('Bob Post 2', 2);
            """
        )

    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_relationship_dataloader_batching(pg_adapter_rel_data: Any) -> None:
    # 1. Inspector & IR
    inspector = PostgresSchemaInspector(pg_adapter_rel_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_rel_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    # 2. Build GraphQL Schema
    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_rel_data)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    # 3. Track executed SQL queries to prove DataLoader O(1) batching
    executed_queries: list[str] = []
    original_execute = pg_adapter_rel_data.execute

    async def tracking_execute(compiled_query):
        executed_queries.append(compiled_query.sql)
        return await original_execute(compiled_query)

    pg_adapter_rel_data.execute = tracking_execute

    # 4. Execute nested 1:N relationship query fetching authors and their posts with request-scoped context
    context = {"dataloader_registry": DataLoaderRegistry(pg_adapter_rel_data)}
    query = """
    query {
        authorss {
            id
            name
            postss {
                id
                title
            }
        }
    }
    """

    res = await schema.execute(query, context_value=context)

    assert res.errors is None, f"Query errors: {res.errors}"
    assert res.data is not None

    authors = res.data["authorss"]
    assert len(authors) == 2

    alice = next(a for a in authors if a["name"] == "Alice")
    bob = next(a for a in authors if a["name"] == "Bob")

    assert len(alice["postss"]) == 3
    assert len(bob["postss"]) == 2

    # 5. VERIFY Empirical DataLoader Proof:
    # Query 1: SELECT * FROM "public"."authors"
    # Query 2: SELECT * FROM "public"."posts" WHERE "author_id" IN ($1, $2)
    # Total queries MUST be exactly 2 (O(1) per level), avoiding N+1 (1 + 2 = 3 queries)
    assert (
        len(executed_queries) == 2
    ), f"Expected 2 queries, got {len(executed_queries)}: {executed_queries}"
    assert "IN (" in executed_queries[1]
    assert executed_queries[1].count("$") == 2
