from dataclasses import dataclass, field
from typing import Literal


@dataclass
class QueryCost:
    base_cost: int
    multiplier_per_row: float
    max_depth_contribution: int


@dataclass
class PredicateTemplate:
    sql: str
    params: dict[str, str]


@dataclass
class AuthorizationPolicy:
    resource_type: str
    action: Literal["read", "create", "update", "delete"]
    predicate_template: PredicateTemplate


@dataclass
class FieldPolicy:
    read_allowed: bool
    update_allowed: bool


@dataclass
class TableRef:
    schema: str
    name: str


@dataclass
class ColumnRef:
    table: TableRef
    name: str


@dataclass
class JoinPath:
    source_columns: list[str]
    target_columns: list[str]
    join_table: TableRef | None = None


@dataclass
class GraphQLRelationshipIR:
    kind: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    target_type: str
    join: JoinPath
    authorization_policy: AuthorizationPolicy | None = None


@dataclass
class GraphQLFieldIR:
    name: str
    graphql_type: str
    nullable: bool
    source_column: ColumnRef | None = None
    relationship: GraphQLRelationshipIR | None = None
    field_policy: FieldPolicy | None = None
    is_primary_key: bool = False


@dataclass
class GraphQLTypeIR:
    name: str
    source_table: TableRef
    fields: list[GraphQLFieldIR] = field(default_factory=list)
    is_view: bool = False
    description: str | None = None
