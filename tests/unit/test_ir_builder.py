from db_graphql_gateway.database.models.schema import (
    Column,
    DatabaseSchema,
    DatabaseSchemaNamespace,
    Table,
)
from db_graphql_gateway.schema.config import FieldConfig, GatewayConfig, TableConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder


class StubTypeMapper:
    def to_graphql_type(self, column: Column) -> str:
        if column.type == "int":
            return "Int"
        return "String"


def test_ir_builder_generates_ir_without_config() -> None:
    db_schema = DatabaseSchema()
    ns = DatabaseSchemaNamespace(name="public")
    db_schema.namespaces["public"] = ns

    table = Table(
        name="users",
        schema="public",
        columns=[
            Column(
                name="id", type="int", nullable=False, is_primary_key=True, is_foreign_key=False
            ),
            Column(
                name="username",
                type="varchar",
                nullable=False,
                is_primary_key=False,
                is_foreign_key=False,
            ),
        ],
    )
    ns.tables["users"] = table

    config = GatewayConfig()
    builder = IRBuilder(type_mapper=StubTypeMapper())

    types = builder.build(db_schema, config)

    assert len(types) == 1
    type_ir = types[0]
    assert type_ir.name == "users"
    assert type_ir.source_table.name == "users"

    assert len(type_ir.fields) == 2
    assert type_ir.fields[0].name == "id"
    assert type_ir.fields[0].graphql_type == "Int"
    assert type_ir.fields[1].name == "username"
    assert type_ir.fields[1].graphql_type == "String"


def test_ir_builder_applies_config_overrides() -> None:
    db_schema = DatabaseSchema()
    ns = DatabaseSchemaNamespace(name="public")
    db_schema.namespaces["public"] = ns

    table = Table(
        name="user_accounts",
        schema="public",
        columns=[
            Column(
                name="id", type="int", nullable=False, is_primary_key=True, is_foreign_key=False
            ),
            Column(
                name="pwd_hash",
                type="varchar",
                nullable=False,
                is_primary_key=False,
                is_foreign_key=False,
            ),
            Column(
                name="created_at",
                type="timestamp",
                nullable=False,
                is_primary_key=False,
                is_foreign_key=False,
            ),
        ],
    )
    ns.tables["user_accounts"] = table

    # Config to rename table, hide password, and rename created_at
    config = GatewayConfig(
        tables={
            "user_accounts": TableConfig(
                graphql_name="User",
                fields={
                    "pwd_hash": FieldConfig(hidden=True),
                    "created_at": FieldConfig(graphql_name="registeredAt"),
                },
            )
        }
    )

    builder = IRBuilder(type_mapper=StubTypeMapper())
    types = builder.build(db_schema, config)

    assert len(types) == 1
    type_ir = types[0]

    assert type_ir.name == "User"  # Renamed!
    assert type_ir.source_table.name == "user_accounts"  # Original reference preserved

    assert len(type_ir.fields) == 2  # pwd_hash is hidden!

    field_names = {f.name for f in type_ir.fields}
    assert "id" in field_names
    assert "registeredAt" in field_names  # Renamed!

    # Original column reference is preserved
    registered_at_field = next(f for f in type_ir.fields if f.name == "registeredAt")
    assert registered_at_field.source_column is not None
    assert registered_at_field.source_column.name == "created_at"


def test_ir_builder_hides_entire_table() -> None:
    db_schema = DatabaseSchema()
    ns = DatabaseSchemaNamespace(name="public")
    db_schema.namespaces["public"] = ns

    table = Table(
        name="internal_logs",
        schema="public",
        columns=[
            Column(
                name="id", type="int", nullable=False, is_primary_key=True, is_foreign_key=False
            ),
        ],
    )
    ns.tables["internal_logs"] = table

    config = GatewayConfig(tables={"internal_logs": TableConfig(hidden=True)})

    builder = IRBuilder(type_mapper=StubTypeMapper())
    types = builder.build(db_schema, config)

    assert len(types) == 0  # Table is completely hidden
