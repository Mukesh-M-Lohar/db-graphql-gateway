from typing import Any

from db_graphql_gateway.database.adapters.interfaces import TypeMapper
from db_graphql_gateway.database.models.schema import Column


class PostgresTypeMapper(TypeMapper):
    def to_graphql_type(self, column: Column) -> Any:
        type_str = column.type.lower()
        if "int" in type_str or "serial" in type_str:
            return "Int"
        if "bool" in type_str:
            return "Boolean"
        if (
            "numeric" in type_str
            or "float" in type_str
            or "double" in type_str
            or "real" in type_str
        ):
            return "Float"
        if "timestamp" in type_str or "date" in type_str or "time" in type_str:
            return "DateTime"
        if "json" in type_str:
            return "JSON"
        if "uuid" in type_str:
            return "UUID"
        return "String"
