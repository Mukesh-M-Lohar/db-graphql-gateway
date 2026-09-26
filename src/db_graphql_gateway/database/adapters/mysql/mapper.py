"""MySQL type mapper.

Converts MySQL ``information_schema`` column type strings (stored in
``Column.type`` by ``MySQLSchemaInspector``) into abstract GraphQL scalar
names.

**Design note**: The inspector stores ``COLUMN_TYPE`` (e.g. ``"tinyint(1)"``,
``"varchar(255)"``) rather than ``DATA_TYPE`` (e.g. ``"tinyint"``, ``"varchar"``)
because ``COLUMN_TYPE`` carries the display width needed to detect the
MySQL boolean convention (``TINYINT(1)``).

Only abstract scalar names are returned from this mapper (``"Int"``,
``"Boolean"``, etc.), so ``GraphQLSchemaBuilder.map_scalar_type()`` never
sees raw MySQL type strings.
"""

from typing import Any

from db_graphql_gateway.database.adapters.interfaces import TypeMapper
from db_graphql_gateway.database.models.schema import Column


class MySQLTypeMapper(TypeMapper):
    """Maps MySQL COLUMN_TYPE strings to GraphQL scalar names."""

    def to_graphql_type(self, column: Column) -> Any:
        # Column.type holds COLUMN_TYPE, e.g. "tinyint(1)", "varchar(255)"
        t = column.type.lower().strip()

        # MySQL boolean convention: TINYINT(1) → Boolean
        if t == "tinyint(1)":
            return "Boolean"

        # Integer types (signed and unsigned variants)
        if any(
            t.startswith(prefix) for prefix in ("tinyint", "smallint", "mediumint", "int", "bigint")
        ):
            return "Int"

        # Floating-point / fixed-precision types
        if any(
            t.startswith(prefix) for prefix in ("float", "double", "decimal", "numeric", "real")
        ):
            return "Float"

        # Boolean stored as BIT(1)
        if t == "bit(1)":
            return "Boolean"

        # Temporal types
        if any(
            t.startswith(prefix) for prefix in ("datetime", "timestamp", "date", "time", "year")
        ):
            return "DateTime"

        # JSON (MySQL 5.7.8+)
        if t == "json":
            return "JSON"

        # All text / binary types → String
        return "String"
