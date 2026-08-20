from typing import Any, AsyncGenerator
import pytest
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer

from db_graphql_gateway.auth.authorization import AuthorizationEngine, PolicyRule, TablePolicy
from db_graphql_gateway.auth.interfaces import AuthContext
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
async def pg_adapter_auth_data(postgres_container: Any) -> AsyncGenerator[Any, None]:
    connection_url = postgres_container.get_connection_url(driver=None)
    adapter = PostgresAdapter(dsn=connection_url)
    await adapter.connect()

    assert adapter.pool
    async with adapter.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS projects;")
        await conn.execute(
            """
            CREATE TABLE projects (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                owner_id VARCHAR(50) NOT NULL
            );
            """
        )
        await conn.execute(
            """
            INSERT INTO projects (name, owner_id) VALUES
            ('Project A1', 'user_a'),
            ('Project A2', 'user_a'),
            ('Project B1', 'user_b');
            """
        )

    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_authorization_row_level_isolation(pg_adapter_auth_data: Any) -> None:
    # 1. Setup Inspector, IR, and Authorization Engine
    inspector = PostgresSchemaInspector(pg_adapter_auth_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_auth_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    # Define row-level ownership policy: "projects.owner_id = $user_id"
    policy = TablePolicy(
        table="projects",
        read_rules=[PolicyRule(column="owner_id", op="eq", value_template="$user_id")],
    )
    auth_engine = AuthorizationEngine(policies=[policy])

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_auth_data, auth_engine=auth_engine)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    # 2. Intercept executed SQL queries
    executed_queries: list[str] = []
    original_execute = pg_adapter_auth_data.execute

    async def tracking_execute(compiled_query):
        executed_queries.append(compiled_query.sql)
        return await original_execute(compiled_query)

    pg_adapter_auth_data.execute = tracking_execute

    # 3. User A context querying all projects
    context_user_a = {"auth_context": AuthContext(user_id="user_a", is_authenticated=True)}
    query = """
    query {
        projectss {
            id
            name
            owner_id
        }
    }
    """

    res_a = await schema.execute(query, context_value=context_user_a)
    assert res_a.errors is None, f"Query errors: {res_a.errors}"
    assert res_a.data is not None
    projects_a = res_a.data["projectss"]

    # User A must ONLY see their own projects
    assert len(projects_a) == 2
    assert all(p["owner_id"] == "user_a" for p in projects_a)

    # 4. EXPLICIT SPEC EXIT CRITERIA TEST:
    # User A attempts to fetch Project B (owned by user_b, id=3) with explicit WHERE clause
    query_target_b = """
    query {
        projectss(where: { id: { eq: 3 } }) {
            id
            name
            owner_id
        }
    }
    """

    res_b = await schema.execute(query_target_b, context_value=context_user_a)
    assert res_b.errors is None, f"Query errors: {res_b.errors}"
    assert res_b.data is not None
    projects_b = res_b.data["projectss"]

    # User A CANNOT fetch Project B even if they know Project B's exact primary key ID!
    assert len(projects_b) == 0, f"User A was able to access unauthorized Project B: {projects_b}"

    # Verify SQL query enforced both explicit filter AND authorization predicate in SQL WHERE clause
    last_query = executed_queries[-1]
    assert '"owner_id" = $' in last_query
    assert '"id" = $' in last_query
