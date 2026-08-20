<div align="center">
  <h1>🚀 db-graphql-gateway</h1>
  <p><strong>Generate secure, production-ready GraphQL APIs directly from your PostgreSQL database schema.</strong></p>
  <a href="https://github.com/db-graphql-gateway/db-graphql-gateway"><img src="https://img.shields.io/badge/Status-Production%20Ready-success?style=flat-square" alt="Status"></a>
  <a href="#"><img src="https://img.shields.io/badge/PostgreSQL-14%2B-blue?style=flat-square&logo=postgresql" alt="PostgreSQL"></a>
  <a href="#"><img src="https://img.shields.io/badge/GraphQL-Strawberry-red?style=flat-square&logo=graphql" alt="Strawberry GraphQL"></a>
</div>

---

`db-graphql-gateway` (CLI: `sgql`) is a powerful introspection and execution engine. It inspects your database schema, constructs an Intermediate Representation (IR), and statically generates a highly optimized **Strawberry GraphQL** schema. 

Built for modern enterprise architectures, it features robust security constraints, row-level authorization, and strict $O(1)$ batching to eliminate N+1 query problems.

## ✨ Core Features

- **🔍 Intelligent Schema Introspection**
  Automatically discovers tables, views, primary keys, foreign keys, and enums from PostgreSQL system catalogs. 
- **🚀 O(1) DataLoader Batching**
  N+1 query problem solved by default. Relationship fields use Strawberry DataLoaders that compile grouped SQL queries (e.g., `WHERE id IN ($1, $2)`), keeping your API blazing fast.
- **🛡️ Comprehensive Security & Authorization**
  - **Row-Level Authorization**: Contextual security policies transpiled directly into SQL `WHERE` clauses.
  - **AST DoS Protection**: Hard limits on query depth, execution complexity budgets, and aliases.
  - **Production Masking**: Introspection lockdown and automatic error masking to prevent structural leaks.
  - **Sensitive Fields**: Automatic detection and redaction of PII and secrets (e.g., `password`, `token`).
- **🔀 Filtering, Sorting & Pagination**
  Relay-compliant cursor pagination, deeply nested relationship filtering, and multi-column sorting.
- **⚡ Optimistic Concurrency & Soft Deletes**
  Built-in support for `version` column optimistic locking and automatic `deleted_at` soft-delete filtering.
- **🛠️ FastAPI Integration**
  Decoupled helpers to easily mount the Gateway on FastAPI with pluggable `AuthContext` injection.

## 📦 Installation

```bash
pip install db-graphql-gateway
```

## 📖 Documentation Directory

- [**Quickstart**](quickstart.md) — Get a FastAPI GraphQL server running in 2 minutes.
- [**Architecture**](ARCHITECTURE.md) — Deep dive into the Internal Representation, Planning, and Execution pipelines.
- [**Security**](SECURITY.md) — How the Gateway transpiles authorization into SQL and protects against DoS attacks.
- [**Benchmarks**](BENCHMARKS.md) — N+1 query elimination and $O(1)$ relationship scaling.
- [**FAQ**](FAQ.md) — Common questions regarding design, ORMs, and integrations.

---
> [!TIP]
> **Why not just use an ORM?**
> The Gateway bypasses traditional ORMs to execute dynamic, statically-typed batch queries tailored perfectly to the exact AST requested by the GraphQL client, ensuring minimal memory overhead and zero redundant database hits.
