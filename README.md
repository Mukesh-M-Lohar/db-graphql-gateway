# db-graphql-gateway

[![PyPI version](https://badge.fury.io/py/db-graphql-gateway.svg)](https://badge.fury.io/py/db-graphql-gateway)
[![Documentation](https://img.shields.io/badge/docs-MkDocs-blue.svg)](https://forgedlohar.github.io/db-graphql-gateway/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/ci.yml)
[![Integration](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/integration.yml/badge.svg)](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/integration.yml)
[![Conformance](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/conformance.yml/badge.svg)](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/conformance.yml)
[![Docs](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/docs.yml/badge.svg)](https://github.com/forgedlohar/db-graphql-gateway/actions/workflows/docs.yml)

> **📚 Full Documentation:** [forgedlohar.github.io/db-graphql-gateway](https://forgedlohar.github.io/db-graphql-gateway/)  
> **🐙 GitHub Repository:** [forgedlohar/db-graphql-gateway](https://github.com/forgedlohar/db-graphql-gateway)

A production-grade, reusable Python package that automatically generates a secure, optimized GraphQL API directly from your database connection. 

It acts as a bridge between your database and GraphQL, translating GraphQL queries into efficient, parameterized SQL without requiring you to manually write resolvers, define schemas, or worry about the typical pitfalls of database-to-API integrations.

![GraphiQL IDE showing a nested query against db-graphql-gateway with 3 DB queries total](docs/assets/graphiql_demo.gif)

> *Live GraphiQL explorer at `localhost:8000/graphql` — zero resolver code written. **3 queries total** for a depth-3 nested query across 5 users.*

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

## 🤝 Contributing

We welcome contributions! Whether it's fixing a typo, adding a new database adapter, or improving performance, your help is appreciated. 

Please see our [Contributing Guide](CONTRIBUTING.md) for details on how to get started, run tests, and submit pull requests.
