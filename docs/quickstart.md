# Quickstart

This guide will walk you through spinning up a full FastAPI GraphQL server over a PostgreSQL database in just a few minutes.

## 1. Installation

Install the Gateway along with `fastapi` and an ASGI server:

```bash
uv add db-graphql-gateway fastapi uvicorn
```

## 2. Server Example

Here is a complete example of connecting to your database, building the IR, generating the Strawberry schema, and mounting it in FastAPI.

```python
import asyncio
from fastapi import FastAPI
import uvicorn

from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.builder import IRBuilder
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

async def main():
    dsn = "postgresql://postgres:postgres@localhost:5432/postgres"
    
    # 1. Connect and Inspect Database
    adapter = PostgresAdapter(dsn)
    await adapter.connect()
    
    inspector = PostgresSchemaInspector(adapter.pool)
    db_schema = await inspector.discover_schema()

    # 2. Build Intermediate Representation (IR)
    # The config allows you to hide tables or rename fields. 
    # By default, it auto-hides sensitive fields like 'password' and 'token'.
    config = GatewayConfig()
    ir_builder = IRBuilder(type_mapper=adapter.type_mapper())
    ir_types = ir_builder.build(db_schema, config)

    # 3. Generate Strawberry GraphQL Schema
    schema_builder = GraphQLSchemaBuilder(
        db_adapter=adapter,
        max_page_size=100, # Prevents clients from requesting too many rows
    )
    schema = schema_builder.build(ir_types, db_schema=db_schema)

    # 4. Mount on FastAPI
    app = FastAPI()
    router = make_graphql_router(schema)
    app.include_router(router)

    config = uvicorn.Config(app, port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
```

> [!TIP]
> **Authentication headers** are automatically extracted by the `make_graphql_router` and passed into the `AuthContext`. If you pass an `Authorization: Bearer <jwt>` header in your requests, the underlying `AuthorizationEngine` (if configured) will securely filter database rows!

## 3. Explore the API

Once the server is running, navigate to [http://localhost:8000/graphql](http://localhost:8000/graphql).

You will see the **GraphiQL** interface where you can explore the automatically generated Schema Docs and execute queries.

### Example: Nested Query with Pagination

```graphql
query GetActiveUsers {
  users_connection(
    first: 10,
    where: { is_active: { eq: true } },
    order_by: [{ field: created_at, direction: DESC }]
  ) {
    edges {
      node {
        id
        email
        # O(1) batched DataLoader resolution!
        tasks {
          id
          title
        }
      }
    }
  }
}
```

## 4. The CLI (`sgql`)

You can use the built-in CLI for various administrative and CI tasks.

```bash
# Check if the database connection and schema are healthy
sgql doctor postgresql://user:pass@localhost:5432/db

# Audit your schema for security flaws (depth limits, complexity, masked errors)
sgql security postgresql://user:pass@localhost:5432/db

# Validate your GatewayConfig overrides (sgql.yaml)
sgql validate --config sgql.yaml
```
