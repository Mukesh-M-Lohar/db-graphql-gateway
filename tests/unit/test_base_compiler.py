"""Unit tests for BaseQueryCompiler — verifies dialect-parameterized behaviour."""

from db_graphql_gateway.database.adapters.base_compiler import BaseQueryCompiler
from db_graphql_gateway.database.adapters.interfaces import (
    FilterCondition,
    FilterGroup,
    MutationPlan,
    QueryPlan,
    TableRef,
)


# ---------------------------------------------------------------------------
# Concrete subclasses for each dialect style
# ---------------------------------------------------------------------------


class NumberedCompiler(BaseQueryCompiler):
    placeholder_style = "numbered"
    identifier_quote_char = '"'
    supports_returning = True
    ilike_supported = True


class QmarkCompiler(BaseQueryCompiler):
    placeholder_style = "qmark"
    identifier_quote_char = '"'
    supports_returning = False
    ilike_supported = False


class BacktickCompiler(BaseQueryCompiler):
    placeholder_style = "qmark"
    identifier_quote_char = "`"
    supports_returning = False
    ilike_supported = False


# ---------------------------------------------------------------------------
# Placeholder style tests
# ---------------------------------------------------------------------------


def test_numbered_placeholder_basic() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="users"),
        filter_tree=FilterCondition(column="id", op="eq", value=42),
    )
    cq = c.compile(plan)
    assert "$1" in cq.sql
    assert cq.params == [42]


def test_qmark_placeholder_basic() -> None:
    c = QmarkCompiler()
    plan = QueryPlan(
        table=TableRef(schema="main", name="users"),
        filter_tree=FilterCondition(column="id", op="eq", value=42),
    )
    cq = c.compile(plan)
    assert "?" in cq.sql
    assert "$" not in cq.sql
    assert cq.params == [42]


def test_numbered_placeholder_multiple_params() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="items"),
        filter_tree=FilterGroup(
            operator="AND",
            conditions=[
                FilterCondition(column="price", op="gt", value=10),
                FilterCondition(column="price", op="lt", value=100),
            ],
        ),
    )
    cq = c.compile(plan)
    assert "$1" in cq.sql
    assert "$2" in cq.sql
    assert cq.params == [10, 100]


def test_qmark_multiple_params() -> None:
    c = QmarkCompiler()
    plan = QueryPlan(
        table=TableRef(schema="main", name="items"),
        filter_tree=FilterGroup(
            operator="AND",
            conditions=[
                FilterCondition(column="price", op="gt", value=10),
                FilterCondition(column="price", op="lt", value=100),
            ],
        ),
    )
    cq = c.compile(plan)
    assert cq.sql.count("?") == 2
    assert "$" not in cq.sql
    assert cq.params == [10, 100]


# ---------------------------------------------------------------------------
# Identifier quoting tests
# ---------------------------------------------------------------------------


def test_double_quote_identifiers() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(table=TableRef(schema="public", name="users"))
    cq = c.compile(plan)
    assert '"public"."users"' in cq.sql


def test_backtick_identifiers() -> None:
    c = BacktickCompiler()
    plan = QueryPlan(table=TableRef(schema="mydb", name="users"))
    cq = c.compile(plan)
    assert "`mydb`.`users`" in cq.sql


def test_column_quoted_in_filter() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="users"),
        filter_tree=FilterCondition(column="user_name", op="eq", value="alice"),
    )
    cq = c.compile(plan)
    assert '"user_name"' in cq.sql


# ---------------------------------------------------------------------------
# ILIKE vs LIKE branching
# ---------------------------------------------------------------------------


def test_ilike_used_when_supported() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="posts"),
        filter_tree=FilterCondition(column="title", op="ilike", value="%hello%"),
    )
    cq = c.compile(plan)
    assert "ILIKE" in cq.sql


def test_ilike_falls_back_to_like() -> None:
    c = QmarkCompiler()
    plan = QueryPlan(
        table=TableRef(schema="main", name="posts"),
        filter_tree=FilterCondition(column="title", op="ilike", value="%hello%"),
    )
    cq = c.compile(plan)
    assert "LIKE" in cq.sql
    assert "ILIKE" not in cq.sql


def test_contains_filter_numbered() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="posts"),
        filter_tree=FilterCondition(column="title", op="contains", value="hello"),
    )
    cq = c.compile(plan)
    assert "ILIKE" in cq.sql
    assert cq.params == ["%hello%"]


