# Changelog

All notable changes to `db-graphql-gateway` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Integration Testing Workflow**: Added a fully automated, Docker-based end-to-end integration test suite (`integration_tests/`) that validates Deep Nesting, N+1 limits, and Row-Level Security directly against PostgreSQL. Hooked into GitHub Actions.
- **Documentation Overhaul**: Complete MkDocs migration with Material theme, Tabbed code blocks, Grid Cards, and Admonitions.
- **Documentation Audit**: Remediated staleness and cross-file contradictions across all markdown files to match codebase ground truth.
- **Optimistic Concurrency**: Automatic detection of `version` columns. Generates `expected_version` arguments on update mutations and enforces database-level concurrency checks.
- **Soft Deletes**: Automatic detection of `deleted_at` columns. Adds implicit `deleted_at IS NULL` filters to read queries and converts `delete_` mutations to timestamp updates.
- **Complexity Budgets**: New Strawberry AST validation rule to reject queries that exceed a calculated complexity score based on nesting depth and field count.
- **AST Security Limits**: Configured `max_depth` and `max_aliases` protections via `QueryDepthLimiter` and `MaxAliasesLimiter` to harden the gateway against expansive query attacks.
- **Introspection Lockdown**: Added security rule to prevent schema introspection in production environments.
- **Sensitive Field Redaction**: `GatewayConfig` now supports `sensitive_field_patterns` (defaults to passwords and tokens). These fields are automatically dropped from the GraphQL schema during the IR build phase.
- **Comprehensive Documentation**: Complete rewrite of the documentation suite, adding Mermaid diagrams, GitHub alerts, deep architectural dives, and an expanded FAQ.

### Changed
- **Type Safety**: Core GraphQL execution and schema building logic (`builder.py`, `filter_builder.py`) is now strictly typed and passes `mypy --strict`. Removed blanket `# mypy: ignore-errors` suppressions.
- **Dynamic Annotations**: Resolved `MissingArgumentsAnnotationsError` in Strawberry by dynamically generating robust `__annotations__` dictionaries for dynamically compiled resolver functions.
- **N+1 Benchmarking Docs**: Updated documentation SQL snippets to accurately reflect the modern `WHERE id IN ($1, $2)` DataLoader batching pattern.

### Fixed
- **Table Pluralization Bug**: Fixed the database inspector generating incorrect table pluralizations (e.g. `userss` instead of `users`). All corresponding unit and conformance tests have been corrected.
- **Error Masking Scope**: Narrowed the production error masking rule to safely catch database exceptions (asyncpg, SQL syntax) without silencing generic Python errors erroneously.
- **CLI Dead Code**: Removed unused imports in `main.py` causing `ruff` CI failures.
- **Stub Code Removal**: Removed deprecated mock JWT and duplicate model files leftover from earlier development phases.
