# Quickstart

This guide will walk you through spinning up a full FastAPI GraphQL server over a PostgreSQL, SQLite, or MySQL database in just a few minutes.

## 1. Installation

Install the Gateway along with `fastapi` and an ASGI server:

```bash
uv add "db-graphql-gateway[fastapi]" uvicorn
```

## 2. Server Example

Here is a complete example of connecting to your database, building the GraphQL schema dynamically, and mounting it in FastAPI.

```python
import asyncio
import uvicorn
from fastapi import FastAPI
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

app = FastAPI(title="GraphQL Gateway")

# 1. Connect to DB and Configure
# Check the "Database Adapters" section below for your specific engine!
adapter = get_my_adapter() 
config = GatewayConfig()
schema_builder = GraphQLSchemaBuilder(adapter, config)

@app.on_event("startup")
async def startup():
    await adapter.connect()
    # 2. Introspects DB and builds the Schema
    schema = await schema_builder.build_schema()
    
    # 3. Mount the GraphQL Router
    graphql_router = make_graphql_router(schema)
    app.include_router(graphql_router, prefix="/graphql")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

### Database Adapters

Choose your underlying database engine and instantiate the correct adapter:

=== "PostgreSQL"
    ```python
    from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter

    def get_my_adapter():
        return PostgresAdapter(dsn="postgresql://postgres:password@localhost:5432/my_database")
    ```

=== "SQLite"
    ```python
    from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter

    def get_my_adapter():
        return SQLiteAdapter(path="my_database.sqlite")
    ```

=== "MySQL / MariaDB"
    ```python
    from db_graphql_gateway.database.adapters.mysql.adapter import MySQLAdapter

    def get_my_adapter():
        return MySQLAdapter(
            host="127.0.0.1",
            port=3306,
            user="root",
            password="password",
            database="my_database"
        )
    ```

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
# Use the correct DSN prefix (postgresql://, sqlite:///, mysql://) for your adapter
sgql doctor --dsn postgresql://user:pass@localhost:5432/db

# Audit your schema for security flaws (depth limits, complexity, masked errors)
sgql security --config sgql.yaml

# Validate your GatewayConfig overrides (sgql.yaml)
sgql validate --config sgql.yaml
```
