from dataclasses import dataclass
from typing import Any, Protocol

from db_graphql_gateway.database.models.schema import Column, DatabaseSchema


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
    op: str  # eq, neq, gt, gte, lt, lte, in, like, ilike, is_null
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
    def __init__(self, sql: str, params: list[Any]) -> None:
        self.sql = sql
        self.params = params


class SchemaInspector(Protocol):
    async def discover_schema(self) -> DatabaseSchema: ...


class QueryCompiler(Protocol):
    def compile(self, plan: QueryPlan) -> CompiledQuery: ...
    def compile_mutation(self, plan: MutationPlan) -> CompiledQuery: ...


class TypeMapper(Protocol):
    def to_graphql_type(self, column: Column) -> Any: ...


class DatabaseAdapter(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def execute(self, query: CompiledQuery) -> QueryResult: ...
    async def execute_many(self, queries: list[CompiledQuery]) -> list[QueryResult]: ...
    def inspector(self) -> SchemaInspector: ...
    def compiler(self) -> QueryCompiler: ...
    def type_mapper(self) -> TypeMapper: ...
