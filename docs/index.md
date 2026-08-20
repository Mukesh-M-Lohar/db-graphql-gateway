<div align="center" style="margin-top: 4rem; margin-bottom: 2rem;">
  <h1 style="font-size: 3rem; margin-bottom: 0.5rem; letter-spacing: -0.04em;">db-graphql-gateway</h1>
  <p style="font-size: 1.25rem; color: var(--md-text-color); max-width: 600px; margin: 0 auto;">
    Generate secure, production-ready GraphQL APIs directly from your PostgreSQL database schema with O(1) batching and row-level authorization.
  </p>
  <div style="margin-top: 1.5rem; display: flex; gap: 10px; justify-content: center;">
    <a href="quickstart/"><button class="md-button md-button--primary">Get Started</button></a>
    <a href="https://github.com/db-graphql-gateway/db-graphql-gateway"><button class="md-button">View on GitHub</button></a>
  </div>
</div>

---

`db-graphql-gateway` (CLI: `sgql`) is a powerful introspection and execution engine. It inspects your database schema, constructs an Intermediate Representation (IR), and statically generates a highly optimized **Strawberry GraphQL** schema.

Built for modern enterprise architectures, it features robust security constraints, row-level authorization, and strict $O(1)$ batching to eliminate N+1 query problems.

## ✨ Core Features

<div class="grid cards" markdown>

-   :material-database-search: **Intelligent Schema Introspection**

    ---

    Automatically discovers tables, views, primary keys, foreign keys, and enums directly from PostgreSQL system catalogs.

-   :material-rocket-launch: **O(1) DataLoader Batching**

    ---

    N+1 query problem solved by default. Relationship fields use Strawberry DataLoaders that compile grouped SQL queries (e.g., `WHERE id IN ($1, $2)`), keeping your API blazing fast.

-   :material-shield-lock: **Comprehensive Security & Auth**

    ---

    Row-Level Authorization transpiled directly into SQL `WHERE` clauses. AST DoS protection with hard limits on query depth, complexity budgets, and aliases.

-   :material-filter-variant: **Filtering, Sorting & Pagination**

    ---

    Relay-compliant cursor pagination, deeply nested relationship filtering, and multi-column sorting generated out of the box.

-   :material-history: **Optimistic Concurrency & Soft Deletes**

    ---

    Built-in support for `version` column optimistic locking and automatic `deleted_at` soft-delete filtering.

-   :material-api: **FastAPI Integration**

    ---

    Decoupled helpers to easily mount the Gateway on FastAPI with pluggable `AuthContext` injection.

</div>

---

## 📖 Documentation Directory

<div class="grid cards" markdown>

-   [**Quickstart**](quickstart.md)
    ---
    Get a FastAPI GraphQL server running in 2 minutes.

-   [**Architecture**](ARCHITECTURE.md)
    ---
    Deep dive into the Internal Representation, Planning, and Execution pipelines.

-   [**Security**](SECURITY.md)
    ---
    How the Gateway transpiles authorization into SQL and protects against DoS attacks.

-   [**Benchmarks**](BENCHMARKS.md)
    ---
    N+1 query elimination and $O(1)$ relationship scaling.

-   [**FAQ**](FAQ.md)
    ---
    Common questions regarding design, ORMs, and integrations.

</div>

---

!!! tip "Why not just use an ORM?"
    The Gateway bypasses traditional ORMs to execute dynamic, statically-typed batch queries tailored perfectly to the exact AST requested by the GraphQL client, ensuring minimal memory overhead and zero redundant database hits.
