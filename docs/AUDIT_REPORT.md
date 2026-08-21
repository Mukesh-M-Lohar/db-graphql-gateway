# Documentation Audit Report

This audit was conducted against the ground truth of the `db-graphql-gateway` repository (CLI commands, `DatabaseAdapter` interface, `GraphQLSchemaBuilder`, and `AuthorizationEngine` implementation) as of commit `e2aed85`.

## Per-File Audit Results

| File | Issue | Severity | Fix needed |
|---|---|---|---|
| `index.md` | Python snippet uses non-existent `GatewayConfig(enable_mutations=True)` | Broken | Remove invalid kwarg from configuration. |
| `quickstart.md` | 1. Snippet uses non-existent `GraphQLGateway` wrapper.<br>2. CLI commands are wrong (`sgql doctor` requires `--dsn`, `sgql security` requires `--config`).<br>3. `enable_mutations=True` invalid. | Broken | Rewrite Python snippet to use `PostgresAdapter`, `GraphQLSchemaBuilder`, and `make_graphql_router`. Fix CLI flags. |
| `SPEC.md` | 1. Phase 14 contains an accidental copy-paste of a user prompt ("don't just run pytest and say it is finished audit").<br>2. Phase 9 mentions "field, relationship policies" but `TablePolicy` only supports table-level `read_rules`. | Stale / Broken | Clean up Phase 14 text. Clarify that Phase 9 authorization currently enforces row-level (tenant) policies. |
| `ARCHITECTURE.md` | No issues found. Accurately describes `CompiledQuery`, `PlaceholderStyle`, and DataLoader batching. | None | None |
| `CONTRIBUTING_ADAPTER.md` | States `fetch_after_write` is a capability flag on the Adapter/Compiler. It is actually dynamically set on `CompiledQuery` by the compiler. The actual adapter flag is `supports_returning`. | Stale | Correct the distinction between `CompiledQuery.fetch_after_write` and `DatabaseAdapter.supports_returning`. |
| `SECURITY.md` | No issues found. Accurately describes JWT, AST limits, and SQL predicate injection. | None | None |
| `BENCHMARKS.md` | Missing commit hash / date reference for the benchmark numbers. | Gap | Add timestamp/commit ref to validate freshness. |
| `PACKAGING_PLAN.md` | No issues found. Outlines future plugin shift correctly. | None | None |
| `FAQ.md` | No issues found. (Recently updated to reflect MySQL/SQLite support). | None | None |
| `CHANGELOG.md` | Missing recent documentation formatting overhaul and audit fixes. | Stale | Add new entries under `[Unreleased]` for the audit remediation. |

## Undocumented in any file
- The `make_graphql_router` function in `fastapi_integration.py` requires `pip install db-graphql-gateway[fastapi]`. This extra installation step is missing from `quickstart.md`.
- `sgql diff` and `sgql validate` are present in the CLI but have no examples in the documentation.
