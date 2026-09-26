# Frequently Asked Questions

## Why build a custom Gateway instead of using Hasura or PostGraphile?

While tools like Hasura and PostGraphile are excellent, they often require deploying separate compiled binaries (Haskell, Node.js) and can be difficult to extend with custom Python business logic. 

`db-graphql-gateway` is a **native Python library** designed to be directly embedded within your existing asynchronous FastAPI applications. It allows you to leverage your existing Python ecosystem (e.g., PyJWT, Strawberry) while getting automated schema generation.

---

## Does this support MySQL or SQLite?

**Yes!** As of Phase 1, `db-graphql-gateway` ships with fully-supported, production-grade adapters for:
- PostgreSQL (`PostgresAdapter` via `asyncpg`)
- MySQL/MariaDB (`MySQLAdapter` via `asyncmy`)
- SQLite (`SQLiteAdapter` via `aiosqlite`)

It is completely database-agnostic. The query planner compiles filtering and authorization logic into standard SQL dialects through a plugin-based adapter architecture. 

---

## How does this solve the N+1 query problem?

GraphQL resolvers naively fetch nested relationship fields one at a time per parent row. The Gateway automatically wires **Strawberry DataLoaders** to all relationship fields. 

Rather than running 100 queries for 100 posts to fetch authors, the DataLoader collects all `author_id` keys and executes a single batched query: `SELECT * FROM users WHERE id IN ($1, $2, ...)`. 

!!! tip "O(1) Guarantee"
    This ensures that relationship fetching is always O(1) in database queries per relationship depth.

---

## How does Optimistic Concurrency work?

If a table has a column named `version` (of type integer), the Gateway automatically generates an `expected_version` argument for the update mutation.

When an update is requested with an `expected_version`:
1. The SQL query adds `AND version = $expected_version`.
2. The SQL query increments the version: `SET version = $expected_version + 1`.
3. If no rows are updated, the Gateway throws an `Optimistic concurrency failure` exception, ensuring no concurrent writes overwrite each other.

---

## How are Soft Deletes handled?

If a table contains a `deleted_at` timestamp column, the Gateway applies automatic soft-delete logic:

!!! success "Automatic Soft Deletion"
    - **Reads**: An implicit filter `deleted_at IS NULL` is applied to all queries and DataLoader batches.
    - **Deletes**: The generated `delete_<type>` mutation is converted into an update operation that sets `deleted_at = NOW()` rather than executing a destructive `DELETE` statement.

---

## Can I manually customize the generated GraphQL schema?

**Yes.** Because the Gateway builds a standard Strawberry `Schema` object, you can programmatically inject custom `strawberry.type` root fields, custom resolvers, mutations, or extensions before passing the final `Schema` to FastAPI. You can also hide tables or rename fields using the `sgql.yaml` configuration.

---

## Can I run this with Graphene or Ariadne?

**No**. The architecture is tightly coupled with **Strawberry GraphQL** because it relies heavily on modern Python type hints (`__annotations__`), dynamic `type()` generation, and native asynchronous DataLoaders.
