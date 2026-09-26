# Contributing to db-graphql-gateway

Thank you for your interest in contributing! This project is community-driven and every contribution matters — from a typo fix to a new database adapter.

---

## 🚀 Quick Start

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/db-graphql-gateway.git
cd db-graphql-gateway

# 2. Install dependencies (Python 3.11+, uv required)
uv sync --all-extras --dev

# 3. Install pre-commit hooks
uv run pre-commit install

# 4. Verify everything works
uv run pytest tests/ -q
```

---

## 🗂 Project Structure

```
src/db_graphql_gateway/
├── auth/               # JWT authentication & row-level authorization engine
├── cli/                # sgql CLI commands (doctor, inspect, validate...)
├── database/
│   └── adapters/
│       ├── interfaces.py    # DatabaseAdapter ABC — implement this to add a new DB
│       ├── postgres/        # asyncpg adapter
│       ├── sqlite/          # aiosqlite adapter
│       └── mysql/           # aiomysql adapter
├── graphql/
│   ├── builder.py           # Builds Strawberry schema from IR
│   ├── mutation_builder.py  # Auto-generates create/update/delete mutations
│   └── query_planner.py     # DataLoader batching logic (the N+1 killer)
├── integrations/
│   └── fastapi_integration.py  # make_graphql_router()
└── schema/
    ├── config.py            # GatewayConfig / sgql.yaml loader
    └── ir/                  # Intermediate Representation (DB-agnostic types)
```

---

## 🧪 Running Tests

```bash
# Unit tests (fast, no external deps)
uv run pytest tests/unit/ -v

# Conformance tests (SQLite in-process)
uv run pytest tests/conformance/ -v

# SQLite integration tests (no Docker needed)
cd integration_tests && bash run_sqlite.sh

# PostgreSQL integration tests (requires Docker)
cd integration_tests && bash run_all.sh
```

All tests must pass before a PR is reviewed. The CI will run them automatically.

---

## 🏗 Adding a New Database Adapter

See [`docs/CONTRIBUTING_ADAPTER.md`](docs/CONTRIBUTING_ADAPTER.md) for the full step-by-step guide. The short version:

1. Create `src/db_graphql_gateway/database/adapters/yourdb/`
2. Implement `DatabaseAdapter`, `SchemaInspector`, `QueryCompiler`, `TypeMapper`
3. Add conformance tests in `tests/conformance/`
4. Update `docs/quickstart.md` with a tab for the new adapter

---

## 📝 Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/) — this is what drives the automated semantic versioning and changelog.

| Prefix | When to use | Semver bump |
|--------|-------------|-------------|
| `fix:` | Bug fix | Patch |
| `feat:` | New feature | Minor |
| `feat!:` or `BREAKING CHANGE:` | Breaking API change | Major |
| `docs:` | Documentation only | None |
| `test:` | Tests only | None |
| `chore:` | Tooling / deps | None |
| `refactor:` | Code change, no behavior change | None |

Examples:
```
feat: add MySQL adapter
fix: correct backward pagination cursor encoding for empty results
docs: add OIDC integration example to quickstart
feat!: rename make_graphql_router kwarg context_getter to get_context
```

---

## 🔍 Code Style

Pre-commit hooks enforce everything automatically on commit:

- **ruff** — linting + import sorting
- **ruff-format** — formatting (replaces Black)
- **mypy** — strict type checking

Run them manually:
```bash
uv run pre-commit run --all-files
```

---

## 📬 Submitting a PR

1. Branch from `main`: `git checkout -b feat/my-feature`
2. Write tests — the batching tests in `integration_tests/level5_batching.py` are a good model for performance-sensitive changes
3. Run the full test suite
4. Open a PR with a clear title following the commit convention
5. Fill in the PR description explaining **what** and **why**

PRs are squash-merged. One commit per PR lands on `main`.

---

## 🐛 Reporting Bugs

Please open a [GitHub Issue](https://github.com/forgedlohar/db-graphql-gateway/issues/new) with:

- Python version and OS
- DB adapter used (Postgres / SQLite / MySQL)
- Minimal reproducible example
- Expected vs actual behavior

---

## 💬 Questions?

Open a [GitHub Discussion](https://github.com/forgedlohar/db-graphql-gateway/discussions) — no question is too small.
