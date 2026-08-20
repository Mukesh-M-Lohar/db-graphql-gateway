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
async def pg_adapter_mutation_data(postgres_container: Any) -> AsyncGenerator[Any, None]:
    connection_url = postgres_container.get_connection_url(driver=None)
    adapter = PostgresAdapter(dsn=connection_url)
    await adapter.connect()

    assert adapter.pool
    async with adapter.pool.acquire() as conn:
        await conn.execute("DROP VIEW IF EXISTS active_tasks_view;")
        await conn.execute("DROP TABLE IF EXISTS tasks;")
        await conn.execute(
            """
            CREATE TABLE tasks (
                id SERIAL PRIMARY KEY,
                title VARCHAR(100) NOT NULL,
                owner_id VARCHAR(50) NOT NULL
            );
            """
        )
        await conn.execute(
            """
            CREATE VIEW active_tasks_view AS
            SELECT id, title, owner_id FROM tasks;
            """
        )

    yield adapter
    await adapter.close()


@pytest.mark.asyncio
async def test_mutations_create_update_delete_flow(pg_adapter_mutation_data: Any) -> None:
    inspector = PostgresSchemaInspector(pg_adapter_mutation_data.pool, schemas=["public"])
    db_schema = await inspector.discover_schema()

    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=pg_adapter_mutation_data.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    # Policy: users can only modify/delete tasks where owner_id = $user_id
    policy = TablePolicy(
        table="tasks",
        read_rules=[PolicyRule(column="owner_id", op="eq", value_template="$user_id")],
    )
    auth_engine = AuthorizationEngine(policies=[policy])

    builder = GraphQLSchemaBuilder(db_adapter=pg_adapter_mutation_data, auth_engine=auth_engine)
    schema = builder.build(ir_types=ir_types, db_schema=db_schema)

    user_a_ctx = {"auth_context": AuthContext(user_id="user_a", is_authenticated=True)}
    user_b_ctx = {"auth_context": AuthContext(user_id="user_b", is_authenticated=True)}

    # 1. User A creates a task
    create_mutation = """
    mutation {
        create_tasks(input: { title: "Task 1", owner_id: "user_a" }) {
            id
            title
            owner_id
        }
    }
    """
    res_create = await schema.execute(create_mutation, context_value=user_a_ctx)
    assert res_create.errors is None, f"Create mutation errors: {res_create.errors}"
    task = res_create.data["create_tasks"]
    task_id = task["id"]
    assert task["title"] == "Task 1"
    assert task["owner_id"] == "user_a"

    # 2. User B attempts to UPDATE User A's task -> Should be DENIED (returns null)
    update_mutation = f"""
    mutation {{
        update_tasks(id: {task_id}, input: {{ title: "Hacked Title" }}) {{
            id
            title
        }}
    }}
    """
    res_update_b = await schema.execute(update_mutation, context_value=user_b_ctx)
    assert res_update_b.errors is None
    assert res_update_b.data["update_tasks"] is None

    # 3. User A UPDATES their own task -> Success
    update_mutation_a = f"""
    mutation {{
        update_tasks(id: {task_id}, input: {{ title: "Updated Title" }}) {{
            id
            title
        }}
    }}
    """
    res_update_a = await schema.execute(update_mutation_a, context_value=user_a_ctx)
    assert res_update_a.errors is None
    assert res_update_a.data["update_tasks"]["title"] == "Updated Title"

    # 4. User B attempts to DELETE User A's task -> Should be DENIED (returns null)
    delete_mutation = f"""
    mutation {{
        delete_tasks(id: {task_id}) {{
            id
        }}
    }}
    """
    res_delete_b = await schema.execute(delete_mutation, context_value=user_b_ctx)
    assert res_delete_b.errors is None
    assert res_delete_b.data["delete_tasks"] is None

    # 5. User A DELETES their own task -> Success
    res_delete_a = await schema.execute(delete_mutation, context_value=user_a_ctx)
    assert res_delete_a.errors is None
    assert res_delete_a.data["delete_tasks"]["id"] == task_id

    # 6. Verify Read-Only Views have NO mutations generated
    mutation_type = schema.mutation
    assert mutation_type is not None
    mutation_fields = mutation_type.__strawberry_definition__.fields
    field_names = [f.python_name for f in mutation_fields if f.python_name]
    assert not any(
        "active_tasks_view" in fn for fn in field_names
    ), f"View mutations exposed! {field_names}"
