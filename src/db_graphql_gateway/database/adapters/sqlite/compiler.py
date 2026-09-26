"""SQLite query compiler.

Inherits all SQL generation from ``BaseQueryCompiler`` and sets the three
dialect attributes appropriate for SQLite:

- ``?`` qmark placeholders (aiosqlite / sqlite3 DB-API style)
- ``"`` double-quoted identifiers (standard SQL, also valid in SQLite)
- ``RETURNING`` support detected at runtime in ``SQLiteAdapter.connect()``
  and patched onto the class after connect.
- No native ``ILIKE`` — falls back to ``LIKE`` (which is case-insensitive
  for ASCII in SQLite by default).
"""

from db_graphql_gateway.database.adapters.base_compiler import BaseQueryCompiler


class SQLiteQueryCompiler(BaseQueryCompiler):
    """Compiles ``QueryPlan`` / ``MutationPlan`` into aiosqlite-compatible SQL."""

    placeholder_style = "qmark"
    identifier_quote_char = '"'
    # supports_returning is overridden per-instance by SQLiteAdapter.connect()
    # to reflect the runtime SQLite library version.
    supports_returning = False
    supports_upsert_on_conflict = True  # ON CONFLICT DO UPDATE (SQLite 3.24+)
    ilike_supported = False  # No ILIKE in SQLite; LIKE is ci for ASCII
