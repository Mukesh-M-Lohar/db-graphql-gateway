# Frequently Asked Questions (FAQ)

## Q: Why build a custom Gateway instead of using Hasura or PostGraphile?
While tools like Hasura and PostGraphile are excellent, they often require deploying separate compiled binaries (Haskell, Node.js) and can be difficult to extend with custom Python business logic. `db-graphql-gateway` is a native Python library designed to be directly embedded within your existing asynchronous FastAPI applications. It allows you to leverage your existing Python ecosystem (e.g., PyJWT, Strawberry) while getting automated schema generation.

## Q: Does this support MySQL or SQLite?
Currently, `db-graphql-gateway` is optimized exclusively for PostgreSQL due to its reliance on system catalog table introspection (`pg_class`, `pg_attribute`) and specific SQL syntax parameters (`$1`). An adapter interface exists, making it possible to implement a MySQL adapter in the future.

## Q: How does this solve the N+1 query problem?
GraphQL resolvers naively fetch nested relationship fields one at a time per parent row. The Gateway automatically wires **Strawberry DataLoaders** to all relationship fields. Rather than running 100 queries for 100 posts to fetch authors, the DataLoader collects all `author_id` keys and executes a single batched query: `SELECT * FROM users WHERE id IN ($1, $2, ...)`. 

## Q: How does Optimistic Concurrency work?
If a table has a column named `version` (of type integer), the Gateway automatically generates an `expected_version` argument for the update mutation.
When an update is requested with an `expected_version`:
1. The SQL query adds `AND version = $expected_version`.
2. The SQL query increments the version: `SET version = $expected_version + 1`.
3. If no rows are updated, the Gateway throws an `Optimistic concurrency failure` exception, ensuring no concurrent writes overwrite each other.

## Q: How are Soft Deletes handled?
If a table contains a `deleted_at` timestamp column, the Gateway applies automatic soft-delete logic:
1. **Reads**: An implicit filter `deleted_at IS NULL` is applied to all queries and DataLoader batches.
2. **Deletes**: The generated `delete_<type>` mutation is converted into an update operation that sets `deleted_at = NOW()` rather than executing a destructive `DELETE` statement.

## Q: Can I manually customize the generated GraphQL schema?
Yes. Since the Gateway builds a standard Strawberry `Schema` object, you can programmatically inject custom `strawberry.type` root fields, mutations, or custom extensions before passing the final `Schema` to FastAPI.

## Q: Can I run this with Graphene or Ariadne?
No, the architecture is tightly coupled with **Strawberry GraphQL** because it relies on modern Python type hints (`__annotations__`), dynamic `type()` generation, and native asynchronous DataLoaders.
