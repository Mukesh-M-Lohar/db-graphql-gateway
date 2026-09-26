# Benchmarks & Performance

!!! info "Benchmark Integrity"
    *These metrics were recorded on commit `a792d6a` from the live integration test suite (`level5_batching.py`), which runs against real PostgreSQL and SQLite databases in CI. All figures are reproducible by running `bash integration_tests/run_sqlite.sh` or `bash integration_tests/run_all.sh`.*

The `db-graphql-gateway` is designed to provide highly scalable GraphQL querying over relational databases without the performance penalties traditionally associated with ORM-based GraphQL servers.

---

## N+1 Query Elimination

GraphQL's primary performance bottleneck is the **N+1 query problem**, where a single parent list query triggers N subsequent queries for nested relationship fields.

=== "Without DataLoaders (Traditional ORM)"

    | Action | Query | Execution Count |
    |--------|-------|-----------------|
    | Query 100 `Posts` | `SELECT * FROM posts LIMIT 100` | 1 |
    | Resolve `User` for Post 1 | `SELECT * FROM users WHERE id = 1` | 1 |
    | Resolve `User` for Post 2 | `SELECT * FROM users WHERE id = 2` | 1 |
    | ... | ... | ... |
    | Resolve `User` for Post 100| `SELECT * FROM users WHERE id = 100` | 1 |
    | **Total DB Queries** | | **101** 🔴 |

=== "With `db-graphql-gateway` DataLoaders"

    | Action | Query | Execution Count |
    |--------|-------|-----------------|
    | Query 100 `Posts` | `SELECT * FROM posts LIMIT 100` | 1 |
    | Resolve `User` for **all** Posts | `SELECT * FROM users WHERE id IN ($1, ..., $100)` | 1 |
    | **Total DB Queries** | | **2** 🟢 |

This constant $O(1)$ query complexity per relationship depth level ensures the API remains fast regardless of response data size.

---

## Empirical Proof: O(1) Guarantee

The following results are taken **directly from the `level5_batching.py` integration test suite**, which instruments the actual DB connections using `pg_stat_statements` (Postgres) and `aiosqlite.set_trace_callback` (SQLite).

### Test 1 — Fan-Out Independence (fix depth, scale breadth)

**Query:** `posts → comments` (depth=2), varying the number of posts requested.

| Post Count (breadth) | DB Queries (SQLite) | DB Queries (Postgres) |
|---------------------:|--------------------:|----------------------:|
| 5 | **2** | **4** |
| 20 | **2** | **4** |
| 50 | **2** | **4** |

✅ **Query count is IDENTICAL across all breadths.** Growth with row count = 0. N+1 is eliminated.

> *Postgres counts are higher because `pg_stat_statements` records prepared-statement execution steps. The absolute number is constant — that is the guarantee.*

---

### Test 2 — Depth Linearity (fix breadth, scale depth)

**Query shape:** depth 1 → depth 2 → depth 3, with a fixed batch of 5 rows per level.

| Depth | Relationship Path | DB Queries (SQLite) | DB Queries (Postgres) |
|------:|-------------------|--------------------:|----------------------:|
| 1 | `posts` | 1 | 2 |
| 2 | `posts → comments` | 2 | 4 |
| 3 | `posts → comments → users` | 3 | 4–6 |

✅ **Linear growth (O(depth)), not exponential.** Adding a depth level adds exactly one batched query.

---

### Test 3 — Many-to-Many Batching

**Query:** `posts → tags` across 10 posts (M2M through `post_tags` join table).

| Metric | Observed |
|--------|----------|
| SQLite DB queries | **3** (posts + post_tags + tags) |
| Postgres DB queries | **6** (same 3 logical, counted at prepared-statement granularity) |
| Would be without batching | **1 + 10 + 10 = 21** ❌ |

✅ **One batched query per level**, even across join tables.

---

### Test 4 — Sibling Relations (additive, not multiplicative)

**Query:** `posts { users, comments, tags }` — three sibling relationships resolved in parallel.

| | SQLite | Postgres |
|--|--------|----------|
| Base (posts only) | 1 | 2 |
| All siblings together | 5 | 8 |
| Extra queries for 3 siblings | **+4** | **+6** |

✅ **Additive** (each sibling adds ~1–2 queries), not **multiplicative** (which would be 1 × 3 × N).

---

## Security vs Execution Overhead

The Gateway executes security rules strictly at the Abstract Syntax Tree (AST) level before any resolver logic runs.

- **AST Validation**: Max Depth, Alias, and Complexity checks happen *before* connecting to the database — a CPU-bound, sub-millisecond operation that shields the database from malicious payloads.
- **Transpiled SQL**: Row-level policies are injected directly into the query compiler's AST, so the database engine filters unauthorized rows at the storage level. No post-fetch filtering in Python memory.

!!! tip "Running the benchmarks yourself"
    ```bash
    # SQLite (no Docker needed)
    bash integration_tests/run_sqlite.sh

    # PostgreSQL (requires Docker)
    bash integration_tests/run_all.sh
    ```
    Look for the `Level 5: Batching Correctness` section in the output for live query counts.
