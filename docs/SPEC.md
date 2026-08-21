# SPEC: db-graphql-gateway

## Product Goal
A production-grade, reusable Python package that automatically generates a secure, optimized GraphQL API from a database connection (starting with PostgreSQL asyncpg).

## Core Rules
- **No ORM Required**: The database itself is the source of truth. SQLAlchemy and SQLModel are strictly optional integrations.
- **Security First**: Authentication and Authorization are separate. Authorization is implemented as SQL predicates, never as Python-level filtering of fetched rows.
- **Performance**: DataLoader pattern must be implemented per-request for relationship batching (with integrated auth predicates) to prevent N+1 queries.
- **Zero Raw SQL Exposure**: Clients never provide SQL fragments. Filters, sorting, and pagination are strictly typed GraphQL arguments.
- **Schema Decoupling**: Database introspection -> Intermediate Representation (IR) -> GraphQL Schema. The IR is where YAML configurations mutate the graph.
- **Python target**: 3.11+
- **CLI**: `sgql` (init, inspect, generate, validate, diff, security, doctor, test)

## Implementation Phases

### Phase 1 — Foundation (COMPLETED)
- **Deliverable**: Project structure, `pyproject.toml`, config, logging, CLI skeleton, core interfaces, adapter interfaces, tests, CI setup with `uv`.
- **Exit Criteria**: `pytest` green on skeleton; interfaces reviewed and approved. Empirical proof via `sgql --help`.

### Phase 2 — PostgreSQL Introspection
- **Deliverable**: Connection pooling, schema discovery (tables, columns, types, PKs, FKs, constraints, indexes, views).
- **Exit Criteria**: Integration tests passing against a real Postgres container (`testcontainers-python`).

### Phase 3 — Schema IR
- **Deliverable**: Translation of `DatabaseSchema` into GraphQL IR, relationship inference, and type mapping. Includes merging configuration overrides from `sgql.yaml`.
- **Exit Criteria**: IR unit tests passing, demonstrating configuration override merging works.

### Phase 4 — Basic GraphQL
- **Deliverable**: GraphQL types, root queries, single-object lookups, and basic list queries generated from IR.
- **Exit Criteria**: One complete end-to-end query successfully executes.

### Phase 5 — Filter, Sort, Pagination
- **Deliverable**: Type-aware filters, sorting enums, cursor-based pagination, and security limits on lists.
- **Exit Criteria**: `max_page_size` properly enforced in tests; filters strictly bound as SQL parameters.

### Phase 6 — Relationships & DataLoader
- **Deliverable**: Relationship traversal (1:1, 1:N, N:1, M:M), request-scoped `DataLoader` batching, N+1 detection.
- **Exit Criteria**: Benchmarks prove O(1) queries per relationship level, avoiding O(N) queries.

### Phase 7 — Query Planner
- **Deliverable**: AST parsing, field selection, planning, integration of authorization predicates, and generation of efficient SQL (`EXISTS`, `JOIN`, `IN`).
- **Exit Criteria**: Benchmarks show optimal parameterized SQL generated for deeply nested queries.

### Phase 8 — Authentication
- **Deliverable**: Pluggable authentication interface (`AuthenticationProvider`), JWT validation, `AuthContext` middleware.
- **Exit Criteria**: Tests reject expired, invalid-sig, wrong-issuer, wrong-audience, and bad-alg tokens.

### Phase 9 — Authorization
- **Deliverable**: Authorization policy engine resolving table and tenant-level policies into SQL predicates (future phases will expand to field and relationship policies).
- **Exit Criteria**: **Explicit test**: User A cannot fetch Project B even if they know the ID (predicates prevent loading unauthorized rows).

### Phase 10 — Security Hardening
- **Deliverable**: Complexity budgets, depth limits, alias limits, rate limiting, timeouts, error masking, production introspection lockdown, sensitive-field defaults.
- **Exit Criteria**: Security test suite is completely green.

### Phase 11 — Mutations
- **Deliverable**: `create`, `update`, `delete` operations respecting views (read-only), authorization, constraints, transactions, optimistic concurrency, and soft deletes.
- **Exit Criteria**: Must only pass after Phase 9 (Authorization) is complete and robust.

### Phase 12 — FastAPI/ORM Integrations
- **Deliverable**: Optional framework integrations (`fastapi`) and ORM support (`sqlalchemy`, `sqlmodel`) layered purely on top.
- **Exit Criteria**: Core package must remain importable without `fastapi` or `sqlalchemy` installed.

### Phase 13 — CLI Tooling
- **Deliverable**: Implementation of `sgql doctor`, `sgql security`, `sgql diff`, and `sgql validate`.
- **Exit Criteria**: CLI smoke tests pass for all utility commands.

### Phase 14 — Final Testing & Documentation
- **Deliverable**: Full test suite run, security review, performance review, and documentation generation using `mkdocs`. Must include `README.md`, `quickstart.md`, `ARCHITECTURE.md`, `SPEC.md`, `FAQ.md`, `BENCHMARKS.md`, and `SECURITY.md`.
- **Exit Criteria**: Final Acceptance Test passes end-to-end (from `pip install` to secure API serving).
