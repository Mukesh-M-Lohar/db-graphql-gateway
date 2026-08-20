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
from fastapi import FastAPI
from db_graphql_gateway import GraphQLGateway

app = FastAPI(title="GraphQL Gateway")

# 1. Initialize the Gateway
gateway = GraphQLGateway(
    database_url="postgresql://postgres:password@localhost:5432/my_database",
    schema="public"
)

# 2. Build the Schema at Startup
@app.on_event("startup")
async def startup():
    await gateway.build_schema()

# 3. Mount the GraphQL Router
app.include_router(gateway.get_router(), prefix="/graphql")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

!!! tip "Database Configuration"
    Make sure to replace `postgresql://postgres:password@localhost:5432/my_database` with your actual database connection string.

---

## 3. Explore the API

Start your server:

```bash
python main.py
```

Open your browser and navigate to the built-in GraphiQL IDE at:

> [**http://localhost:8000/graphql**](http://localhost:8000/graphql)

### Example: Nested Query with Pagination

Thanks to `db-graphql-gateway`, you can immediately execute deeply nested queries without worrying about the N+1 problem.

=== "Query"
    ```graphql
    query GetUsersWithPosts {
      users(first: 10) {
        edges {
          node {
            id
            email
            created_at
            posts(first: 5) {
              edges {
                node {
                  id
                  title
                }
              }
            }
          }
        }
      }
    }
    ```

=== "Response"
    ```json
    {
      "data": {
        "users": {
          "edges": [
            {
              "node": {
                "id": "1",
                "email": "alice@example.com",
                "created_at": "2024-01-01T00:00:00",
                "posts": {
                  "edges": [
                    {
                      "node": {
                        "id": "101",
                        "title": "Hello World"
                      }
                    }
                  ]
                }
              }
            }
          ]
        }
      }
    }
    ```

---

## 4. The CLI (`sgql`)

You can use the built-in CLI for various administrative and CI tasks directly from your terminal.

```bash
# Check if the database connection and schema are healthy
sgql doctor postgresql://user:pass@localhost:5432/db

# Audit your schema for security flaws (depth limits, complexity, masked errors)
sgql security postgresql://user:pass@localhost:5432/db

# Validate your GatewayConfig overrides (sgql.yaml)
sgql validate --config sgql.yaml
```
