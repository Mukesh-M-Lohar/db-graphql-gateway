# Benchmarks & Performance

!!! info "Benchmark Integrity"
    *These metrics were recorded on August 21, 2026 (commit `e2aed85`). All N+1 metrics reflect the modern DataLoader batching pattern using `WHERE id IN ($1, $2, ...)`.*

The `db-graphql-gateway` is designed to provide highly scalable GraphQL querying over relational databases without the performance penalties traditionally associated with ORM-based GraphQL servers.

## N+1 Query Elimination

GraphQL's primary performance bottleneck is the **N+1 query problem**, where a single parent list query triggers N subsequent queries for nested relationship fields.

=== "Without DataLoaders (Traditional ORM)"

    | Action | Query | Execution Count |
    |--------|-------|-----------------|
    | Query 100 `Tasks` | `SELECT * FROM tasks LIMIT 100` | 1 |
    | Resolve `User` for Task 1 | `SELECT * FROM users WHERE id = $1` | 1 |
    | Resolve `User` for Task 2 | `SELECT * FROM users WHERE id = $2` | 1 |
    | ... | ... | ... |
    | Resolve `User` for Task 100| `SELECT * FROM users WHERE id = $100` | 1 |
    | **Total Database Queries** | | **101** 🔴 |

=== "With `db-graphql-gateway` DataLoaders"

    | Action | Query | Execution Count |
    |--------|-------|-----------------|
    | Query 100 `Tasks` | `SELECT * FROM tasks LIMIT 100` | 1 |
    | Resolve `User` for all Tasks | `SELECT * FROM users WHERE id IN ($1, $2, ..., $100)` | 1 |
    | **Total Database Queries** | | **2** 🟢 |

This constant $O(1)$ query complexity for relationships ensures the API remains fast regardless of response data size.

## Security vs Execution Overhead

The Gateway executes security rules strictly at the Abstract Syntax Tree (AST) level before attempting to execute any resolvers.

- **AST Validation**: Checking Max Depth, Aliases, and Complexity happens *before* connecting to the database. This is a CPU-bound, sub-millisecond operation that guarantees the database is shielded from malicious payloads.
- **Transpiled SQL**: Row-level policies are injected directly into the AST generated for the Query Compiler, guaranteeing that the database filters the rows perfectly. This pushes the filtering overhead down to the optimized PostgreSQL query planner, rather than doing post-fetch filtering in Python memory.
