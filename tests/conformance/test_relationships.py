import pytest
from typing import Any
from unittest.mock import AsyncMock

pytestmark = pytest.mark.asyncio


async def test_relationship_dataloader(gql_schema: tuple[Any, Any], run_sql: Any) -> None:
    schema, adapter = gql_schema

    await run_sql(adapter, "INSERT INTO authors (id, name) VALUES (1, 'Tolkien'), (2, 'Asimov')")
    await run_sql(
        adapter,
        "INSERT INTO books (title, author_id) VALUES ('The Hobbit', 1), ('Foundation', 2), ('LOTR', 1)",
    )

    query = """
    query {
        authorss(order_by: { name: DESC }) {
            name
            bookss {
                title
            }
        }
    }
    """
    original_execute = adapter.execute
    original_execute_many = adapter.execute_many
    mock_execute = AsyncMock(side_effect=original_execute)
    mock_execute_many = AsyncMock(side_effect=original_execute_many)
    adapter.execute = mock_execute
    adapter.execute_many = mock_execute_many

    result = await schema.execute(query, context_value={})

    adapter.execute = original_execute
    adapter.execute_many = original_execute_many

    assert (
        (mock_execute.call_count + mock_execute_many.call_count) == 2
    ), f"N+1 failure: expected 2 queries, got {mock_execute.call_count + mock_execute_many.call_count}"

    assert result.errors is None
    assert result.data is not None

    authors = result.data["authorss"]
    assert len(authors) == 2

    assert authors[0]["name"] == "Tolkien"
    assert len(authors[0]["bookss"]) == 2
    book_titles_1 = {b["title"] for b in authors[0]["bookss"]}
    assert book_titles_1 == {"The Hobbit", "LOTR"}

    assert authors[1]["name"] == "Asimov"
    assert len(authors[1]["bookss"]) == 1
    assert authors[1]["bookss"][0]["title"] == "Foundation"
