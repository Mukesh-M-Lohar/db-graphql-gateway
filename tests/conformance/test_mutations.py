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
    list_q = "query { articless { id } }"
    res1 = await schema.execute(list_q)
    assert res1.errors is None
    assert res1.data is not None
    assert len(res1.data["articless"]) == 2

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
    assert len(res3.data["articless"]) == 1
    assert res3.data["articless"][0]["id"] == 2
