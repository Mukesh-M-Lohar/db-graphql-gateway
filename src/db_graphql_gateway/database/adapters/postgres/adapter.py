"""PostgreSQL adapter using asyncpg connection pooling."""

import logging

import asyncpg

from db_graphql_gateway.database.adapters.interfaces import (
    CompiledQuery,
    DatabaseAdapter,
    PlaceholderStyle,
    QueryCompiler,
    QueryResult,
    SchemaInspector,
    TypeMapper,
)
from db_graphql_gateway.database.adapters.postgres.compiler import PostgresQueryCompiler
from db_graphql_gateway.database.adapters.postgres.inspector import PostgresSchemaInspector
from db_graphql_gateway.database.adapters.postgres.mapper import PostgresTypeMapper

logger = logging.getLogger(__name__)


class PostgresAdapter(DatabaseAdapter):
    # ── Dialect capability flags ───────────────────────────────────────────
    supports_returning: bool = True
    supports_upsert_on_conflict: bool = True
    placeholder_style: PlaceholderStyle = "numbered"
    identifier_quote_char: str = '"'

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10) -> None:
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=self.min_size,
            max_size=self.max_size,
        )

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def execute(self, query: CompiledQuery) -> QueryResult:
        if not self.pool:
            raise RuntimeError("Database not connected")
        logger.debug("SQL: %s | PARAMS: %s", query.sql, query.params)
        async with self.pool.acquire() as conn:
            params = query.params if isinstance(query.params, list) else list(query.params.values())
            records = await conn.fetch(query.sql, *params)
            return QueryResult(data=[dict(record) for record in records])

    async def execute_many(self, queries: list[CompiledQuery]) -> list[QueryResult]:
        if not self.pool:
            raise RuntimeError("DatabaseAdapter is not connected. Call connect() first.")
        results = []
        async with self.pool.acquire() as conn, conn.transaction():
            for query in queries:
                params = (
                    query.params if isinstance(query.params, list) else list(query.params.values())
                )
                records = await conn.fetch(query.sql, *params)
                results.append(QueryResult(data=[dict(r) for r in records]))
        return results

    async def execute_raw_dml(self, sql: str) -> None:
        """Execute raw SQL for testing or schema setup."""
        if not self.pool:
            raise RuntimeError("Adapter is not connected")
        async with self.pool.acquire() as conn:
            await conn.execute(sql)

    def inspector(self) -> SchemaInspector:
        if not self.pool:
            raise RuntimeError("DatabaseAdapter is not connected. Call connect() first.")
        return PostgresSchemaInspector(self.pool)

    def compiler(self) -> QueryCompiler:
        return PostgresQueryCompiler()

    def type_mapper(self) -> TypeMapper:
        return PostgresTypeMapper()
