from pydantic import BaseModel, Field


class FieldConfig(BaseModel):
    graphql_name: str | None = None
    hidden: bool | None = None


class TableConfig(BaseModel):
    graphql_name: str | None = None
    hidden: bool | None = None
    fields: dict[str, FieldConfig] = Field(default_factory=dict)


class GatewayConfig(BaseModel):
    tables: dict[str, TableConfig] = Field(default_factory=dict)
    sensitive_field_patterns: list[str] = Field(
        default_factory=lambda: ["password", "pwd", "secret", "token", "hash"]
    )
