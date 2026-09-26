from typing import Any
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.graphql.dataloader import DataLoaderRegistry
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder


@pytest_asyncio.fixture
async def pg_adapter_m2m_data(postgres_container: Any) -> AsyncGenerator[Any, None]:
    url = postgres_container.get_connection_url().replace("postgresql+psycopg2", "postgresql")

    adapter = PostgresAdapter(url)
    await adapter.connect()

    assert adapter.pool is not None

    async with adapter.pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE posts (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL
            );

            CREATE TABLE tags (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) NOT NULL UNIQUE
            );

            CREATE TABLE post_tags (
                post_id INT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                tag_id INT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (post_id, tag_id)
            );
            """
        )
        await conn.execute(
            """
            INSERT INTO posts (title) VALUES
            ('Post 1'),
            ('Post 2'),
            ('Post 3');
            """
        )
        await conn.execute(
            """
            INSERT INTO tags (name) VALUES
            ('tagA'),
            ('tagB'),
            ('tagC');
            """
        )
        await conn.execute(
            """
            INSERT INTO post_tags (post_id, tag_id) VALUES
            (1, 1), -- Post 1 -> tagA
            (1, 2), -- Post 1 -> tagB
            (2, 2), -- Post 2 -> tagB
            (2, 3), -- Post 2 -> tagC
            (3, 1); -- Post 3 -> tagA
            """
        )

    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_many_to_many_dataloader(pg_adapter_m2m_data: Any) -> None:
    inspector = PostgresSchemaInspector(pg_adapter_m2m_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_m2m_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    # 2. Build GraphQL Schema
    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_m2m_data)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    # Note: `post_tags` should NOT be exposed as a top-level query because we hid it.
    # assert "post_tags" not in schema.get_type("Query").fields

    # Execute M2M query fetching posts and their tags
    context = {"dataloader_registry": DataLoaderRegistry(pg_adapter_m2m_data, {})}
    query = """
    query {
        posts(order_by: [{ id: ASC }]) {
            id
            title
            tags {
                id
                name
            }
        }
    }
    """

    res = await schema.execute(query, context_value=context)

    assert res.errors is None, f"Query errors: {res.errors}"
    assert res.data is not None

    posts = res.data["posts"]
    assert len(posts) == 3

    assert posts[0]["title"] == "Post 1"
    assert len(posts[0]["tags"]) == 2
    tag_names_1 = {t["name"] for t in posts[0]["tags"]}
    assert tag_names_1 == {"tagA", "tagB"}

    assert posts[1]["title"] == "Post 2"
    assert len(posts[1]["tags"]) == 2
    tag_names_2 = {t["name"] for t in posts[1]["tags"]}
    assert tag_names_2 == {"tagB", "tagC"}

    assert posts[2]["title"] == "Post 3"
    assert len(posts[2]["tags"]) == 1
    assert posts[2]["tags"][0]["name"] == "tagA"
