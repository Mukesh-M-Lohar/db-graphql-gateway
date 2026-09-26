"""SQLite type mapper.

Converts the normalised ``Column.type`` strings produced by
``SQLiteSchemaInspector._normalise_type()`` into abstract GraphQL scalar
names.  Only abstract names are returned (``"Int"``, ``"Float"``, etc.),
so ``GraphQLSchemaBuilder.map_scalar_type()`` never receives raw SQLite
affinity strings.
"""

from typing import Any

from db_graphql_gateway.database.adapters.interfaces import TypeMapper
from db_graphql_gateway.database.models.schema import Column


class SQLiteTypeMapper(TypeMapper):
    """Maps SQLite normalised column types to GraphQL scalar names."""

    def to_graphql_type(self, column: Column) -> Any:
        t = column.type.lower()

        if t in ("integer", "int", "bigint", "smallint", "tinyint"):
            return "Int"

        if t == "boolean":
            return "Boolean"

        if t in ("float", "real", "double", "numeric", "decimal"):
            return "Float"

        if t in ("timestamp", "datetime", "date", "time"):
            return "DateTime"

        if t == "json":
            return "JSON"

        # text, blob, unknown → String
        return "String"
