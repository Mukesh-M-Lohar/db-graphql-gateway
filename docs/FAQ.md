# Frequently Asked Questions

## Deployment & Infrastructure

### Why build a custom Gateway instead of using Hasura or PostGraphile?
While tools like Hasura and PostGraphile are excellent, they often require deploying separate compiled binaries (Haskell, Node.js) and can be difficult to extend with custom Python business logic. 

`db-graphql-gateway` is a **native Python library** designed to be directly embedded within your existing asynchronous FastAPI applications. It allows you to leverage your existing Python ecosystem (e.g., PyJWT, Strawberry) while getting automated schema generation.

### Does sgql require any special infrastructure?
No, it is a native Python library designed to be embedded directly into FastAPI (or any ASGI server). There are no external binaries (like Haskell or Go) required.

### Can I run multiple instances behind a load balancer?
Yes, the gateway is completely stateless. You can scale it horizontally behind any load balancer.

### How do I handle zero-downtime deploys when the DB schema changes?
By setting `auto_expose: false` in your `sgql.yaml`, any new tables or columns introduced during a database migration are hidden by default. This ensures your GraphQL schema won't change unexpectedly and break clients until you explicitly configure the new fields.

### Can I run this with Graphene or Ariadne?
**No**. The architecture is tightly coupled with **Strawberry GraphQL** because it relies heavily on modern Python type hints (`__annotations__`), dynamic `type()` generation, and native asynchronous DataLoaders.

### Can I manually customize the generated GraphQL schema?
**Yes.** The Gateway allows both programatic extensions and config-driven schema control:
- **`sgql.yaml` Config**: You can hide tables, rename fields, or set explicit opt-in exposure (so only fields explicitly declared in your config are exposed, preventing new DB migrations from leaking columns into the public API).
- **Programmatic Customization**: Because the Gateway builds a standard Strawberry `Schema` object, you can programmatically inject custom `strawberry.type` root fields, custom resolvers, mutations, or extensions before passing the final `Schema` to FastAPI.

---

## Performance & Scaling

### How does it avoid N+1 queries under real production load?
GraphQL resolvers naively fetch nested relationship fields one at a time per parent row. The Gateway automatically wires **Strawberry DataLoaders** to all relationship fields. 

Rather than running 100 queries for 100 posts to fetch authors, the DataLoader collects all `author_id` keys and executes a single batched query: `SELECT * FROM users WHERE id IN ($1, $2, ...)`. 

!!! tip "O(1) Guarantee"
    This ensures that relationship fetching is always O(1) in database queries per relationship depth.

### What stops a malicious or careless client from sending an expensive query?
The gateway enforces configurable AST limits before the query ever hits the database. You can define `max_depth`, `max_aliases`, and `max_complexity` in your `sgql.yaml` to proactively reject expensive queries.

### Does it support pagination out of the box?
Yes, it natively supports Relay-style cursor pagination (`first`, `after`) with global configurable ceilings (e.g. `max_page_size: 100`) to prevent excessive data fetching.

---

## Security

### How is authorization enforced?
Authorization policies are compiled directly into SQL `WHERE` predicates (e.g., `WHERE tenant_id = $1`). This prevents unauthorized rows from ever leaving the database engine, offering true zero-memory filtering.

### Is raw SQL ever exposed to clients?
Never. Clients construct queries using strictly typed GraphQL filters (like `{ id: { eq: 5 } }`). The query planner converts these AST nodes into parameterized SQL using the dialect's secure placeholders (e.g., `$1` or `?`). In production, you can enable `error_masking` in `sgql.yaml` to hide database tracebacks.

### Can sensitive columns be hidden from the generated schema?
Yes. Columns matching `sensitive_field_patterns` (like `password`, `token`) are automatically redacted during introspection. You can also manually set `hidden: true` for any table or column in `sgql.yaml`.

### Is introspection safe to leave enabled in production?
Usually no. You can lock down introspection in production by setting `disable_introspection: true` in `sgql.yaml` to prevent attackers from downloading your entire API structure.

### Does it support multi-tenant row-level isolation?
Absolutely. You can define a `TablePolicy` that links a database column (like `tenant_id`) directly to a JWT claim (`$claims.tenant_id`). The gateway will inject this into every query, guaranteeing row-level tenant isolation.

---

## Database Compatibility

### Which databases are supported today?
**Yes!** As of Phase 1, `db-graphql-gateway` ships with fully-supported, production-grade adapters for:
- PostgreSQL (`PostgresAdapter` via `asyncpg`)
- MySQL/MariaDB (`MySQLAdapter` via `asyncmy`)
- SQLite (`SQLiteAdapter` via `aiosqlite`)

It is completely database-agnostic. The query planner compiles filtering and authorization logic into standard SQL dialects through a plugin-based adapter architecture. 

### Can I add support for a database that isn't listed?
Yes, you can implement the `DatabaseAdapter` protocol to plug in any custom database dialect or async driver. (See the [Adapter Development Guide](CONTRIBUTING_ADAPTER.md)).

### Does behavior differ across database adapters?
The core GraphQL schema generation and query planner logic remain identical. The only differences are handled internally by the adapter (like mapping types and formatting SQL placeholders).

---

## Data Mutation & Consistency

### How does Optimistic Concurrency work?
If a table has a column named `version` (of type integer), the Gateway automatically generates an `expected_version` argument for the update mutation.

When an update is requested with an `expected_version`:
1. The SQL query adds `AND version = $expected_version`.
2. The SQL query increments the version: `SET version = $expected_version + 1`.
3. If no rows are updated, the Gateway throws an `Optimistic concurrency failure` exception, ensuring no concurrent writes overwrite each other.

### How are Soft Deletes handled?
If a table contains a `deleted_at` timestamp column, the Gateway applies automatic soft-delete logic:

!!! success "Automatic Soft Deletion"
    - **Reads**: An implicit filter `deleted_at IS NULL` is applied to all queries and DataLoader batches.
    - **Deletes**: The generated `delete_<type>` mutation is converted into an update operation that sets `deleted_at = NOW()` rather than executing a destructive `DELETE` statement.

---

## Observability & Operations

### How do I monitor query cost and performance in production?
Since it's built on Strawberry GraphQL, you can utilize standard Strawberry extensions for tracing (such as OpenTelemetry or Apollo Tracing) to monitor resolver execution times and query complexity.

### What happens when a query is rejected for exceeding complexity/depth limits?
The gateway immediately throws a GraphQL validation error before attempting database execution. This prevents any database load and informs the client which limit was breached.

---

## Versioning & Support

### Is this project stable enough for production use?
Yes, the core engine, security features, pagination, and multi-dialect support are stable and covered by extensive integration tests. All core development phases have been successfully completed.

### Is it free to use commercially?
Yes, `db-graphql-gateway` is open-source and free to use. (See the LICENSE file in the repository root for exact terms).

### Where do I report a bug or request a feature?
You can report bugs or request features by opening an issue on the project's GitHub repository.
