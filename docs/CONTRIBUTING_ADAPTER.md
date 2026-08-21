# Contributing a New Database Adapter

Thank you for your interest in expanding the database support of `db-graphql-gateway`! Our goal is to maintain a truly database-agnostic GraphQL interface. This means that users should be able to swap adapters without modifying their GraphQL schemas, authorization policies, or application code.

This guide explains the `DatabaseAdapter` protocol, how to build a new adapter, and how to prove it works using the **Cross-Adapter Conformance Suite**.

## The `DatabaseAdapter` Protocol

To integrate a new database engine (e.g., SQL Server, DuckDB, CockroachDB), you must implement the `DatabaseAdapter` interface (found in `src/db_graphql_gateway/database/adapters/interfaces.py`).

The adapter acts as a bridge between the engine-agnostic core (`GraphQLSchemaBuilder`, `AuthorizationEngine`) and the underlying database dialect.

### Key Components

1. **`DatabaseAdapter`**: Manages the connection pool, executes queries, and returns raw data.
2. **`SchemaInspector`**: Introspects the database to dynamically generate the canonical schema.
3. **`TypeMapper`**: Translates dialect-specific types (e.g., MySQL's `TINYINT(1)`) into abstract GraphQL IR types (`GraphQLType.BOOLEAN`).
4. **`QueryCompiler`**: Usually inherits from `BaseQueryCompiler` and overrides dialect-specific AST-to-SQL logic.

### Capability Flags

When configuring your `QueryCompiler` or `Adapter`, you may need to define capability flags that instruct the core gateway on how to handle the dialect's quirks:

- `supports_returning` (bool): Set to `True` if your engine supports `RETURNING` clauses (like Postgres). If `False` (like SQLite/MySQL), the gateway will automatically use a "SELECT-after-write" pattern.
- `supports_upsert_on_conflict` (bool): Set to `True` if your engine supports `ON CONFLICT DO UPDATE` or `ON DUPLICATE KEY UPDATE`.

!!! note "SELECT-after-write"
    If `supports_returning` is `False`, the `BaseQueryCompiler` will dynamically set `fetch_after_write = True` on the `CompiledQuery` returned during mutations. Your adapter's `execute()` method must intercept this and perform the secondary select using `cursor.lastrowid` or the known primary key.
- `placeholder_style` (enum/string): e.g., `?` for SQLite, `%s` for MySQL, `$1` for Postgres. Ensures parameterized queries match the underlying driver's expectations.

## Building a New Adapter: Worked Example (SQLite)

Let's look at how SQLite was implemented.

### 1. Connection & Execution
```python
class SQLiteAdapter(DatabaseAdapter):
    async def execute_query(self, query: str, params: list[Any]) -> list[dict[str, Any]]:
        async with self.pool.acquire() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

### 2. Query Compilation
Inherit from `BaseQueryCompiler` to get 90% of ANSI SQL behavior for free.
```python
class SQLiteQueryCompiler(BaseQueryCompiler):
    def __init__(self):
        super().__init__()
        self.placeholder = "?"
        self.supports_returning = False
```

### 3. Engine Gotchas (Checklist)

Before building, verify the following against your driver:
- [ ] **Placeholder Style**: Does the driver use `?`, `%s`, `:name`, or `$1`?
- [ ] **Identifier Quoting**: Does it use `""` (Postgres/SQLite) or `\`\`` (MySQL)? Override `quote_identifier()` in your compiler.
- [ ] **Boolean Types**: Does the engine lack a native `BOOLEAN`? Ensure your `TypeMapper` intercepts it (e.g., `TINYINT(1) -> BOOLEAN`).
- [ ] **Upsert Syntax**: Does it use `ON CONFLICT` or `ON DUPLICATE KEY UPDATE`?

### Explicit Non-Goals
The `DatabaseAdapter` protocol does **not** need to support highly proprietary, engine-specific extensions (e.g., Postgres PostGIS, Oracle XMLType) if there is no cross-engine equivalent. Expose these via adapter-level opt-in configuration, not by muddying the core protocol.

## Passing the Conformance Suite

Your PR **will not be merged** unless it passes the Conformance Suite. This suite runs identical GraphQL queries against all adapters to guarantee 100% behavioral parity (including pagination, relationships, and authorization pushdowns).

### How to hook into the Conformance Suite:

1. Open `tests/conformance/conftest.py`.
2. Add your engine to the parameter matrix:
   ```python
   @pytest_asyncio.fixture(params=["sqlite", "mysql", "postgres", "your_engine"])
   ```
3. Update the `db_adapter` fixture to provision your engine (use `testcontainers` if it requires a daemon). The fixture must use the generic `get_ddl("your_engine")` string to instantiate the canonical schema:
   ```python
   elif engine == "your_engine":
       # Setup your engine here
       for stmt in get_ddl("your_engine"):
           await conn.execute(stmt)
   ```
4. Run the suite: `uv run pytest tests/conformance/ -k "db_adapter[your_engine]"`

If your compiler and type mapper are correct, all tests will pass without writing a single line of test code!

## Entry Points & Packaging

To keep the core package lightweight, third-party adapters should be published as separate packages (e.g., `db-graphql-gateway-duckdb`).

Register your adapter in your `pyproject.toml` so the gateway can auto-discover it:
```toml
[project.entry-points."db_graphql_gateway.adapters"]
duckdb = "my_duckdb_package.adapter:DuckDBAdapter"
```
Users will then configure the gateway with `engine="duckdb"` and the plugin system will handle the rest.
