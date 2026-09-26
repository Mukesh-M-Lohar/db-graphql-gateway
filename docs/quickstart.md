# Quickstart

This guide will walk you through spinning up a full FastAPI GraphQL server over a PostgreSQL, SQLite, or MySQL database in just a few minutes.

## 1. Installation

Install the Gateway along with `fastapi` and an ASGI server:

=== "pip"

    ```bash
    pip install "db-graphql-gateway[fastapi]" uvicorn
    ```

=== "uv"

    ```bash
    uv add "db-graphql-gateway[fastapi]" uvicorn
    ```

---

## 2. Server Example

Here is a complete, production-ready example that connects to your database, introspects it, builds the GraphQL schema, and mounts it in FastAPI.

=== "PostgreSQL"

    ```python
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    import uvicorn

    from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
    from db_graphql_gateway.schema.config import GatewayConfig
    from db_graphql_gateway.schema.ir.builder import IRBuilder
    from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
    from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

    adapter = PostgresAdapter(dsn="postgresql://user:password@localhost:5432/my_db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await adapter.connect()

        inspector = adapter.inspector()
        db_schema = await inspector.discover_schema()

        ir = IRBuilder(type_mapper=adapter.type_mapper()).build(
            db_schema=db_schema, config=GatewayConfig()
        )
        schema = GraphQLSchemaBuilder(db_adapter=adapter).build(
            ir_types=ir, db_schema=db_schema
        )

        app.include_router(make_graphql_router(schema))
        yield

        await adapter.close()

    app = FastAPI(title="My GraphQL API", lifespan=lifespan)

    if __name__ == "__main__":
        uvicorn.run("main:app", host="0.0.0.0", port=8000)
    ```

=== "SQLite"

    ```python
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    import uvicorn

    from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
    from db_graphql_gateway.schema.config import GatewayConfig
    from db_graphql_gateway.schema.ir.builder import IRBuilder
    from db_graphql_gateway.graphql.builder import GraphQLSchemaBuilder
    from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

    adapter = SQLiteAdapter(path="my_database.sqlite")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await adapter.connect()

        inspector = adapter.inspector()
        db_schema = await inspector.discover_schema()

        ir = IRBuilder(type_mapper=adapter.type_mapper()).build(
            db_schema=db_schema, config=GatewayConfig()
        )
        schema = GraphQLSchemaBuilder(db_adapter=adapter).build(
            ir_types=ir, db_schema=db_schema
        )

        app.include_router(make_graphql_router(schema))
        yield

        await adapter.close()

    app = FastAPI(title="My GraphQL API", lifespan=lifespan)

    if __name__ == "__main__":
        uvicorn.run("main:app", host="0.0.0.0", port=8000)
    ```

---

## 3. Schema Configuration (`sgql.yaml`)

Place a `sgql.yaml` alongside your server to customize the schema without code changes:

```yaml
models:
  - name: users
    fields:
      - name: email
        is_sensitive: true   # hidden from the GraphQL schema

auth:
  providers:
    - type: jwt
      issuer: "https://my-auth-server.com"
      audience: "my-api"
      secret: "your-hs256-secret"   # or use 'public_key' for RS256
      algorithm: "HS256"
  rules:
    - target: posts
      predicate: "{user_id} = {jwt.user_id}"   # row-level policy
    - target: comments
      predicate: "{user_id} = {jwt.user_id}"

security:
  max_depth: 8
  max_aliases: 15
  max_complexity: 100
```

Load it at startup:

```python
import yaml
from db_graphql_gateway.schema.config import GatewayConfig

with open("sgql.yaml") as f:
    config = GatewayConfig(**yaml.safe_load(f))
```

---

## 4. Authentication

### JWT (built-in)

The gateway ships with a `JWTAuthenticationProvider` for HS256 and RS256 tokens:

```python
from db_graphql_gateway.auth.jwt_provider import JWTAuthenticationProvider
from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

auth_provider = JWTAuthenticationProvider(
    secret_or_key="your-secret",
    algorithms=["HS256"],
    issuer="https://my-auth-server.com",
    audience="my-api",
)

router = make_graphql_router(schema, auth_provider=auth_provider)
```

### OIDC / OAuth2 (via FastAPI dependencies)

For OIDC or any custom auth flow, pass a `context_getter` directly — the gateway forwards all `**kwargs` to Strawberry's `GraphQLRouter`:

```python
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def my_oidc_context(
    request: Request,
    token: str = Depends(oauth2_scheme),
) -> dict:
    # Validate token with your OIDC provider here
    user = await verify_oidc_token(token)
    return {"request": request, "user": user}

router = make_graphql_router(schema, context_getter=my_oidc_context)
```

!!! tip "Any FastAPI dependency works"
    Because `make_graphql_router` passes `**kwargs` to `strawberry.fastapi.GraphQLRouter`, any FastAPI dependency injection pattern — including `HTTPBearer`, `OpenIdConnect`, or a custom class — works exactly as you'd expect.

---

## 5. Explore the API

Start your server:

```bash
uvicorn main:app --reload
```

Open your browser and navigate to the built-in GraphiQL IDE:

> [**http://localhost:8000/graphql**](http://localhost:8000/graphql)

### Example: Nested Query with Pagination

Thanks to the built-in DataLoader, you can immediately execute deeply nested queries. The gateway guarantees **exactly one SQL query per relationship depth level** — not one per row.

=== "GraphQL Query"
    ```graphql
    query GetUsersWithPosts {
      users_connection(first: 10) {
        edges {
          node {
            id
            username
            posts {
              id
              title
              comments {
                id
                body
              }
            }
          }
        }
      }
    }
    ```

=== "SQL Issued (3 queries total, not 1+N+N²)"
    ```sql
    -- Depth 1: fetch users
    SELECT * FROM users LIMIT 10;

    -- Depth 2: fetch ALL posts for those users in ONE batched query
    SELECT * FROM posts WHERE user_id IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10);

    -- Depth 3: fetch ALL comments for those posts in ONE batched query
    SELECT * FROM comments WHERE post_id IN (101, 102, 103, ...);
    ```

---

## 6. The CLI (`sgql`)

Use the built-in CLI for diagnostics and CI tasks:

```bash
# Verify DB connection and introspect schema
sgql doctor --dsn postgresql://user:pass@localhost:5432/db

# Audit your schema config for security issues
sgql security --config sgql.yaml

# Validate sgql.yaml structure
sgql validate --config sgql.yaml
```
