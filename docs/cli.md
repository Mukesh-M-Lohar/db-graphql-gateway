# CLI Reference (`sgql`)

The `db-graphql-gateway` comes with a powerful command-line interface (`sgql`) designed to help you manage, inspect, and test your gateway configuration.

## Global Options

- `--version`: Show the version and exit.
- `--help`: Show the help message and exit.

---

## Commands

### `sgql init`

Initialize a new `db-graphql-gateway` configuration file (`sgql.yaml`) in the current directory.

```bash
sgql init
```

This generates a default `sgql.yaml` configuring authentication, security limits, and pagination defaults.

---

### `sgql inspect`

Inspect the live database schema and generate an Intermediate Representation (IR).

**Options:**
- `--dsn TEXT`: Database connection string (or use `DATABASE_URL` environment variable).

```bash
sgql inspect --dsn postgresql://user:pass@localhost:5432/db
```

This command connects to the specified database (PostgreSQL, SQLite, or MySQL), introspects tables, views, and relationships, and outputs the detected schema statistics.

---

### `sgql doctor`

Inspect system readiness and check dependencies for production deployment.

**Options:**
- `--dsn TEXT`: Database connection string to test connectivity.

```bash
sgql doctor --dsn sqlite:///my_database.sqlite
```

Doctor checks:
- Python environment version (Requires 3.10+)
- Presence of required dependencies (`asyncpg`, `jwt`, `strawberry`)
- Database reachability (if a DSN is provided)
- Presence of the Gateway configuration file (`sgql.yaml`)

---

### `sgql security`

Run a security audit against the current configuration and policy rules.

**Options:**
- `--config TEXT`: Path to config file (default: `sgql.yaml`).

```bash
sgql security --config sgql.yaml
```

Verifies that JWT authentication, row-level authorization policies, AST maximum depth and alias limits, and production error masking are properly enabled.

---

### `sgql validate`

Validate current configuration, IR definitions, and schema mappings.

**Options:**
- `--config TEXT`: Path to config file (default: `sgql.yaml`).

```bash
sgql validate --config sgql.yaml
```

Parses the YAML configuration and validates it against the internal Pydantic schema model.

---

### `sgql diff`

Show differences between the live database schema and the generated IR. 

**Options:**
- `--dsn TEXT`: Database connection string.

```bash
sgql diff --dsn mysql://root:pass@127.0.0.1:3306/db
```

Useful for detecting schema drift after running database migrations.

---

### `sgql generate`

Generate GraphQL schema from IR and configuration.

```bash
sgql generate
```

Builds the GraphQL type definitions and wires up the DataLoader resolvers.

---

### `sgql docs`

Serve the project documentation locally (requires `mkdocs-material`).

**Options:**
- `--port INTEGER`: Port to serve documentation on (default: `8000`).

```bash
sgql docs --port 8080
```

Starts a local MkDocs development server with live reloading, so you can read and browse the gateway documentation and architecture diagrams locally.

---

### `sgql test`

Run generated GraphQL schema unit and integration tests.

```bash
sgql test
```

Executes the gateway test suite to ensure resolving logic operates safely.
