# Welcome to db-graphql-gateway

`db-graphql-gateway` is a powerful, database-agnostic library that automatically generates a fully-featured GraphQL schema from your existing database schema. It securely bridges your database directly to GraphQL, providing robust querying, mutation, pagination, and authorization capabilities out of the box without requiring manual schema definition.

Fast, extensible, and fully type-checked, `db-graphql-gateway` allows you to expose databases over GraphQL with minimal friction while retaining high performance and granular access control.

## Key Features

- **Database Agnostic**: Built on a pluggable `DatabaseAdapter` protocol. Currently supports:
  - PostgreSQL (via `asyncpg`)
  - MySQL/MariaDB (via `asyncmy`)
  - SQLite (via `aiosqlite`)
- **Zero-Memory Filtering (SQL Pushdown)**: All GraphQL filters, sorts, and limits are compiled directly into SQL at the database layer. No full-table scans in memory.
- **N+1 Safe Batching**: Leverages DataLoader patterns to automatically batch relationship queries (e.g., fetching a user and all their posts executes exactly two queries, not N+1).
- **Native Authorization**: Generates SQL AST predicates from your GraphQL context, pushing authorization logic directly down to the database query itself.
- **Strict Typing & Conformance**: Passes a rigorous cross-adapter conformance test suite ensuring identical behavior regardless of the underlying database engine.

## Example Usage

Here is a quick example of how you can instantiate the gateway and execute a query:

```python
import asyncio
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
from db_graphql_gateway.auth.authorization import AuthorizationEngine

async def main():
    # 1. Connect to your database
    adapter = PostgresAdapter(dsn="postgresql://user:password@localhost:5432/my_db")
    await adapter.connect()

    # 2. Configure the gateway
    config = GatewayConfig(enable_mutations=True)
    auth_engine = AuthorizationEngine()

    # 3. Build the GraphQL schema dynamically from the database schema
    schema_builder = GraphQLSchemaBuilder(adapter, config, auth_engine)
    schema = await schema_builder.build_schema()

    # 4. Execute a GraphQL query
    query = """
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
    """
    result = await schema.execute(query)
    print(result.data)

    await adapter.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## Why use db-graphql-gateway?

If you want to instantly securely expose an existing database as a GraphQL API without writing endless resolvers, `db-graphql-gateway` is the perfect fit. Unlike typical ORMs or monolithic frameworks, it strictly adheres to **SQL pushdown**—meaning your application memory stays flat regardless of the size of the tables you're querying.
