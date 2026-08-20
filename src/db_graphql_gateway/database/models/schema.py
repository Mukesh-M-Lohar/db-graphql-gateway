from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    description: str | None = None


@dataclass
class Constraint:
    name: str
    type: Literal["primary", "foreign", "unique", "check"]
    columns: list[str]


@dataclass
class Index:
    name: str
    columns: list[str]
    is_unique: bool


@dataclass
class Relationship:
    name: str
    target_table: str
    kind: Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]
    source_columns: list[str]
    target_columns: list[str]
    join_table: str | None = None


@dataclass
class Enum:
    name: str
    values: list[str]


@dataclass
class Table:
    name: str
    schema: str
    columns: list[Column] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    indexes: list[Index] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    description: str | None = None


@dataclass
class View(Table):
    is_materialized: bool = False
    # Views are read-only


@dataclass
class DatabaseSchemaNamespace:
    name: str
    tables: dict[str, Table] = field(default_factory=dict)
    views: dict[str, View] = field(default_factory=dict)
    enums: dict[str, Enum] = field(default_factory=dict)


@dataclass
class DatabaseSchema:
    namespaces: dict[str, DatabaseSchemaNamespace] = field(default_factory=dict)
