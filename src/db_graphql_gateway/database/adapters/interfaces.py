from dataclasses import dataclass
from typing import Any, Literal, Protocol

from db_graphql_gateway.database.models.schema import Column, DatabaseSchema


# ---------------------------------------------------------------------------
# Dialect capability type alias
# ---------------------------------------------------------------------------

PlaceholderStyle = Literal["numbered", "qmark", "named"]
"""
"numbered" : $1, $2, …    (PostgreSQL / asyncpg)
"qmark"    : ?, ?, …      (SQLite via aiosqlite, MySQL via asyncmy)
"named"    : @p1, @p2, …  (SQL Server / future)
"""


@dataclass
class TableRef:
    schema: str
    name: str


class QueryResult:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


@dataclass
class FilterCondition:
    column: str
    op: str  # eq, neq, gt, gte, lt, lte, in, like, ilike, contains, is_null
    value: Any


@dataclass
class FilterGroup:
    operator: str  # AND, OR, NOT
    conditions: list["FilterCondition | FilterGroup"]


@dataclass
class OrderByItem:
    column: str
    direction: str  # ASC, DESC


@dataclass
class QueryPlan:
    table: TableRef
    selected_columns: list[str] | None = None
    pk_column: str | None = None
    pk_value: Any | None = None
    filter_tree: FilterGroup | FilterCondition | None = None
    order_by: list[OrderByItem] | None = None
    limit: int | None = None
    offset: int | None = None
    batch_column: str | None = None
    batch_values: list[Any] | None = None


@dataclass
class MutationPlan:
    operation: str  # insert, update, delete
    table: TableRef
    data: dict[str, Any] | None = None
    filter_tree: FilterGroup | FilterCondition | None = None
    pk_column: str | None = None
    pk_value: Any | None = None


class CompiledQuery:
    """A compiled SQL string paired with its positional or named parameters.

    For adapters that do not support ``RETURNING`` (SQLite < 3.35, MySQL < 8.0.21),
    ``compile_mutation`` sets ``fetch_after_write = True`` and populates
    ``fetch_table`` / ``fetch_pk_col`` / ``fetch_pk_value`` so the adapter's
    ``execute()`` can perform the follow-up SELECT automatically.
    """

    def __init__(self, sql: str, params: list[Any] | dict[str, Any]) -> None:
        self.sql = sql
        # list[Any] for positional dialects (numbered / qmark)
        # dict[str, Any] for named dialects (@p1 / :name)
        self.params: list[Any] | dict[str, Any] = params

        # SELECT-after-write sentinel fields (set by BaseQueryCompiler when
        # supports_returning == False)
        self.fetch_after_write: bool = False
        self.fetch_table: str | None = None
        self.fetch_pk_col: str | None = None
        self.fetch_pk_value: Any = None


class SchemaInspector(Protocol):
    async def discover_schema(self) -> DatabaseSchema: ...


class QueryCompiler(Protocol):
    def compile(self, plan: QueryPlan) -> CompiledQuery: ...
    def compile_mutation(self, plan: MutationPlan) -> CompiledQuery: ...


class TypeMapper(Protocol):
    def to_graphql_type(self, column: Column) -> Any: ...


class DatabaseAdapter(Protocol):
    # ── Dialect capability flags ──────────────────────────────────────────
    supports_returning: bool
    """True when the adapter's SQL dialect supports RETURNING after DML."""

    supports_upsert_on_conflict: bool
    """True when ON CONFLICT DO UPDATE / ON DUPLICATE KEY UPDATE is available."""

    placeholder_style: PlaceholderStyle
    """Controls how the compiler renders parameter placeholders."""

    identifier_quote_char: str
    """Character used to quote SQL identifiers: '\"' (Postgres/SQLite), '`' (MySQL)."""

    # ── Lifecycle ──────────────────────────────────────────────────────────
    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    # ── Execution ──────────────────────────────────────────────────────────
    async def execute(self, query: CompiledQuery) -> QueryResult: ...
    async def execute_many(self, queries: list[CompiledQuery]) -> list[QueryResult]: ...
    async def execute_raw_dml(self, sql: str) -> None: ...

    # ── Sub-objects ────────────────────────────────────────────────────────
    def inspector(self) -> SchemaInspector: ...
    def compiler(self) -> QueryCompiler: ...
    def type_mapper(self) -> TypeMapper: ...
