from db_graphql_gateway.database.models.schema import Column, Table


def test_table_model() -> None:
    col = Column(name="id", type="int", nullable=False, is_primary_key=True, is_foreign_key=False)
    table = Table(name="users", schema="public", columns=[col])

    assert table.name == "users"
    assert table.schema == "public"
    assert len(table.columns) == 1
    assert table.columns[0].name == "id"
