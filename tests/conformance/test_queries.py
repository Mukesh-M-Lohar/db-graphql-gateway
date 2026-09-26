import pytest
from typing import Any

pytestmark = pytest.mark.asyncio


async def test_simple_list_query(gql_schema: tuple[Any, Any], run_sql: Any) -> None:
    schema, adapter = gql_schema

    # Insert test data
    await run_sql(adapter, "INSERT INTO authors (name) VALUES ('Tolkien'), ('Asimov')")

    query = """
    query {
        authorss {
            id
            name
        }
    }
    """
    result = await schema.execute(query)

    assert result.errors is None
    assert result.data is not None
    assert len(result.data["authorss"]) == 2

    names = {author["name"] for author in result.data["authorss"]}
    assert names == {"Tolkien", "Asimov"}


async def test_filtering_and_pagination(gql_schema: tuple[Any, Any], run_sql: Any) -> None:
    schema, adapter = gql_schema

    await run_sql(
        adapter,
        "INSERT INTO users (name, is_active, owner_id) VALUES ('Alice', true, 1), ('Bob', false, 1), ('Charlie', true, 2)",
    )

    query = """
    query {
        userss(where: { is_active: { eq: true } }, order_by: { name: DESC }, limit: 1) {
            id
            name
            is_active
        }
    }
    """
    result = await schema.execute(query)

    assert result.errors is None
    assert result.data is not None
    assert len(result.data["userss"]) == 1

    # Charlie is active, Alice is active. DESC order means Charlie comes first.
    assert result.data["userss"][0]["name"] == "Charlie"
    assert result.data["userss"][0]["is_active"] is True
