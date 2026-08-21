"""
Conformance Test Suite Fixtures
"""

import pytest
import pytest_asyncio
import sqlalchemy as sa
from typing import Any, AsyncGenerator, Generator

pytest.importorskip("testcontainers")
pytest.importorskip("asyncmy")
pytest.importorskip("asyncpg")

from testcontainers.community.mysql import MySqlContainer  # noqa: E402
from testcontainers.community.postgres import PostgresContainer  # noqa: E402

from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter  # noqa: E402
from db_graphql_gateway.database.adapters.mysql.adapter import MySQLAdapter  # noqa: E402
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter  # noqa: E402

from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder  # noqa: E402
from db_graphql_gateway.schema.config import GatewayConfig  # noqa: E402
from db_graphql_gateway.schema.ir.builder import IRBuilder  # noqa: E402
from db_graphql_gateway.auth.authorization import AuthorizationEngine  # noqa: E402

# ---------------------------------------------------------------------------
# Canonical Schema Definition
# ---------------------------------------------------------------------------

metadata = sa.MetaData()

authors = sa.Table(
    "authors",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(255), nullable=False),
)

books = sa.Table(
    "books",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("author_id", sa.Integer, sa.ForeignKey("authors.id")),
)

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("is_active", sa.Boolean, default=True),
    sa.Column("owner_id", sa.Integer),
    sa.Column("password", sa.String(255)),
    sa.Column("status", sa.Enum("active", "inactive", name="status_enum")),
)

tasks = sa.Table(
    "tasks",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("summary", sa.String(255), nullable=False),
    sa.Column("version", sa.Integer, nullable=False, default=0),
)

articles = sa.Table(
    "articles",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("title", sa.String(255), nullable=False),
    sa.Column("deleted_at", sa.DateTime(timezone=True)),
)


def get_ddl(engine: str) -> list[str]:
    from sqlalchemy.dialects import postgresql, mysql, sqlite

    if engine == "postgres":
        dialect = postgresql.dialect()
    elif engine == "mysql":
        dialect = mysql.dialect()
    else:
        dialect = sqlite.dialect()

    ddl_statements = []
    if engine == "postgres":
        ddl_statements.append("CREATE TYPE status_enum AS ENUM ('active', 'inactive');")

    for table in metadata.sorted_tables:
        create_stmt = sa.schema.CreateTable(table)
        ddl_statements.append(str(create_stmt.compile(dialect=dialect)).strip() + ";")
    return ddl_statements


# ---------------------------------------------------------------------------
# Dynamic Engine Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mysql_container() -> Generator[MySqlContainer, None, None]:
    with MySqlContainer("mysql:8.0") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer("postgres:15") as container:
        yield container


@pytest_asyncio.fixture(params=["sqlite", "mysql", "postgres"])
async def db_adapter(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[Any, None]:
    """Provides a fresh database adapter for the parameterized engine."""
    engine = request.param

    if engine == "sqlite":
        adapter = SQLiteAdapter(":memory:")
        await adapter.connect()
        conn = adapter._conn
        assert conn is not None
        for stmt in get_ddl("sqlite"):
            await conn.execute(stmt)
        await conn.commit()
        try:
            yield adapter
        finally:
            await adapter.close()

    elif engine == "mysql":
        mysql_container = request.getfixturevalue("mysql_container")
        host = mysql_container.get_container_host_ip()
        port = int(mysql_container.get_exposed_port(3306))
        mysql_adapter = MySQLAdapter(
            host=host,
            port=port,
            user=getattr(mysql_container, "username", "test"),
            password=getattr(mysql_container, "password", "test"),
            database=getattr(mysql_container, "dbname", "test"),
        )
        await mysql_adapter.connect()
        pool = mysql_adapter.pool
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                for table in reversed(metadata.sorted_tables):
                    await cur.execute(f"DROP TABLE IF EXISTS {table.name}")
                for stmt in get_ddl("mysql"):
                    await cur.execute(stmt)
            await conn.commit()
        try:
            yield mysql_adapter
        finally:
            await mysql_adapter.close()

    elif engine == "postgres":
        postgres_container = request.getfixturevalue("postgres_container")
        host = postgres_container.get_container_host_ip()
        port = postgres_container.get_exposed_port(5432)
        user = getattr(postgres_container, "username", "test")
        pwd = getattr(postgres_container, "password", "test")
        db = getattr(postgres_container, "dbname", "test")
        dsn = f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
        pg_adapter = PostgresAdapter(dsn=dsn)
        await pg_adapter.connect()
        pg_pool = pg_adapter.pool
        assert pg_pool is not None
        async with pg_pool.acquire() as conn:
            for table in reversed(metadata.sorted_tables):
                await conn.execute(f"DROP TABLE IF EXISTS {table.name} CASCADE")
                await conn.execute("DROP TYPE IF EXISTS status_enum CASCADE")
            for stmt in get_ddl("postgres"):
                await conn.execute(stmt)
        try:
            yield pg_adapter
        finally:
            await pg_adapter.close()

    else:
        raise ValueError(f"Unknown engine: {engine}")


@pytest_asyncio.fixture
async def gql_schema(db_adapter: Any, auth_engine: AuthorizationEngine) -> tuple[Any, Any]:
    """Build a Strawberry GraphQL schema from the conformance adapter."""
    inspector = db_adapter.inspector()
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=db_adapter.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    builder = GraphQLSchemaBuilder(db_adapter=db_adapter, auth_engine=auth_engine)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)
    return schema, db_adapter


# Expose authorization engine fixture for testing policy pushdowns
@pytest.fixture
def auth_engine() -> AuthorizationEngine:
    return AuthorizationEngine()


@pytest.fixture
def run_sql() -> Any:
    async def _run_sql(adapter: Any, sql: str) -> None:
        """Helper to execute raw DML across adapters for test setup."""
        await adapter.execute_raw_dml(sql)

    return _run_sql
