import pytest
from typing import Any
import asyncio
from db_graphql_gateway.database.adapters.interfaces import CompiledQuery

pytestmark = pytest.mark.asyncio


async def test_optimistic_locking(gql_schema: tuple[Any, Any], run_sql: Any) -> None:
    schema, adapter = gql_schema

    await run_sql(adapter, "INSERT INTO tasks (id, summary, version) VALUES (1, 'Old Summary', 0)")

    # 1. Update with correct version -> Success
    mutation_success = """
    mutation {
        update_tasks(id: 1, input: { summary: "New Summary" }, expected_version: 0) {
            id
            summary
            version
        }
    }
    """
    res1 = await schema.execute(mutation_success)
    assert res1.errors is None
    assert res1.data is not None
    assert res1.data["update_tasks"]["summary"] == "New Summary"
    assert res1.data["update_tasks"]["version"] == 1

    # 2. Update concurrently with same expected version -> 1 Success, 1 Failure
    res2, res3 = await asyncio.gather(
        schema.execute(
            mutation_success.replace("New", "Racer1").replace(
                "expected_version: 0", "expected_version: 1"
            )
        ),
        schema.execute(
            mutation_success.replace("New", "Racer2").replace(
                "expected_version: 0", "expected_version: 1"
            )
        ),
    )

    # Exactly one should fail
    errors = (res2.errors or []) + (res3.errors or [])
    assert len(errors) == 1
    assert (
        "Optimistic concurrency failure: record modified by another transaction or not found."
        in str(errors[0])
    )


async def test_soft_deletes(gql_schema: tuple[Any, Any], run_sql: Any) -> None:
    schema, adapter = gql_schema

    await run_sql(
        adapter,
        "INSERT INTO articles (id, title, deleted_at) VALUES (1, 'Article 1', NULL), (2, 'Article 2', NULL)",
    )

    # 1. List shows both initially
    list_q = "query { articles { id } }"
    res1 = await schema.execute(list_q)
    assert res1.errors is None
    assert res1.data is not None
    assert len(res1.data["articles"]) == 2

    # 2. Delete article 1
    del_m = "mutation { delete_articles(id: 1) { id } }"
    res_del = await schema.execute(del_m)
    assert res_del.errors is None
    assert res_del.data is not None

    # 2.5 Raw SELECT to ensure the row still exists and deleted_at is set
    raw_q = CompiledQuery(sql="SELECT id, deleted_at FROM articles WHERE id = 1", params=[])
    db_res = await adapter.execute(raw_q)
    assert len(db_res.data) == 1
    assert db_res.data[0]["deleted_at"] is not None

    # 3. List shows only article 2 now
    res3 = await schema.execute(list_q)
    assert res3.errors is None
    assert res3.data is not None
    assert len(res3.data["articles"]) == 1
    assert res3.data["articles"][0]["id"] == 2


async def test_pkless_table_read_only(gql_schema: tuple[Any, Any], run_sql: Any) -> None:
    schema, adapter = gql_schema

    # 1. mutation create_logs shouldn't exist
    mutation_query = """
    mutation {
        create_logs(input: { message: "test", level: "info" }) {
            message
        }
    }
    """
    res = await schema.execute(mutation_query)
    assert res.errors is not None
    assert "Cannot query field 'create_logs' on type 'Mutation'" in str(res.errors[0])

    # 2. We can still read from it
    await run_sql(adapter, "INSERT INTO logs (message, level) VALUES ('Hello', 'INFO')")
    read_res = await schema.execute("query { logs { message level } }")
    assert read_res.errors is None
    assert read_res.data is not None
    assert read_res.data["logs"][0]["message"] == "Hello"


async def test_composite_pk(gql_schema: tuple[Any, Any]) -> None:
    schema, adapter = gql_schema

    # Create
    mutation_create = """
    mutation {
        create_user_roles(input: { user_id: 1, role_id: 2, assigned_by: 99 }) {
            user_id
            role_id
            assigned_by
        }
    }
    """
    res = await schema.execute(mutation_create)
    assert res.errors is None, res.errors
    assert res.data is not None
    assert res.data["create_user_roles"]["assigned_by"] == 99

    # Update - passing a JSON object for ID requires GraphQL variables since {user_id: 1, role_id: 2} is parsed as nested objects instead of JSON if written as literal, wait!
    # Strawberry JSON scalar parses inline `{ user_id: 1, role_id: 2 }` just fine.
    mutation_update = """
    mutation {
        update_user_roles(id: { user_id: 1, role_id: 2 }, input: { assigned_by: 100 }) {
            user_id
            role_id
            assigned_by
        }
    }
    """
    # Wait, actually in GraphQL a JSON literal object like `{ user_id: 1, role_id: 2 }` is invalid syntax for a scalar literal unless parsed by the scalar itself. Strawberry JSON scalar parses object literals!
    # If it fails, I'll use variables.
    res = await schema.execute(
        "mutation($id: JSON!) { update_user_roles(id: $id, input: { assigned_by: 100 }) { assigned_by } }",
        variable_values={"id": {"user_id": 1, "role_id": 2}},
    )
    assert res.errors is None, res.errors
    assert res.data is not None
    assert res.data["update_user_roles"]["assigned_by"] == 100

    # Delete
    res = await schema.execute(
        "mutation($id: JSON!) { delete_user_roles(id: $id) { user_id } }",
        variable_values={"id": {"user_id": 1, "role_id": 2}},
    )
    assert res.errors is None, res.errors
    assert res.data is not None
    assert res.data["delete_user_roles"]["user_id"] == 1
