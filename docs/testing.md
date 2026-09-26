# Testing Guide

This page documents how to run the full test suite for `db-graphql-gateway`, including unit tests, conformance tests, and the live integration tests against real databases.

---

## Test Layers

| Layer | Location | What it covers |
|-------|----------|----------------|
| **Unit** | `tests/unit/` | Auth, SQL compiler, IR builder, type mapping |
| **Conformance** | `tests/conformance/` | Cross-adapter correctness (SQLite in-process) |
| **Integration** | `integration_tests/` | Full HTTP stack against live Postgres & SQLite |

---

## Unit & Conformance Tests

These run in-process with no external dependencies:

```bash
# Install dev dependencies
uv sync --all-extras --dev

# Run all unit tests
uv run pytest tests/unit/ -v

# Run all conformance tests
uv run pytest tests/conformance/ -v

# Run everything
uv run pytest tests/ -v
```

---

## Integration Tests

The integration tests spin up a real HTTP gateway server and fire GraphQL requests over `httpx`. They verify the full stack end-to-end, including auth, row-level policies, pagination, mutations, and DataLoader batching.

### SQLite (no Docker required)

```bash
cd integration_tests
bash run_sqlite.sh
```

This script:

1. Drops and recreates `sgql_test_db.sqlite3`
2. Seeds the database with `seed_sqlite.py`
3. Starts the gateway server in the background
4. Runs all test levels (L1–L5) via `run_integration.py`
5. Cleans up the DB file on exit

### PostgreSQL (requires Docker)

```bash
cd integration_tests
bash run_all.sh
```

This script:

1. Starts a Postgres container via `docker compose up -d`
2. Waits for the healthcheck to pass
3. Seeds the database with `seed.py`
4. Starts the gateway server in the background
5. Runs all test levels (L1–L5)
6. Tears down the container **including volumes** (`docker compose down -v`)

!!! warning "Volume cleanup"
    The `run_all.sh` script uses `docker compose down -v` on both the success and failure paths, ensuring the Postgres data volume is fully wiped between runs. This prevents `DuplicateTableError` on re-runs.

---

## Test Levels

| Level | Module | What it tests |
|-------|--------|---------------|
| L1 | `level1_basic.py` | Simple queries, filters |
| L2 | `level2_medium.py` | Nested queries, pagination, mutations |
| L3 | `level3_advanced.py` | Depth limits, aliases, auth, backward pagination, M2M |
| L4 | `level4_mutations.py` | Composite PKs, read-only tables, enums |
| L5 | `level5_batching.py` | **Empirical O(1) DataLoader batching correctness** |

---

## Level 5: Batching Correctness Tests

Level 5 is the most important test for the `db-graphql-gateway` performance guarantee.
It **empirically proves** that DB query count does not scale with row count.

### How query counting works

| Adapter | Mechanism |
|---------|-----------|
| **Postgres** | `pg_stat_statements` (enabled by `schema.sql`). The engine resets it before each query and reads the DML-only count after. |
| **SQLite** | `aiosqlite.set_trace_callback` installed at gateway startup. Count is exposed at `GET /admin/query-count` and reset at `GET /admin/query-count/reset`. |

### Individual tests

| Test | Assertion |
|------|-----------|
| **Fan-out independence** | Query count is identical for breadths 5, 20, and 50 |
| **Depth linearity** | Query count grows by ≤1 per additional depth level |
| **M2M batching** | `posts → tags` emits ≤7 queries regardless of join cardinality |
| **Sibling relations** | Extra queries per sibling are additive, not multiplicative |
| **Circular reference** | `users → posts → users` bounded at ≤6 queries |

### Sample output

```
--- Level 5: Batching Correctness (sqlite) ---

  L5-1: Fan-out independence (breadth scaling, depth=2)
    breadth=5:  2 queries
    breadth=20: 2 queries
    breadth=50: 2 queries

  L5-2: Depth linearity (depth scaling, fixed breadth)
    depth=1: 1 queries
    depth=2: 2 queries
    depth=3: 3 queries
    growth ratio per depth: 2.00x (linear OK)

  L5-3: M2M batching (posts -> tags, one query for level)
    posts+tags query count: 3

✅ L5-1: Fan-out independence (0.0ms, 2 queries)
✅ L5-2: Depth linearity (0.0ms, 3 queries)
✅ L5-3: M2M batching (6.4ms, 3 queries)
✅ L5-4: Sibling relations (12.2ms, 5 queries)
✅ L5-5: Circular reference (15.3ms, 3 queries)
```

---

## CI Pipeline

The full test suite runs on every push and pull request:

| Workflow | Trigger | What runs |
|----------|---------|-----------|
| `ci.yml` | Every push / PR | pre-commit (ruff, mypy), unit tests |
| `integration.yml` | Every push to `main` | Full SQLite integration suite |
| `conformance.yml` | Every push / PR | Cross-adapter conformance tests |
| `docs.yml` | Every push to `main` | MkDocs build → GitHub Pages |

Any failure in any test level is **build-breaking** — `run_integration.py` exits with code 1 on the first failed test, causing the shell script to propagate the failure to CI.
