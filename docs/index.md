---
hide:
  - navigation
---

# db-graphql-gateway

A production-grade, reusable Python package that automatically generates a secure, optimized GraphQL API directly from your database connection. 

It acts as a bridge between your database and GraphQL, translating GraphQL queries into efficient, parameterized SQL without requiring you to manually write resolvers, define schemas, or worry about the typical pitfalls of database-to-API integrations.

---

<div class="grid cards" markdown>

-   :material-database: **No ORM Required**
    ---
    The database itself is the source of truth. You don't need to define models in SQLAlchemy, SQLModel, Django, or Prisma just to get a GraphQL API.

-   :material-security: **Security First**
    ---
    Authentication and Authorization are treated as separate concerns. Authorization is implemented as **SQL predicates**, meaning data filtering happens deep at the database engine level.

-   :material-rocket-launch: **N+1 Prevention Guarantee**
    ---
    A sophisticated, request-scoped DataLoader pattern is wired up automatically. Combined with integrated authorization predicates, it guarantees **O(1) database queries per relationship depth**.

-   :material-shield-check: **Zero Raw SQL Exposure**
    ---
    Clients never provide SQL fragments. All filters, sorting rules, and pagination constraints are strictly typed GraphQL arguments, protecting you from SQL injection.

</div>

---

## 🏗 Architecture Highlights

The system is decoupled into three primary layers, giving you total control before the schema is ever exposed to the client.

1. **Introspection**: Connects to PostgreSQL, MySQL, or SQLite and introspects tables, columns, primary keys, foreign keys, and views.
2. **Intermediate Representation (IR)**: Converts the raw DB schema into a database-agnostic IR. This is where your YAML configurations (`sgql.yaml`) override names or hide sensitive fields.
3. **GraphQL Generation**: The IR dynamically builds a fully-typed Strawberry GraphQL schema.
4. **Query Execution**: ASTs are parsed, authorization policies are merged, and highly optimized SQL (`EXISTS`, `JOIN`, `IN`) is generated to fulfill the request.

---

## ⚡ Quick Example

Here is a quick example of how you can instantiate the gateway and execute a query securely:

=== "Python Application"

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

=== "GraphQL Output"

    ```json
    {
      "data": {
        "users": {
          "edges": [
            {
              "node": {
                "id": "1",
                "username": "alice",
                "posts": [
                  { "title": "My first post" },
                  { "title": "GraphQL is awesome" }
                ]
              }
            }
          ]
        }
      }
    }
    ```

---

## 🔒 Security & Hardening

Out of the box, `db-graphql-gateway` provides robust security controls:

!!! abstract "Built-in Defenses"
    - **Complexity Budgets**: Rejects wildly nested or computationally expensive queries.
    - **Depth & Alias Limits**: Prevents denial-of-service via query expansion.
    - **Tenant-Level Policies**: Row-level security translated to SQL `WHERE` clauses.
    - **Masking & Safety**: Production introspection lockdown and sensitive-field protection by default.

Whether you're building a massive multi-tenant SaaS or just want to quickly expose a read-only dashboard over a SQLite file, `db-graphql-gateway` is designed to be the most reliable, decoupled, and performant bridge available in Python.
