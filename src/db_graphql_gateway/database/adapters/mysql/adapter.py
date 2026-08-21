"""MySQL/MariaDB database adapter using asyncmy.

Key design choices
------------------
**Connection pool**: Uses ``asyncmy.create_pool()`` for async connection
pooling, mirroring the pattern used by ``PostgresAdapter``.

**SELECT-after-write**: MySQL does not support ``RETURNING`` (before
MariaDB 10.5 / MySQL 8.0.21).  When ``MySQLQueryCompiler`` compiles a
DML mutation, it sets ``CompiledQuery.fetch_after_write = True``.
``execute()`` detects this and issues a follow-up ``SELECT`` using
``cursor.lastrowid`` (INSERT) or the known PK value (UPDATE / DELETE).

**Row dictionary**: asyncmy's ``DictCursor`` returns rows as plain dicts,
matching the ``QueryResult`` contract directly.

**Identifier schema**: The ``database`` constructor argument becomes the
namespace name in ``DatabaseSchema``.  It is also used by the inspector
to scope ``information_schema`` queries to the correct database.
"""

import logging
from typing import Any

import asyncmy
import asyncmy.cursors

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
from db_graphql_gateway.database.adapters.mysql.compiler import MySQLQueryCompiler
from db_graphql_gateway.database.adapters.mysql.inspector import MySQLSchemaInspector
from db_graphql_gateway.database.adapters.mysql.mapper import MySQLTypeMapper

logger = logging.getLogger(__name__)


class MySQLAdapter(DatabaseAdapter):
    """Async MySQL/MariaDB adapter wrapping ``asyncmy``."""

    # ── Dialect capability flags ───────────────────────────────────────────
    supports_returning: bool = False
    supports_upsert_on_conflict: bool = False  # MySQL uses ON DUPLICATE KEY UPDATE
    placeholder_style: PlaceholderStyle = "qmark"
    identifier_quote_char: str = "`"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        database: str = "",
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.min_size = min_size
        self.max_size = max_size
        self.pool: Any = None

    async def connect(self) -> None:
        self.pool = await asyncmy.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.database,
            minsize=self.min_size,
            maxsize=self.max_size,
        )
        logger.debug(
            "MySQLAdapter connected (host=%s:%s, db=%s)",
            self.host,
            self.port,
            self.database,
        )

    async def close(self) -> None:
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_pool(self) -> Any:
        if self.pool is None:
            raise RuntimeError("MySQLAdapter is not connected. Call connect() first.")
        return self.pool

    async def _fetch_by_pk(self, table: str, pk_col: str, pk_val: Any) -> QueryResult:
        """SELECT-after-write helper — used when RETURNING is unavailable."""
        comp = MySQLQueryCompiler()
        plan = QueryPlan(
            table=TableRef(schema=self.database, name=table),
            pk_column=pk_col,
            pk_value=pk_val,
        )
        cq = comp.compile(plan)
        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.cursor(asyncmy.cursors.DictCursor) as cur:
                params = (
                    cq.params if isinstance(cq.params, (list, tuple)) else list(cq.params.values())
                )
                await cur.execute(cq.sql, params)
                rows = await cur.fetchall()
        return QueryResult(data=list(rows))

    # ------------------------------------------------------------------
    # DatabaseAdapter interface
    # ------------------------------------------------------------------

    async def execute(self, query: CompiledQuery) -> QueryResult:
        pool = self._require_pool()
        logger.debug("SQL: %s | PARAMS: %s", query.sql, query.params)
        params = (
            query.params if isinstance(query.params, (list, tuple)) else list(query.params.values())
        )

        async with pool.acquire() as conn:
            async with conn.cursor(asyncmy.cursors.DictCursor) as cur:
                await cur.execute(query.sql, params)

                if query.fetch_after_write:
                    if cur.rowcount == 0:
                        await conn.commit()
                        return QueryResult(data=[])
                    pk_val = cur.lastrowid if query.fetch_pk_value is None else query.fetch_pk_value
                    await conn.commit()
                    if query.fetch_table and query.fetch_pk_col and pk_val:
                        return await self._fetch_by_pk(
                            query.fetch_table, query.fetch_pk_col, pk_val
                        )
                    return QueryResult(data=[])

                rows = await cur.fetchall()
                return QueryResult(data=list(rows))

    async def execute_many(self, queries: list[CompiledQuery]) -> list[QueryResult]:
        pool = self._require_pool()
        results: list[QueryResult] = []
        async with pool.acquire() as conn:
            async with conn.cursor(asyncmy.cursors.DictCursor) as cur:
                await cur.execute("BEGIN")
                try:
                    for query in queries:
                        params = (
                            query.params
                            if isinstance(query.params, (list, tuple))
                            else list(query.params.values())
                        )
                        await cur.execute(query.sql, params)

                        if query.fetch_after_write:
                            if cur.rowcount == 0:
                                results.append(QueryResult(data=[]))
                                continue
                            pk_val = (
                                cur.lastrowid
                                if query.fetch_pk_value is None
                                else query.fetch_pk_value
                            )
                            if query.fetch_table and query.fetch_pk_col and pk_val:
                                results.append(
                                    await self._fetch_by_pk(
                                        query.fetch_table, query.fetch_pk_col, pk_val
                                    )
                                )
                            else:
                                results.append(QueryResult(data=[]))
                        else:
                            rows = await cur.fetchall()
                            results.append(QueryResult(data=list(rows)))

                    await cur.execute("COMMIT")
                except Exception:
                    await cur.execute("ROLLBACK")
                    raise
        return results

    async def execute_raw_dml(self, sql: str) -> None:
        """Execute raw SQL for testing or schema setup."""
        if not self.pool:
            raise RuntimeError("Adapter is not connected")
        conn = await self.pool.acquire()
        try:
            async with conn.cursor() as cur:
                await cur.execute(sql)
            await conn.commit()
        finally:
            await self.pool.release(conn)

    def inspector(self) -> SchemaInspector:
        self._require_pool()
        return MySQLSchemaInspector(pool=self.pool, database=self.database)

    def compiler(self) -> QueryCompiler:
        return MySQLQueryCompiler()

    def type_mapper(self) -> TypeMapper:
        return MySQLTypeMapper()
