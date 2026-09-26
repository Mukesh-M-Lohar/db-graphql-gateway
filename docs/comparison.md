# ⚖️ Detailed Comparison

There are several excellent tools in the "Database-to-GraphQL" ecosystem. However, `db-graphql-gateway` makes very different architectural tradeoffs compared to existing solutions like PostGraphile, Hasura, and Supabase (`pg_graphql`).

This document provides an honest, detailed comparison, outlining both what `db-graphql-gateway` uniquely offers and **what it does not offer** by design.

---

## 🚀 vs. PostGraphile

[PostGraphile](https://www.graphile.org/postgraphile/) is a fantastic tool that heavily embraces the **Database as the Application Layer**.

### What `db-graphql-gateway` offers that PostGraphile does not:
- **Database Agnosticism**: PostGraphile is strictly bound to PostgreSQL. `db-graphql-gateway` uses a modular adapter system supporting Postgres, MySQL, and SQLite.
- **Application-Tier Authorization**: PostGraphile relies entirely on PostgreSQL's Row-Level Security (RLS) and database `GRANT` roles. You must create database users/roles for your API clients. `db-graphql-gateway` keeps authorization at the **Application Tier**. It uses an `AuthorizationEngine` that evaluates Python rules and pushes them down into the SQL AST automatically. You only need a single database connection.
- **Python-Native Extensibility**: You can write custom ASGI middleware, use FastAPI Dependency Injection, and merge custom Strawberry resolvers natively in Python.

### What `db-graphql-gateway` DOES NOT offer (Tradeoffs):
- **Smart Tags & DB Comments**: PostGraphile allows configuring the GraphQL schema via SQL comments (e.g., `COMMENT ON TABLE users IS '@omit create';`). `db-graphql-gateway` ignores database comments and requires using a YAML config file (`sgql.yaml`) for overrides.
- **Advanced Postgres Types**: PostGraphile has incredibly deep support for Postgres-specific types (e.g., PostGIS geometry, full-text search vectors). `db-graphql-gateway` maps to standardized scalars by default to maintain cross-adapter compatibility.

---

## ⚡ vs. Supabase / `pg_graphql`

[pg_graphql](https://supabase.github.io/pg_graphql/) (the engine powering Supabase's GraphQL API) is an incredibly fast, native Postgres extension written in Rust.

### What `db-graphql-gateway` offers that `pg_graphql` does not:
- **Universal Deployment**: `pg_graphql` runs *inside* the database as a native extension. This makes it blazingly fast, but many managed database providers (like AWS RDS, Azure Postgres) restrict installing custom extensions. `db-graphql-gateway` runs in your Python backend (e.g., as a FastAPI route), requiring **zero modifications** to your database server.
- **Multiple Database Support**: Like PostGraphile, `pg_graphql` is strictly for Postgres.
- **O(1) DataLoaders Built-In**: `db-graphql-gateway` guarantees O(1) query performance per relationship depth in the application tier using intelligent batching (even for SQLite).

### What `db-graphql-gateway` DOES NOT offer (Tradeoffs):
- **C-Level/Rust Performance**: Because `pg_graphql` runs inside Postgres and is written in Rust, it can execute certain complex joins and string aggregations faster than passing data back and forth to a Python middle-tier.
- **Zero-Backend Architecture**: With `pg_graphql` via Supabase, you don't even need a backend server; clients talk directly to the database layer (via PostgREST/GraphQL). `db-graphql-gateway` *is* a backend framework and requires running a Python web server (like Uvicorn).

---

## 🦅 vs. Hasura

[Hasura](https://hasura.io/) is an enterprise-grade GraphQL engine that provides instant APIs over multiple data sources.

### What `db-graphql-gateway` offers that Hasura does not:
- **Code-First Integration**: Hasura is a standalone service (often deployed as a separate Docker container) that acts as an API gateway. `db-graphql-gateway` is a Python library. You import it directly into your existing FastAPI/Strawberry application. You don't need to deploy a separate infrastructure piece.
- **No Console Required**: Hasura heavily relies on its UI Console or CLI migrations for tracking tables and defining permissions. `db-graphql-gateway` dynamically introspects your database on startup and uses a simple, declarative YAML file for visibility overrides.

### What `db-graphql-gateway` DOES NOT offer (Tradeoffs):
- **GraphQL Subscriptions**: Hasura has best-in-class support for live queries and subscriptions out-of-the-box. `db-graphql-gateway` currently **does not support GraphQL Subscriptions**.
- **Remote Joins & API Federation**: Hasura can join data across multiple different databases and third-party REST/GraphQL APIs (Schema Stitching). `db-graphql-gateway` is designed to map a single database to a single schema.
- **Event Triggers**: Hasura can trigger webhooks on database inserts/updates. `db-graphql-gateway` focuses solely on API resolution.

---

## Summary

Use **`db-graphql-gateway`** if you are building a Python/FastAPI backend, want to dynamically expose a secure GraphQL API backed by MySQL, Postgres, or SQLite, but want to retain the ability to write custom Python business logic alongside it.

Use **PostGraphile** or **pg_graphql** if you are fully committed to the PostgreSQL ecosystem and want to use Row-Level Security.

Use **Hasura** if you need a standalone API Gateway, API federation, or out-of-the-box realtime Subscriptions.
