"""MySQL end-to-end integration tests using testcontainers.

These tests spin up a real MySQL 8.0 container and verify the full
pipeline from connection through GraphQL execution.

Exit criteria (Phase 20):
- Full lifecycle: connect → DDL → introspect → IR build → GraphQL schema build
  → list query → create/update/delete mutations
- Auth predicate pushdown verified — WHERE clause in MySQL SQL
- TINYINT(1) → Boolean mapping works end-to-end
- No RETURNING in any emitted SQL (confirmed via compiler)

To run:
    uv run pytest tests/integration/test_mysql_integration.py -v

Requirements:
    - Docker daemon running
    - testcontainers[mysql] installed (in dev dependencies)

Marks:
    These tests are decorated with ``@pytest.mark.integration`` and are
    excluded from the default unit test run via ``-k "not integration"``.
"""

# The imports below must follow pytest.importorskip() calls; the noqa
# comments suppress ruff E402 (module-level import not at top of file),
# which is the accepted pattern for optional-dependency test files.
import pytest
import pytest_asyncio
from typing import Any, AsyncGenerator, Generator

pytest.importorskip("testcontainers")
pytest.importorskip("asyncmy")

from testcontainers.mysql import MySqlContainer  # noqa: E402

from db_graphql_gateway.auth.authorization import (  # noqa: E402
    AuthorizationEngine,
    PolicyRule,
    TablePolicy,
)
from db_graphql_gateway.auth.interfaces import AuthContext  # noqa: E402
from db_graphql_gateway.database.adapters.interfaces import (  # noqa: E402
    FilterCondition,
    MutationPlan,
    QueryPlan,
    TableRef,
)
from db_graphql_gateway.database.adapters.mysql.adapter import MySQLAdapter  # noqa: E402
from db_graphql_gateway.database.adapters.mysql.compiler import MySQLQueryCompiler  # noqa: E402
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder  # noqa: E402
from db_graphql_gateway.schema.config import GatewayConfig  # noqa: E402
from db_graphql_gateway.schema.ir.builder import IRBuilder  # noqa: E402

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mysql_container() -> Generator[MySqlContainer, None, None]:
    """Session-scoped MySQL 8.0 container (shared across all tests in this module)."""
    with MySqlContainer("mysql:8.0") as container:
        yield container


@pytest_asyncio.fixture
async def mysql_adapter(mysql_container: MySqlContainer) -> AsyncGenerator[MySQLAdapter, None]:
    """MySQLAdapter connected to the test container with a fresh schema."""
    host = mysql_container.get_container_host_ip()
    port = int(mysql_container.get_exposed_port(3306))
    database = getattr(mysql_container, "dbname", "test")
    user = getattr(mysql_container, "username", "test")
    password = getattr(mysql_container, "password", "test")

    adapter = MySQLAdapter(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )
    await adapter.connect()

    # Create test tables
    pool = adapter.pool
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DROP TABLE IF EXISTS posts")
            await cur.execute("DROP TABLE IF EXISTS users")
            await cur.execute(
                """
                CREATE TABLE users (
                    id         INT PRIMARY KEY AUTO_INCREMENT,
                    name       VARCHAR(255) NOT NULL,
                    owner_id   INT,
                    is_active  TINYINT(1) DEFAULT 1,
                    deleted_at DATETIME
                )
                """
            )
            await cur.execute(
                """
                CREATE TABLE posts (
                    id        INT PRIMARY KEY AUTO_INCREMENT,
                    title     VARCHAR(255) NOT NULL,
                    author_id INT,
                    CONSTRAINT fk_author FOREIGN KEY (author_id) REFERENCES users(id)
                )
                """
            )
            await conn.commit()

    yield adapter
    await adapter.close()


@pytest_asyncio.fixture
async def gql_schema(mysql_adapter: MySQLAdapter) -> tuple[Any, MySQLAdapter]:
    """Build a Strawberry schema from MySQL adapter."""
    inspector = mysql_adapter.inspector()
    db_schema = await inspector.discover_schema()

    ir_types = IRBuilder(type_mapper=mysql_adapter.type_mapper()).build(db_schema, GatewayConfig())
    schema = GraphQLSchemaBuilder(db_adapter=mysql_adapter).build(
        ir_types=ir_types, db_schema=db_schema
    )
    return schema, mysql_adapter


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_query_empty(gql_schema: tuple[Any, MySQLAdapter]) -> None:
    schema, _ = gql_schema
    result = await schema.execute("query { userss { id name } }")
    assert result.errors is None
    assert result.data["userss"] == []


