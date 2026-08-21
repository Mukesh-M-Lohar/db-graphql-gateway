"""SQLite database adapter using aiosqlite.

Key design choices
------------------
**No connection pool**: SQLite is an embedded engine accessed via a single
``aiosqlite.Connection``.  Concurrency is handled by aiosqlite's internal
serialisation queue; no pool is needed or appropriate.

**SELECT-after-write**: When ``supports_returning`` is ``False`` (SQLite <
3.35), DML mutations compiled by ``SQLiteQueryCompiler`` set the
``fetch_after_write`` sentinel on the ``CompiledQuery``.  ``execute()``
detects this flag and issues a follow-up ``SELECT`` using ``lastrowid`` (for
INSERT) or the known PK value (for UPDATE / DELETE).

**Row factory**: ``aiosqlite.Row`` is set as the row factory so that
``dict(row)`` produces a plain Python dictionary, matching the
``QueryResult`` contract.

**Runtime RETURNING detection**: At ``connect()`` time the adapter inspects
``sqlite3.sqlite_version`` and sets ``supports_returning = True`` when the
library is ≥ 3.35.0.  The compiler instance is then patched to match so
that compiled queries use ``RETURNING *`` and skip the extra ``SELECT``.
"""

import logging
import sqlite3
from typing import Any

import aiosqlite

from db_graphql_gateway.database.adapters.interfaces import (
    CompiledQuery,
    DatabaseAdapter,
    PlaceholderStyle,
    QueryCompiler,
    QueryPlan,
    QueryResult,
    SchemaInspector,
    TableRef,
    TypeMapper,
)
from db_graphql_gateway.database.adapters.sqlite.compiler import SQLiteQueryCompiler
from db_graphql_gateway.database.adapters.sqlite.inspector import (
    SQLiteSchemaInspector,
    SQLITE_MAIN_SCHEMA,
    sqlite_version_tuple,
)
from db_graphql_gateway.database.adapters.sqlite.mapper import SQLiteTypeMapper

logger = logging.getLogger(__name__)

# SQLite ≥ 3.35.0 supports RETURNING
_RETURNING_MIN_VERSION = (3, 35, 0)


class SQLiteAdapter(DatabaseAdapter):
    """Async SQLite adapter wrapping ``aiosqlite``."""

    # ── Dialect capability flags ───────────────────────────────────────────
    supports_returning: bool = False  # patched at connect() time
    supports_upsert_on_conflict: bool = True  # ON CONFLICT DO UPDATE (3.24+)
    placeholder_style: PlaceholderStyle = "qmark"
    identifier_quote_char: str = '"'

    def __init__(self, path: str = ":memory:") -> None:
        """
        Args:
            path: Path to the SQLite database file, or ``":memory:"`` for an
                  in-memory database (useful for testing without a real file).
        """
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._compiler: SQLiteQueryCompiler | None = None

    async def connect(self) -> None:
        """Open the aiosqlite connection and detect RETURNING support."""
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        # Enable FK enforcement (off by default in SQLite)
        await self._conn.execute("PRAGMA foreign_keys = ON")

        # Runtime RETURNING detection — patch both the adapter and a shared
        # compiler instance so they stay in sync.
        ver = sqlite_version_tuple()
        returning_ok = ver >= _RETURNING_MIN_VERSION
        self.supports_returning = returning_ok
        self._compiler = SQLiteQueryCompiler()
        self._compiler.supports_returning = returning_ok

        logger.debug(
            "SQLiteAdapter connected (path=%s, sqlite=%s, RETURNING=%s)",
            self.path,
            sqlite3.sqlite_version,
            returning_ok,
        )

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SQLiteAdapter is not connected. Call connect() first.")
        return self._conn

    async def _fetch_by_pk(self, table: str, pk_col: str, pk_val: Any) -> QueryResult:
        """Issue a SELECT after a DML that lacks RETURNING."""
        conn = self._require_conn()
        comp = self._compiler or SQLiteQueryCompiler()
        plan = QueryPlan(
            table=TableRef(schema=SQLITE_MAIN_SCHEMA, name=table),
            pk_column=pk_col,
            pk_value=pk_val,
        )
        cq = comp.compile(plan)
        async with conn.execute(cq.sql, cq.params) as cur:
            rows = await cur.fetchall()
        return QueryResult(data=[dict(row) for row in rows])

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def execute(self, query: CompiledQuery) -> QueryResult:
        conn = self._require_conn()
        logger.debug("SQL: %s | PARAMS: %s", query.sql, query.params)
        params = query.params if isinstance(query.params, list) else list(query.params.values())

        async with conn.execute(query.sql, params) as cur:
            if query.fetch_after_write:
                # SELECT-after-write: use lastrowid for INSERT, known pk for UPDATE/DELETE
                pk_val = cur.lastrowid if query.fetch_pk_value is None else query.fetch_pk_value
                await conn.commit()
                if query.fetch_table and query.fetch_pk_col and pk_val is not None:
                    return await self._fetch_by_pk(query.fetch_table, query.fetch_pk_col, pk_val)
                return QueryResult(data=[])
            rows = await cur.fetchall()
        return QueryResult(data=[dict(row) for row in rows])

    async def execute_many(self, queries: list[CompiledQuery]) -> list[QueryResult]:
        conn = self._require_conn()
        results: list[QueryResult] = []
        async with conn:  # uses context manager for auto-commit/rollback
            for query in queries:
                params = (
                    query.params if isinstance(query.params, list) else list(query.params.values())
                )
                async with conn.execute(query.sql, params) as cur:
                    if query.fetch_after_write:
                        pk_val = (
                            cur.lastrowid if query.fetch_pk_value is None else query.fetch_pk_value
                        )
                        if query.fetch_table and query.fetch_pk_col and pk_val is not None:
                            results.append(
                                await self._fetch_by_pk(
                                    query.fetch_table, query.fetch_pk_col, pk_val
                                )
                            )
                        else:
                            results.append(QueryResult(data=[]))
                    else:
                        rows = await cur.fetchall()
                        results.append(QueryResult(data=[dict(r) for r in rows]))
        return results

    async def execute_raw_dml(self, sql: str) -> None:
        """Execute raw SQL for testing or schema setup."""
        if self._conn is None:
            raise RuntimeError("Adapter is not connected")
        await self._conn.execute(sql)
        await self._conn.commit()

    def inspector(self) -> SchemaInspector:
        conn = self._require_conn()
        return SQLiteSchemaInspector(conn)

    def compiler(self) -> QueryCompiler:
        return self._compiler or SQLiteQueryCompiler()

    def type_mapper(self) -> TypeMapper:
        return SQLiteTypeMapper()
