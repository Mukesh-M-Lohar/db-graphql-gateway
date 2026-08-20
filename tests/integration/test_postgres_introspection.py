import asyncpg
import pytest

from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.database.models.schema import Table, View


@pytest.mark.asyncio
async def test_postgres_introspection_discovers_tables_and_views(db_pool: asyncpg.Pool) -> None:
    inspector = PostgresSchemaInspector(db_pool, schemas=["public"])

    schema = await inspector.discover_schema()

    assert "public" in schema.namespaces
    public_ns = schema.namespaces["public"]

    # Check tables
    assert "users" in public_ns.tables
    assert isinstance(public_ns.tables["users"], Table)

    assert "posts" in public_ns.tables
    assert isinstance(public_ns.tables["posts"], Table)

    # Check views
    assert "published_posts" in public_ns.views
    assert isinstance(public_ns.views["published_posts"], View)
    assert public_ns.views["published_posts"].is_materialized is False


@pytest.mark.asyncio
async def test_postgres_introspection_discovers_columns(db_pool: asyncpg.Pool) -> None:
    inspector = PostgresSchemaInspector(db_pool, schemas=["public"])

    schema = await inspector.discover_schema()
    public_ns = schema.namespaces["public"]

    users_table = public_ns.tables["users"]

    # id, username, created_at
    assert len(users_table.columns) == 3
    col_names = {c.name for c in users_table.columns}
    assert col_names == {"id", "username", "created_at"}

    # check specific column
    username_col = next(c for c in users_table.columns if c.name == "username")
    assert username_col.nullable is False
    assert "character varying" in username_col.type
