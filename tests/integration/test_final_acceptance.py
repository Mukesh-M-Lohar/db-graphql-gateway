import strawberry
from typing import AsyncGenerator
import pytest
import pytest_asyncio
import jwt

from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.auth.authorization import AuthorizationEngine, PolicyRule, TablePolicy
from db_graphql_gateway.schema.ir.builder import IRBuilder
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.auth.jwt_provider import JWTAuthenticationProvider
from testcontainers.community.postgres import PostgresContainer
from typing import Any


@pytest.fixture(scope="module")
def postgres_container() -> Any:
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture
async def acceptance_data(
    postgres_container: Any,
) -> AsyncGenerator[tuple[GraphQLSchemaBuilder, strawberry.Schema], None]:
    postgresql_db = postgres_container.get_connection_url(driver=None)
    adapter = PostgresAdapter(dsn=postgresql_db)
    await adapter.connect()

    assert adapter.pool

    # Seed data
    async with adapter.pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS tasks;")
        await conn.execute(
            """
            CREATE TABLE tasks (
                id SERIAL PRIMARY KEY,
                title VARCHAR(100) NOT NULL,
                owner_id INT NOT NULL
            );
            """
        )
        await conn.execute("DROP TABLE IF EXISTS users;")
        await conn.execute(
            """
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL
            );
            """
        )
        await conn.execute(
            """
            ALTER TABLE tasks ADD CONSTRAINT fk_task_owner FOREIGN KEY (owner_id) REFERENCES users(id);
            """
        )
        await conn.execute(
            """
            INSERT INTO users (id, username) VALUES
            (1, 'alice'),
            (2, 'bob');
            """
        )
        await conn.execute(
            """
            INSERT INTO tasks (id, title, owner_id) VALUES
            (1, 'Task 1', 1),
            (2, 'Task 2', 1),
            (3, 'Task 3', 2),
            (4, 'Task 4', 2);
            
            SELECT setval('users_id_seq', (SELECT MAX(id) FROM users));
            SELECT setval('tasks_id_seq', (SELECT MAX(id) FROM tasks));
            """
        )

    inspector = PostgresSchemaInspector(adapter.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()

    policy = TablePolicy(
        table="tasks",
        read_rules=[PolicyRule(column="owner_id", op="eq", value_template="$user_id")],
    )
    auth_engine = AuthorizationEngine(policies=[policy])

    ir_builder = IRBuilder(type_mapper=adapter.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    schema_builder = GraphQLSchemaBuilder(db_adapter=adapter, auth_engine=auth_engine)
    schema = schema_builder.build(ir_types=ir_types, db_schema=db_schema)

    yield schema_builder, schema

    await adapter.close()


@pytest.mark.asyncio
async def test_final_acceptance_end_to_end(
    acceptance_data: tuple[GraphQLSchemaBuilder, strawberry.Schema],
) -> None:
    schema_builder, schema = acceptance_data

    auth_provider = JWTAuthenticationProvider(
        secret_or_key="secret", algorithms=["HS256"], user_id_claim="uid"
    )
    token = jwt.encode({"uid": 2}, "secret", algorithm="HS256")
    auth_context = await auth_provider.authenticate({"authorization": f"Bearer {token}"})
    print(f"DEBUG AUTH CONTEXT: {auth_context}")

    context_value = {"auth_context": auth_context}

    query = """
    query {
      taskss {
        id
        title
        owner_id
      }
    }
    """
    response = await schema.execute(query, context_value=context_value)
    assert response.errors is None, f"Query errors: {response.errors}"
    assert response.data is not None

    tasks = response.data.get("taskss", [])

    # User 2 has tasks 3 and 4
    assert len(tasks) == 2

    mutation = """
    mutation {
      create_tasks(input: { title: "New Task", owner_id: 2 }) {
        id
        title
      }
    }
    """
    res_mut = await schema.execute(mutation, context_value=context_value)
    assert res_mut.errors is None, f"Mutation errors: {res_mut.errors}"
    assert res_mut.data is not None

    mut_data = res_mut.data.get("create_tasks", {})
    assert mut_data["title"] == "New Task"
