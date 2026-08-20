from typing import Any
from db_graphql_gateway.database.models.schema import Column, DatabaseSchema, Table
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder
from db_graphql_gateway.schema.ir.models import GraphQLTypeIR

try:
    import sqlalchemy  # noqa: F401

    _HAS_SQLALCHEMY = True
except ImportError:
    _HAS_SQLALCHEMY = False


class SQLAlchemyModelInspector:
    """Helper to construct DatabaseSchema and IR types from SQLAlchemy Declarative models."""

    @staticmethod
    def inspect_models(
        models: list[Any], type_mapper: Any, namespace_name: str = "public"
    ) -> tuple[DatabaseSchema, list[GraphQLTypeIR]]:
        tables: dict[str, Table] = {}

        for model in models:
            table_obj = getattr(model, "__table__", None)
            if table_obj is None:
                continue

            tbl_name = table_obj.name
            cols = []
            for col in table_obj.columns:
                cols.append(
                    Column(
                        name=col.name,
                        type=str(col.type),
                        nullable=col.nullable,
                        is_primary_key=col.primary_key,
                        is_foreign_key=bool(col.foreign_keys),
                        description=col.comment,
                    )
                )

            tables[tbl_name] = Table(
                name=tbl_name,
                schema=namespace_name,
                columns=cols,
                description=getattr(model, "__doc__", None),
            )

        from db_graphql_gateway.database.models.schema import DatabaseSchemaNamespace

        ns = DatabaseSchemaNamespace(name=namespace_name, tables=tables)
        db_schema = DatabaseSchema(namespaces={namespace_name: ns})

        ir_builder = IRBuilder(type_mapper=type_mapper)
        ir_types = ir_builder.build(db_schema, GatewayConfig())

        return db_schema, ir_types
