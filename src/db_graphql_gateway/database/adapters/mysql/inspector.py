"""MySQL/MariaDB schema inspector using ``information_schema``.

Produces the same ``DatabaseSchema`` / ``Table`` / ``Column`` shape that
``PostgresSchemaInspector`` produces, so ``IRBuilder`` and all downstream
code remain completely unaware of which database engine was introspected.

Design choices
--------------
- **``COLUMN_TYPE`` stored in ``Column.type``** (not ``DATA_TYPE``) so that
  ``MySQLTypeMapper`` can detect ``TINYINT(1)`` as a boolean.
- **No standalone ENUM type**: MySQL ENUMs are per-column and are not
  reflected as named types in ``information_schema``.  They are mapped to
  ``String`` by the type mapper.  ``namespace.enums`` is always empty.
- **Schema name**: ``DATABASE()`` is used to scope all queries to the current
  database, which becomes the single namespace name.
"""

from typing import Any

import asyncmy
import asyncmy.cursors

from db_graphql_gateway.database.adapters.interfaces import SchemaInspector
from db_graphql_gateway.database.models.schema import (
    Column,
    DatabaseSchema,
    DatabaseSchemaNamespace,
    Relationship,
    Table,
    View,
)


class MySQLSchemaInspector(SchemaInspector):
    """Introspects a MySQL/MariaDB database via ``information_schema``."""

    def __init__(self, pool: Any, database: str) -> None:
        self.pool = pool
        self.database = database

    async def discover_schema(self) -> DatabaseSchema:
        db_schema = DatabaseSchema()
        ns = DatabaseSchemaNamespace(name=self.database)
        db_schema.namespaces[self.database] = ns

        async with self.pool.acquire() as conn:
            async with conn.cursor(asyncmy.cursors.DictCursor) as cur:
                # 1. Tables and views
                await cur.execute(
                    """
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    ORDER BY table_name
                    """,
                    (self.database,),
                )
                table_rows = await cur.fetchall()

                for row in table_rows:
                    tname: str = row["TABLE_NAME"]
                    ttype: str = row["TABLE_TYPE"]

                    if ttype == "BASE TABLE":
                        ns.tables[tname] = Table(name=tname, schema=self.database)
                    elif ttype == "VIEW":
                        ns.views[tname] = View(name=tname, schema=self.database)

                # 2. Columns — use COLUMN_TYPE for tinyint(1) detection
                await cur.execute(
                    """
                    SELECT
                        table_name,
                        column_name,
                        column_type,
                        is_nullable,
                        column_key,
                        extra
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    ORDER BY table_name, ordinal_position
                    """,
                    (self.database,),
                )
                col_rows = await cur.fetchall()

                for row in col_rows:
                    tname = row["TABLE_NAME"]
                    col_name: str = row["COLUMN_NAME"]
                    col_type: str = row["COLUMN_TYPE"]  # e.g. "tinyint(1)", "varchar(255)"
                    nullable: bool = row["IS_NULLABLE"].upper() == "YES"
                    is_pk: bool = row["COLUMN_KEY"].upper() == "PRI"
                    is_fk: bool = False  # updated in FK pass below

                    col = Column(
                        name=col_name,
                        type=col_type,
                        nullable=nullable,
                        is_primary_key=is_pk,
                        is_foreign_key=is_fk,
                    )

                    table_or_view = ns.tables.get(tname) or ns.views.get(tname)
                    if table_or_view is not None:
                        table_or_view.columns.append(col)

                # 3. Foreign keys
                await cur.execute(
                    """
                    SELECT
                        kcu.table_name       AS src_table,
                        kcu.column_name      AS src_col,
                        kcu.referenced_table_name  AS tgt_table,
                        kcu.referenced_column_name AS tgt_col,
                        kcu.constraint_name AS constraint_name
                    FROM information_schema.key_column_usage kcu
                    JOIN information_schema.table_constraints tc
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema   = kcu.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND kcu.table_schema   = %s
                    ORDER BY kcu.constraint_name, kcu.ordinal_position
                    """,
                    (self.database,),
                )
                fk_rows = await cur.fetchall()

                # Group by (src_table, constraint_name) to handle composite FKs
                fk_groups: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
                for fk in fk_rows:
                    key = (fk["src_table"], fk["constraint_name"])
                    fk_groups.setdefault(key, [])
                    fk_groups[key].append((fk["src_col"], fk["tgt_table"], fk["tgt_col"]))

                for (src_table_name, _), refs in fk_groups.items():
                    src_cols = [r[0] for r in refs]
                    tgt_table_name = refs[0][1]
                    tgt_cols = [r[2] for r in refs]

                    src_table = ns.tables.get(src_table_name)
                    if not src_table:
                        continue

                    for col in src_table.columns:
                        if col.name in src_cols:
                            col.is_foreign_key = True

                    src_table.relationships.append(
                        Relationship(
                            name=tgt_table_name.lower(),
                            target_table=tgt_table_name,
                            kind="many_to_one",
                            source_columns=src_cols,
                            target_columns=tgt_cols,
                        )
                    )

                    tgt_table = ns.tables.get(tgt_table_name)
                    if tgt_table:
                        tgt_table.relationships.append(
                            Relationship(
                                name=f"{src_table_name.lower()}s",
                                target_table=src_table_name,
                                kind="one_to_many",
                                source_columns=tgt_cols,
                                target_columns=src_cols,
                            )
                        )

        return db_schema