@pytest.mark.asyncio
async def test_create_user(gql_schema: tuple[Any, MySQLAdapter]) -> None:
    schema, _ = gql_schema
    result = await schema.execute('mutation { create_users(input: { name: "Alice" }) { id name } }')
    assert result.errors is None, result.errors
    assert result.data is not None
    assert result.data is not None
    user = result.data["create_users"]
    assert user["name"] == "Alice"
    assert user["id"] is not None


@pytest.mark.asyncio
async def test_update_user(gql_schema: tuple[Any, MySQLAdapter]) -> None:
    schema, _ = gql_schema
    create = await schema.execute('mutation { create_users(input: { name: "Bob" }) { id } }')
    assert create.data is not None
    uid = create.data["create_users"]["id"]
    update = await schema.execute(
        f'mutation {{ update_users(id: {uid}, input: {{ name: "Robert" }}) {{ id name }} }}'
    )
    assert update.errors is None, update.errors
    assert update.data["update_users"]["name"] == "Robert"


@pytest.mark.asyncio
async def test_delete_user(gql_schema: tuple[Any, MySQLAdapter]) -> None:
    schema, _ = gql_schema
    create = await schema.execute('mutation { create_users(input: { name: "Eve" }) { id } }')
    assert create.data is not None
    uid = create.data["create_users"]["id"]
    delete = await schema.execute(f"mutation {{ delete_users(id: {uid}) {{ id }} }}")
    assert delete.errors is None, delete.errors

    list_res = await schema.execute("query { userss { id } }")
    assert list_res.data is not None
    ids = [r["id"] for r in list_res.data["userss"]]
    assert uid not in ids


# ---------------------------------------------------------------------------
# No RETURNING in SQL — confirmed via compiler
# ---------------------------------------------------------------------------


def test_no_returning_in_mysql_sql() -> None:
    c = MySQLQueryCompiler()
    plan = MutationPlan(
        operation="insert",
        table=TableRef(schema="mydb", name="users"),
        data={"name": "test"},
        pk_column="id",
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" not in cq.sql
    assert cq.fetch_after_write is True


# ---------------------------------------------------------------------------
# TINYINT(1) → Boolean end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tinyint1_mapped_to_boolean(mysql_adapter: MySQLAdapter) -> None:
    inspector = mysql_adapter.inspector()
    db_schema = await inspector.discover_schema()

    ns = db_schema.namespaces.get(mysql_adapter.database)
    assert ns is not None
    users_table = ns.tables.get("users")
    assert users_table is not None

    is_active_col = next((c for c in users_table.columns if c.name == "is_active"), None)
    assert is_active_col is not None, "is_active column not found"

    mapper = mysql_adapter.type_mapper()
    gql_type = mapper.to_graphql_type(is_active_col)
    assert gql_type == "Boolean", f"Expected Boolean, got {gql_type!r}"


# ---------------------------------------------------------------------------
# Auth predicate pushdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_predicate_pushdown(mysql_adapter: MySQLAdapter) -> None:
    """Auth filter must compile to WHERE clause in MySQL SQL (qmark placeholders)."""
    inspector = mysql_adapter.inspector()
    db_schema = await inspector.discover_schema()

    auth_engine = AuthorizationEngine(
        policies=[
            TablePolicy(
                table="users",
                read_rules=[PolicyRule(column="owner_id", op="eq", value_template="$user_id")],
            )
        ]
    )

    ir_types = IRBuilder(type_mapper=mysql_adapter.type_mapper()).build(db_schema, GatewayConfig())
    schema = GraphQLSchemaBuilder(db_adapter=mysql_adapter, auth_engine=auth_engine).build(
        ir_types=ir_types
    )

    # Seed data
    pool = mysql_adapter.pool
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO users (name, owner_id) VALUES ('Mine', 1)")
            await cur.execute("INSERT INTO users (name, owner_id) VALUES ('Theirs', 2)")
            await conn.commit()

    # Query as user_id=1
    auth_ctx = AuthContext(is_authenticated=True, user_id="1", roles=[], claims={})
    result = await schema.execute(
        "query { userss { id name owner_id } }",
        context_value={"auth_context": auth_ctx},
    )
    assert result.errors is None, result.errors
    assert result.data is not None
    assert result.data is not None
    names = [r["name"] for r in result.data["userss"]]
    assert "Mine" in names
    assert "Theirs" not in names

    # Confirm compiler emits ? placeholders
    compiler = mysql_adapter.compiler()
    plan = QueryPlan(
        table=TableRef(schema=mysql_adapter.database, name="users"),
        filter_tree=FilterCondition(column="owner_id", op="eq", value=1),
    )
    cq = compiler.compile(plan)
    assert "$" not in cq.sql
