from typing import Any
import os
import threading
import yaml
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
from db_graphql_gateway.database.adapters.mysql.adapter import MySQLAdapter
from db_graphql_gateway.schema.ir.builder import IRBuilder
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

app = FastAPI(title="GraphQL Gateway Integration Test")

# ---------------------------------------------------------------------------
# SQLite query counter — incremented by aiosqlite trace callback.
# Thread-safe via a lock since aiosqlite calls the callback from its
# internal worker thread.
# ---------------------------------------------------------------------------
_sqlite_query_count: int = 0
_sqlite_query_lock = threading.Lock()


def _sqlite_trace_callback(stmt: str) -> None:  # pragma: no cover
    """Called by aiosqlite for every SQL statement issued on the connection."""
    global _sqlite_query_count
    # Ignore PRAGMA statements that aiosqlite issues internally at connect time
    if not stmt.strip().upper().startswith("PRAGMA"):
        with _sqlite_query_lock:
            _sqlite_query_count += 1


@app.get("/admin/query-count")
async def get_query_count() -> JSONResponse:
    """Return the current SQLite statement count (SQLite mode only)."""
    with _sqlite_query_lock:
        return JSONResponse({"count": _sqlite_query_count})


@app.get("/admin/query-count/reset")
async def reset_query_count() -> JSONResponse:
    """Reset the SQLite statement counter to 0."""
    global _sqlite_query_count
    with _sqlite_query_lock:
        _sqlite_query_count = 0
    return JSONResponse({"count": 0})


# Load Config
config_path = os.getenv("SGQL_CONFIG", "sgql.yaml")
with open(config_path, "r") as f:
    config_data = yaml.safe_load(f)
gateway_config = GatewayConfig(**config_data)

dsn = os.getenv(
    "SGQL_DATABASE_URL", "postgresql://sgql_test:sgql_password@localhost:5433/sgql_test_db"
)

adapter: Any
if dsn.startswith("postgresql"):
    adapter = PostgresAdapter(dsn=dsn)
elif dsn.startswith("sqlite"):
    path = dsn.replace("sqlite:///", "")
    adapter = SQLiteAdapter(path=path)
elif dsn.startswith("mysql"):
    adapter = MySQLAdapter(database="todo_parse_dsn")
else:
    raise ValueError(f"Unsupported DSN scheme: {dsn}")


@app.on_event("startup")
async def startup() -> None:
    await adapter.connect()

    # Auth setup
    from db_graphql_gateway.auth.jwt_provider import JWTAuthenticationProvider
    from db_graphql_gateway.auth.authorization import AuthorizationEngine, TablePolicy, PolicyRule

    auth_provider = None
    auth_engine = None

    auth_config = config_data.get("auth", {})
    if auth_config:
        for provider in auth_config.get("providers", []):
            if provider.get("type") == "jwt":
                auth_provider = JWTAuthenticationProvider(
                    secret_or_key=provider.get("secret"),
                    algorithms=[provider.get("algorithm")] if provider.get("algorithm") else None,
                    issuer=provider.get("issuer"),
                    audience=provider.get("audience"),
                )
                break

        policies = []
        for rule in auth_config.get("rules", []):
            predicate = rule.get("predicate", "")
            if "=" in predicate:
                left, right = [p.strip() for p in predicate.split("=", 1)]
                col = left.strip("{}")
                claim = right.strip("{}").replace("jwt.", "$claims.")
                policies.append(
                    TablePolicy(
                        table=rule.get("target"),
                        read_rules=[PolicyRule(column=col, op="eq", value_template=claim)],
                    )
                )
        auth_engine = AuthorizationEngine(policies=policies)

    # Wire up SQLite query counter via trace callback
    if isinstance(adapter, SQLiteAdapter) and adapter._conn is not None:
        await adapter._conn.set_trace_callback(_sqlite_trace_callback)

    # 1. Inspect DB
    inspector = adapter.inspector()
    db_schema = await inspector.discover_schema()

    # 2. Build IR
    ir_builder = IRBuilder(type_mapper=adapter.type_mapper())
    ir = ir_builder.build(db_schema=db_schema, config=gateway_config)

    # 3. Build GraphQL Schema
    schema_builder = GraphQLSchemaBuilder(db_adapter=adapter, auth_engine=auth_engine)

    extensions: list[Any] = []
    security_config = config_data.get("security", {})
    if security_config:
        from strawberry.extensions import QueryDepthLimiter, MaxAliasesLimiter

        max_depth = security_config.get("max_depth")
        max_aliases = security_config.get("max_aliases")
        if max_depth:
            extensions.append(QueryDepthLimiter(max_depth=max_depth))
        if max_aliases:
            extensions.append(MaxAliasesLimiter(max_alias_count=max_aliases))

    schema = schema_builder.build(ir_types=ir, db_schema=db_schema, extensions=extensions)

    # 4. Mount Router
    graphql_router = make_graphql_router(schema, auth_provider=auth_provider)
    app.include_router(graphql_router)
    print("Gateway started and router mounted.")


@app.on_event("shutdown")
async def shutdown() -> None:
    await adapter.close()


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