def test_contains_filter_qmark() -> None:
    c = QmarkCompiler()
    plan = QueryPlan(
        table=TableRef(schema="main", name="posts"),
        filter_tree=FilterCondition(column="title", op="contains", value="hello"),
    )
    cq = c.compile(plan)
    assert "LIKE" in cq.sql
    assert "ILIKE" not in cq.sql
    assert cq.params == ["%hello%"]


# ---------------------------------------------------------------------------
# RETURNING vs fetch_after_write
# ---------------------------------------------------------------------------


def test_returning_on_insert_when_supported() -> None:
    c = NumberedCompiler()
    plan = MutationPlan(
        operation="insert",
        table=TableRef(schema="public", name="users"),
        data={"name": "Alice"},
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" in cq.sql
    assert not cq.fetch_after_write


def test_no_returning_sets_fetch_after_write_insert() -> None:
    c = QmarkCompiler()
    plan = MutationPlan(
        operation="insert",
        table=TableRef(schema="main", name="users"),
        data={"name": "Alice"},
        pk_column="id",
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" not in cq.sql
    assert cq.fetch_after_write is True
    assert cq.fetch_table == "users"
    assert cq.fetch_pk_col == "id"


def test_no_returning_sets_fetch_after_write_update() -> None:
    c = QmarkCompiler()
    plan = MutationPlan(
        operation="update",
        table=TableRef(schema="main", name="users"),
        data={"name": "Bob"},
        pk_column="id",
        pk_value=5,
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" not in cq.sql
    assert cq.fetch_after_write is True
    assert cq.fetch_pk_value == 5


def test_returning_on_update_when_supported() -> None:
    c = NumberedCompiler()
    plan = MutationPlan(
        operation="update",
        table=TableRef(schema="public", name="users"),
        data={"name": "Carol"},
        pk_column="id",
        pk_value=7,
    )
    cq = c.compile_mutation(plan)
    assert "RETURNING" in cq.sql
    assert not cq.fetch_after_write


# ---------------------------------------------------------------------------
# IN operator
# ---------------------------------------------------------------------------


def test_in_operator_numbered() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="users"),
        filter_tree=FilterCondition(column="id", op="in", value=[1, 2, 3]),
    )
    cq = c.compile(plan)
    assert "IN ($1, $2, $3)" in cq.sql
    assert cq.params == [1, 2, 3]


def test_in_operator_qmark() -> None:
    c = QmarkCompiler()
    plan = QueryPlan(
        table=TableRef(schema="main", name="users"),
        filter_tree=FilterCondition(column="id", op="in", value=[1, 2, 3]),
    )
    cq = c.compile(plan)
    assert "IN (?, ?, ?)" in cq.sql
    assert cq.params == [1, 2, 3]


def test_in_empty_list_returns_false() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="users"),
        filter_tree=FilterCondition(column="id", op="in", value=[]),
    )
    cq = c.compile(plan)
    assert "FALSE" in cq.sql
    assert cq.params == []


# ---------------------------------------------------------------------------
# LIMIT / OFFSET
# ---------------------------------------------------------------------------


def test_limit_offset_numbered() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="posts"),
        limit=10,
        offset=20,
    )
    cq = c.compile(plan)
    assert "LIMIT $1" in cq.sql
    assert "OFFSET $2" in cq.sql
    assert cq.params == [10, 20]


def test_limit_offset_qmark() -> None:
    c = QmarkCompiler()
    plan = QueryPlan(
        table=TableRef(schema="main", name="posts"),
        limit=10,
        offset=20,
    )
    cq = c.compile(plan)
    assert "LIMIT ?" in cq.sql
    assert "OFFSET ?" in cq.sql
    assert cq.params == [10, 20]


# ---------------------------------------------------------------------------
# NOT / OR filters
# ---------------------------------------------------------------------------


def test_not_filter() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="users"),
        filter_tree=FilterGroup(
            operator="NOT",
            conditions=[FilterCondition(column="deleted_at", op="is_null", value=False)],
        ),
    )
    cq = c.compile(plan)
    assert "NOT" in cq.sql


def test_or_filter() -> None:
    c = NumberedCompiler()
    plan = QueryPlan(
        table=TableRef(schema="public", name="users"),
        filter_tree=FilterGroup(
            operator="OR",
            conditions=[
                FilterCondition(column="role", op="eq", value="admin"),
                FilterCondition(column="role", op="eq", value="editor"),
            ],
        ),
    )
    cq = c.compile(plan)
    assert "OR" in cq.sql
    assert cq.params == ["admin", "editor"]
