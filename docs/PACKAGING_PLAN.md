# Adapter Packaging & Migration Plan

This document outlines the architectural shift from bundling all database adapters inside the core `db-graphql-gateway` package to a decentralized, plugin-based ecosystem.

## Goal

- Keep `db-graphql-gateway` lean: no hard dependencies on heavy drivers like `asyncpg`, `asyncmy`, or `testcontainers`.
- Treat third-party adapters exactly like first-party adapters.
- Allow users to install only what they need (e.g., `pip install db-graphql-gateway db-graphql-gateway-postgres`).

## 1. Plugin Architecture (Python Entry Points)

We will use Python's native `importlib.metadata.entry_points` feature to allow external packages to register their adapters without modifying core code.

### Exposing an Adapter (Third-Party View)
A third-party adapter package (e.g., `db-graphql-gateway-duckdb`) will expose its adapter in `pyproject.toml` like this:

```toml
[project.entry-points."db_graphql_gateway.adapters"]
duckdb = "db_graphql_gateway_duckdb.adapter:DuckDBAdapter"
```

### Loading an Adapter (Core View)
The core package's gateway configuration will load adapters dynamically:

```python
import importlib.metadata

def load_adapter(engine_name: str, **kwargs) -> DatabaseAdapter:
    entry_points = importlib.metadata.entry_points(group="db_graphql_gateway.adapters")
    
    for ep in entry_points:
        if ep.name == engine_name:
            adapter_class = ep.load()
            return adapter_class(**kwargs)
            
    raise ValueError(f"No adapter registered for engine '{engine_name}'. Did you install it?")
```

## 2. Migration Strategy for Existing Adapters

Currently, `sqlite`, `mysql`, and `postgres` are bundled in `src/db_graphql_gateway/database/adapters/`. We will migrate them to standalone packages gracefully.

### Phase 1: Scaffolding (Non-Breaking)
1. Add the `load_adapter` entry-point logic to the core initialization flow.
2. Register the bundled adapters *internally* via the core `pyproject.toml`:
   ```toml
   [project.entry-points."db_graphql_gateway.adapters"]
   sqlite = "db_graphql_gateway.database.adapters.sqlite.adapter:SQLiteAdapter"
   mysql = "db_graphql_gateway.database.adapters.mysql.adapter:MySQLAdapter"
   postgres = "db_graphql_gateway.database.adapters.postgres.adapter:PostgresAdapter"
   ```
   *Users will immediately start using the plugin infrastructure unknowingly.*

### Phase 2: Standalone Packages
1. Create new repositories or subdirectories in a monorepo for `db-graphql-gateway-sqlite`, `db-graphql-gateway-mysql`, and `db-graphql-gateway-postgres`.
2. Move the dialect-specific code (`adapter.py`, `compiler.py`, `inspector.py`, `type_mapper.py`) into these new packages.
3. Define the entry points in their respective `pyproject.toml` files.

### Phase 3: Deprecation & Removal
1. In the core `db-graphql-gateway` package, replace the contents of `src/db_graphql_gateway/database/adapters/sqlite/` with a shim that imports from the new package.
2. If the user imports from the core path directly, raise a `DeprecationWarning`:
   ```python
   # src/db_graphql_gateway/database/adapters/sqlite/adapter.py
   import warnings
   try:
       from db_graphql_gateway_sqlite.adapter import SQLiteAdapter
   except ImportError:
       raise ImportError("The SQLite adapter is now a separate package. Please run `pip install db-graphql-gateway-sqlite`.")

   warnings.warn(
       "Importing from db_graphql_gateway.database.adapters is deprecated. Use the plugin registry.", 
       DeprecationWarning
   )
   ```
3. Release v2.0 where the internal adapter paths are fully removed.
