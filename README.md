# db-graphql-gateway

[![PyPI version](https://badge.fury.io/py/db-graphql-gateway.svg)](https://badge.fury.io/py/db-graphql-gateway)
[![Documentation](https://img.shields.io/badge/docs-MkDocs-blue.svg)](https://Mukesh-M-Lohar.github.io/db-graphql-gateway/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/ci.yml)
[![Integration](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/integration.yml/badge.svg)](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/integration.yml)
[![Conformance](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/conformance.yml/badge.svg)](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/conformance.yml)
[![Docs](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/docs.yml/badge.svg)](https://github.com/Mukesh-M-Lohar/db-graphql-gateway/actions/workflows/docs.yml)

> **📚 Full Documentation:** [Mukesh-M-Lohar.github.io/db-graphql-gateway](https://Mukesh-M-Lohar.github.io/db-graphql-gateway/)  
> **🐙 GitHub Repository:** [Mukesh-M-Lohar/db-graphql-gateway](https://github.com/Mukesh-M-Lohar/db-graphql-gateway)

A production-grade, reusable Python package that automatically generates a secure, optimized GraphQL API directly from your database connection. 

It acts as a bridge between your database and GraphQL, translating GraphQL queries into efficient, parameterized SQL without requiring you to manually write resolvers, define schemas, or worry about the typical pitfalls of database-to-API integrations.

## 📦 Installation

Available on PyPI. Install via `pip` or `uv`:

```bash
pip install "db-graphql-gateway[fastapi]"
```

## ✨ Features

- **No ORM Required**: The database itself is the source of truth. You don't need to define models in SQLAlchemy, SQLModel, Django, or Prisma just to get a GraphQL API.
- **Security First**: Authentication and Authorization are treated as separate concerns. Authorization is implemented as **SQL predicates**, meaning data filtering happens deep at the database engine level.
- **N+1 Prevention Guarantee**: A sophisticated, request-scoped DataLoader pattern is wired up automatically. Combined with integrated authorization predicates, it guarantees **O(1) database queries per relationship depth**.
- **Zero Raw SQL Exposure**: Clients never provide SQL fragments. All filters, sorting rules, and pagination constraints are strictly typed GraphQL arguments, protecting you from SQL injection.
- **AST Security Limits**: Configured `max_depth` and `max_aliases` protections via `QueryDepthLimiter` and `MaxAliasesLimiter` to harden the gateway against expansive query attacks.

## ⚖️ How is this different?

There are several excellent tools in this space, but `db-graphql-gateway` makes very different architectural tradeoffs.

### vs. PostGraphile
[PostGraphile](https://www.graphile.org/postgraphile/) is a fantastic tool that heavily embraces the **Database as the Application Layer**. 
- **Database Lock-in**: PostGraphile is strictly bound to PostgreSQL. `db-graphql-gateway` uses a modular adapter system supporting Postgres, MySQL, and SQLite.
- **Authorization Model**: PostGraphile relies entirely on PostgreSQL's Row-Level Security (RLS) and database `GRANT` roles. You must create database users/roles for your API clients. `db-graphql-gateway` keeps authorization at the **Application Tier**. It uses an `AuthorizationEngine` that evaluates Python rules and pushes them down into the SQL AST automatically. You only need a single database connection.

### vs. Supabase / pg_graphql
[pg_graphql](https://supabase.github.io/pg_graphql/) (the engine powering Supabase's GraphQL API) is an incredibly fast, native Postgres extension written in Rust.
- **Deployment**: `pg_graphql` runs *inside* the database as a native extension. This makes it blazingly fast, but many managed database providers (like AWS RDS) restrict installing custom extensions. `db-graphql-gateway` runs in your Python backend (e.g., as a FastAPI route), requiring zero modifications to your database server.
- **Extensibility**: Because `db-graphql-gateway` is a Python library, you can easily intercept the GraphQL context, inject custom Strawberry resolvers alongside the generated ones, or wrap the execution in custom ASGI middleware.

## ⚡ Quickstart Example

Here is a complete example of connecting to your database, building the GraphQL schema dynamically, and mounting it in FastAPI.

```python
import asyncio
import uvicorn
from fastapi import FastAPI
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.auth.authorization import AuthorizationEngine
from db_graphql_gateway.auth.providers import JWTAuthenticationProvider
import strawberry
from strawberry.fastapi import GraphQLRouter

# 1. Initialize the Database Adapter
# Other adapters (MySQLAdapter, SQLiteAdapter) are also available.
db_adapter = PostgresAdapter(dsn="postgresql://user:password@localhost:5432/my_db")

# 2. Configure Security & Authorization
auth_engine = AuthorizationEngine()
auth_provider = JWTAuthenticationProvider(secret_key="super-secret")
config = GatewayConfig()

async def lifespan(app: FastAPI):
    # Connect to the database on startup
    await db_adapter.connect()
    yield
    # Cleanup on shutdown
    await db_adapter.close()

app = FastAPI(lifespan=lifespan)

@app.on_event("startup")
async def setup_graphql():
    # 3. Build the GraphQL Schema dynamically from the database
    schema_builder = GraphQLSchemaBuilder(
        db_adapter=db_adapter, 
        config=config, 
        auth_engine=auth_engine
    )
    schema = await schema_builder.build_schema()
    
    # 4. Mount the Strawberry Router onto FastAPI
    graphql_app = GraphQLRouter(
        schema, 
        context_getter=lambda req: {"request": req, "auth_provider": auth_provider}
    )
    app.include_router(graphql_app, prefix="/graphql")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Example GraphQL Query

Once running, you can hit `http://localhost:8000/graphql` and execute complex relational queries:

```graphql
query {
  users(first: 10, filter: { isActive: { eq: true } }) {
    edges {
      node {
        id
        username
        posts {
          title
        }
      }
    }
  }
}
```

## 🏗 Architecture Highlights

The system is decoupled into three primary layers, giving you total control before the schema is ever exposed to the client.

1. **Introspection**: Connects to PostgreSQL, MySQL, or SQLite and introspects tables, columns, primary keys, foreign keys, and views.
2. **Intermediate Representation (IR)**: Converts the raw DB schema into a database-agnostic IR. This is where your YAML configurations override names or hide sensitive fields.
3. **GraphQL Generation**: The IR dynamically builds a fully-typed Strawberry GraphQL schema.
4. **Query Execution**: ASTs are parsed, authorization policies are merged, and highly optimized SQL (`EXISTS`, `JOIN`, `IN`) is generated to fulfill the request.
