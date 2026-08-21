"""Unit tests for the MySQL adapter suite.

These tests run without a database container — they only exercise the
compiler, type mapper, and static adapter configuration.
Integration tests (requiring a real MySQL container) are in
``tests/integration/test_mysql_integration.py``.
"""

from db_graphql_gateway.database.adapters.mysql.compiler import MySQLQueryCompiler
from db_graphql_gateway.database.adapters.mysql.mapper import MySQLTypeMapper
from db_graphql_gateway.database.adapters.interfaces import (
    FilterCondition,
    MutationPlan,
    QueryPlan,
    TableRef,
)
from db_graphql_gateway.database.models.schema import Column


# ---------------------------------------------------------------------------
# Compiler — placeholder style, identifier quoting, ILIKE, RETURNING
# ---------------------------------------------------------------------------


def test_compiler_uses_qmark_placeholders() -> None:
    c = MySQLQueryCompiler()
    plan = QueryPlan(
        table=TableRef(schema="mydb", name="users"),
        filter_tree=FilterCondition(column="id", op="eq", value=1),
    )
    cq = c.compile(plan)
    assert "%s" in cq.sql
    assert "$" not in cq.sql
    assert cq.params == [1]


def test_compiler_uses_backtick_identifiers() -> None:
    c = MySQLQueryCompiler()
    plan = QueryPlan(table=TableRef(schema="mydb", name="users"))
    cq = c.compile(plan)
    assert "`mydb`.`users`" in cq.sql


def test_compiler_column_backtick_quoted() -> None:
    c = MySQLQueryCompiler()
    plan = QueryPlan(
        table=TableRef(schema="mydb", name="users"),
        filter_tree=FilterCondition(column="user_name", op="eq", value="alice"),
    )
    cq = c.compile(plan)
    assert "`user_name`" in cq.sql


def test_compiler_ilike_degrades_to_like() -> None:
    c = MySQLQueryCompiler()
    plan = QueryPlan(
        table=TableRef(schema="mydb", name="posts"),
        filter_tree=FilterCondition(column="title", op="ilike", value="%hello%"),
    )
    cq = c.compile(plan)
    assert "LIKE" in cq.sql
    assert "ILIKE" not in cq.sql


def test_compiler_contains_degrades_to_like() -> None:
    c = MySQLQueryCompiler()
    plan = QueryPlan(
        table=TableRef(schema="mydb", name="posts"),
        filter_tree=FilterCondition(column="title", op="contains", value="hello"),
    )
    cq = c.compile(plan)
    assert "LIKE" in cq.sql
    assert "ILIKE" not in cq.sql
    assert cq.params == ["%hello%"]


def test_compiler_insert_no_returning() -> None:
    c = MySQLQueryCompiler()
    plan = MutationPlan(
        operation="insert",
        table=TableRef(schema="mydb", name="users"),
        data={"name": "Alice"},
        pk_column="id",
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" not in cq.sql
    assert cq.fetch_after_write is True
    assert cq.fetch_table == "users"
    assert cq.fetch_pk_col == "id"


def test_compiler_update_no_returning() -> None:
    c = MySQLQueryCompiler()
    plan = MutationPlan(
        operation="update",
        table=TableRef(schema="mydb", name="users"),
        data={"name": "Bob"},
        pk_column="id",
        pk_value=3,
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" not in cq.sql
    assert cq.fetch_after_write is True
    assert cq.fetch_pk_value == 3


def test_compiler_delete_no_returning() -> None:
    c = MySQLQueryCompiler()
    plan = MutationPlan(
        operation="delete",
        table=TableRef(schema="mydb", name="users"),
        pk_column="id",
        pk_value=5,
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" not in cq.sql
    assert cq.fetch_after_write is True


def test_auth_filter_uses_qmark() -> None:
    """Authorization predicates must compile to %s placeholders in MySQL."""
    c = MySQLQueryCompiler()
    plan = QueryPlan(
        table=TableRef(schema="mydb", name="tasks"),
        filter_tree=FilterCondition(column="owner_id", op="eq", value=7),
    )
    cq = c.compile(plan)
    assert "`owner_id` = %s" in cq.sql
    assert cq.params == [7]


def test_compiler_limit_offset() -> None:
    c = MySQLQueryCompiler()
    plan = QueryPlan(
        table=TableRef(schema="mydb", name="posts"),
        limit=10,
        offset=20,
    )
    cq = c.compile(plan)
    assert "LIMIT %s" in cq.sql
    assert "OFFSET %s" in cq.sql
    assert cq.params == [10, 20]


def test_compiler_in_operator() -> None:
    c = MySQLQueryCompiler()
    plan = QueryPlan(
        table=TableRef(schema="mydb", name="users"),
        filter_tree=FilterCondition(column="id", op="in", value=[1, 2, 3]),
    )
    cq = c.compile(plan)
    assert "IN (%s, %s, %s)" in cq.sql
    assert cq.params == [1, 2, 3]


# ---------------------------------------------------------------------------
# Type mapper
# ---------------------------------------------------------------------------


def _col(name: str, col_type: str, nullable: bool = True) -> Column:
    return Column(
        name=name,
        type=col_type,
        nullable=nullable,
        is_primary_key=False,
        is_foreign_key=False,
    )


def test_mapper_tinyint1_is_boolean() -> None:
    m = MySQLTypeMapper()
    assert m.to_graphql_type(_col("active", "tinyint(1)")) == "Boolean"


def test_mapper_bit1_is_boolean() -> None:
    m = MySQLTypeMapper()
    assert m.to_graphql_type(_col("flag", "bit(1)")) == "Boolean"


def test_mapper_tinyint_is_int() -> None:
    m = MySQLTypeMapper()
    # tinyint(4) (size > 1) is an integer, not a boolean
    assert m.to_graphql_type(_col("count", "tinyint(4)")) == "Int"


def test_mapper_int_variants() -> None:
    m = MySQLTypeMapper()
    for col_type in ("int(11)", "bigint(20)", "smallint(6)", "mediumint(9)", "int unsigned"):
        assert m.to_graphql_type(_col("n", col_type)) == "Int", f"Failed for {col_type!r}"


def test_mapper_float_variants() -> None:
    m = MySQLTypeMapper()
    for col_type in ("float", "double", "decimal(10,2)", "numeric(8,4)"):
        assert m.to_graphql_type(_col("v", col_type)) == "Float", f"Failed for {col_type!r}"


def test_mapper_datetime_variants() -> None:
    m = MySQLTypeMapper()
    for col_type in ("datetime", "timestamp", "date", "time", "year"):
        assert m.to_graphql_type(_col("t", col_type)) == "DateTime", f"Failed for {col_type!r}"


def test_mapper_json() -> None:
    m = MySQLTypeMapper()
    assert m.to_graphql_type(_col("meta", "json")) == "JSON"


def test_mapper_text_variants() -> None:
    m = MySQLTypeMapper()
    for col_type in ("varchar(255)", "text", "char(10)", "longtext", "mediumtext"):
        assert m.to_graphql_type(_col("s", col_type)) == "String", f"Failed for {col_type!r}"


# ---------------------------------------------------------------------------
# Adapter capability flags (static check, no connection needed)
# ---------------------------------------------------------------------------


def test_adapter_capability_flags() -> None:
    from db_graphql_gateway.database.adapters.mysql.adapter import MySQLAdapter

    adapter = MySQLAdapter()
    assert adapter.supports_returning is False
    assert adapter.supports_upsert_on_conflict is False
    assert adapter.placeholder_style == "qmark"
    assert adapter.identifier_quote_char == "`"
