"""MySQL query compiler.

Inherits all SQL generation from ``BaseQueryCompiler`` and sets the three
dialect attributes appropriate for MySQL/MariaDB:

- ``?`` qmark placeholders (asyncmy / aiomysql DB-API style)
- Backtick-quoted identifiers
- No ``RETURNING`` (MySQL < 8.0.21 / MariaDB < 10.5 unsupported;
  we conservatively default to False for broadest compatibility)
- No native ``ILIKE`` — falls back to ``LIKE`` (MySQL LIKE is case-insensitive
  by default on ``_ci`` collations, which is the MySQL default)
"""

from db_graphql_gateway.database.adapters.base_compiler import BaseQueryCompiler


class MySQLQueryCompiler(BaseQueryCompiler):
    """Compiles ``QueryPlan`` / ``MutationPlan`` into asyncmy-compatible SQL."""

    placeholder_style = "format"
    identifier_quote_char = "`"
    supports_returning = False  # conservative default; no RETURNING in MySQL 5.7/8.0
    supports_upsert_on_conflict = False  # MySQL uses ON DUPLICATE KEY UPDATE, not ON CONFLICT
    ilike_supported = False  # MySQL has no ILIKE; LIKE on _ci collation is ci
