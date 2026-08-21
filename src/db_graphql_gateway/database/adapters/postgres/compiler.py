"""PostgreSQL-specific query compiler.

Extends ``BaseQueryCompiler`` with Postgres dialect settings:
- ``$N`` numbered placeholders (asyncpg style)
- Double-quoted identifiers
- ``RETURNING *`` on all DML
- Native ``ILIKE`` support
"""

from db_graphql_gateway.database.adapters.base_compiler import BaseQueryCompiler


class PostgresQueryCompiler(BaseQueryCompiler):
    """Compiles ``QueryPlan`` / ``MutationPlan`` objects into asyncpg-compatible SQL."""

    placeholder_style = "numbered"
    identifier_quote_char = '"'
    supports_returning = True
    supports_upsert_on_conflict = True
    ilike_supported = True
    # All compilation logic is inherited from BaseQueryCompiler.
    # No overrides are required for Postgres.
