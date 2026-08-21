# Welcome to db-graphql-gateway

`db-graphql-gateway` is a production-grade, reusable Python package that automatically generates a secure, optimized GraphQL API directly from your database connection. It acts as a bridge between your database and GraphQL, translating GraphQL queries into efficient, parameterized SQL without requiring you to manually write resolvers, define schemas, or worry about the typical pitfalls of database-to-API integrations.

## Core Principles & Context

This project was built from the ground up to solve the most difficult problems in exposing databases over GraphQL. It adheres strictly to the following principles:

- **No ORM Required**: The database itself is the source of truth. You don't need to define models in SQLAlchemy, SQLModel, Django, or Prisma just to get a GraphQL API. (Though optional integrations can be layered on top).
- **Security First**: Authentication and Authorization are treated as separate concerns. Authorization is implemented as **SQL predicates** integrated deep in the query planner, meaning data filtering happens at the database engine level. We never fetch rows into Python memory only to discard them.
- **Performance & N+1 Prevention**: A sophisticated, request-scoped DataLoader pattern is implemented for relationship batching. Combined with integrated authorization predicates, it guarantees O(1) database queries per relationship depth, completely avoiding N+1 query problems.
- **Zero Raw SQL Exposure**: Clients never provide SQL fragments. All filters, sorting rules, and pagination constraints are strictly typed GraphQL arguments, protecting you from injection attacks.
- **Schema Decoupling**: We use a powerful 3-tier architecture: `Database Introspection` -> `Intermediate Representation (IR)` -> `GraphQL Schema`. This decoupled approach allows you to inject YAML configurations (`sgql.yaml`) to rename fields, hide columns, or mutate the graph before it is ever exposed to the client.

## Architecture Highlights

1. **Introspection Phase**: The gateway connects to your database (PostgreSQL, MySQL, SQLite) and introspects tables, columns, primary keys, foreign keys, constraints, and views.
2. **Intermediate Representation (IR)**: It converts this database schema into a database-agnostic, GraphQL-agnostic IR. This is where configurations are merged to override names or visibility.
3. **GraphQL Generation**: The IR is used to dynamically build a fully-typed Strawberry GraphQL schema, including root queries, single-object lookups, list queries, filters, and mutations.
4. **Query Execution**: When a query hits, the Query Planner parses the AST, applies authorization policies, merges filters, and generates highly optimized SQL (using `EXISTS`, `JOIN`, `IN`) to fulfill the request.

## Example Usage

Here is a quick example of how you can instantiate the gateway and execute a query securely:

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

    # 3. Build the GraphQL schema dynamically
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

## Security & Hardening

Out of the box, `db-graphql-gateway` provides robust security controls:
- **Complexity Budgets**: Rejects wildly nested or computationally expensive queries.
- **Depth & Alias Limits**: Prevents denial-of-service via query expansion.
- **Tenant-Level Policies**: Row-level security translated to SQL `WHERE` clauses.
- **Masking & Safety**: Production introspection lockdown and sensitive-field protection by default.

Whether you're building a massive multi-tenant SaaS or just want to quickly expose a read-only dashboard over a SQLite file, `db-graphql-gateway` is designed to be the most reliable, decoupled, and performant bridge available in Python.
