"""SQLite schema inspector using PRAGMA commands.

SQLite has no system catalog tables like ``pg_class``.  All metadata is
accessed via PRAGMA statements that return row-sets.  This inspector
normalises the PRAGMA output into the same ``DatabaseSchema`` / ``Table`` /
``Column`` shape that ``PostgresSchemaInspector`` produces, so the rest of
the pipeline (``IRBuilder``, ``GraphQLSchemaBuilder``, auth predicates) is
completely unaware of which database engine was introspected.

Dialect notes
-------------
- **No schemas** — SQLite uses ``ATTACH``-ed databases referenced by alias
  (``main``, ``temp``, …).  All tables from the primary database are placed
  in the synthetic ``"main"`` namespace so they match the ``TableRef.schema``
  value used in ``SQLiteAdapter``.
- **No native ENUM types** — ``namespace.enums`` is always empty; ``IRBuilder``
  handles this gracefully.
- **Dynamic typing** — SQLite stores any value in any column regardless of
  declared affinity.  The inspector maps declared type strings to normalised
  type names (see ``_normalise_type``); the ``SQLiteTypeMapper`` converts these
  to GraphQL scalars.
- **RETURNING support** — SQLite ≥ 3.35.0 (released 2021-03-12) supports
  ``RETURNING``.  Python 3.12 ships with SQLite 3.39.2+, so ``RETURNING`` is
  always available when running on modern Python.  ``SQLiteAdapter.connect()``
  detects the version at runtime and sets ``supports_returning`` accordingly.
"""

import sqlite3

import aiosqlite

from db_graphql_gateway.database.adapters.interfaces import SchemaInspector
from db_graphql_gateway.database.models.schema import (
    Column,
    DatabaseSchema,
    DatabaseSchemaNamespace,
    Relationship,
    Table,
)

# The synthetic schema name used for the primary SQLite database.
SQLITE_MAIN_SCHEMA = "main"


def _normalise_type(declared: str, col_name: str) -> str:
    """Map a SQLite declared-type string to a normalised type name.

    SQLite's type affinity rules (§3.1 of the SQLite spec) are applied,
    with two naming heuristics for columns that lack explicit type
    information:

    - Columns whose name ends in ``_at`` default to ``timestamp``.
    - Columns whose name starts with ``is_`` or ``has_`` default to
      ``boolean``.
    """
    t = declared.strip().lower()

    if not t:
        # Affinity: BLOB — column name heuristics still apply
        if col_name.endswith("_at"):
            return "timestamp"
        if col_name.startswith("is_") or col_name.startswith("has_"):
            return "boolean"
        return "blob"

    # INTEGER affinity
    if any(k in t for k in ("int",)):
        if col_name.startswith("is_") or col_name.startswith("has_"):
            return "boolean"
        return "integer"

    # REAL affinity
    if any(k in t for k in ("real", "floa", "doub")):
        return "float"

    # NUMERIC affinity (includes DECIMAL, NUMERIC, BOOLEAN declared types)
    if any(k in t for k in ("numeric", "decimal", "bool")):
        if "bool" in t:
            return "boolean"
        return "numeric"

    # TEXT affinity — check for timestamp hints in name
    if any(k in t for k in ("char", "clob", "text", "varchar", "nchar", "nvar")):
        if col_name.endswith("_at") or "timestamp" in t or "datetime" in t or "date" in t:
            return "timestamp"
        if "json" in t:
            return "json"
        return "text"

    # Explicit timestamp / date / time declared types
    if any(k in t for k in ("timestamp", "datetime", "date", "time")):
        return "timestamp"

    if "json" in t:
        return "json"

    if "blob" in t:
        return "blob"

    # Fallback: treat anything else as text
    return "text"


class SQLiteSchemaInspector(SchemaInspector):
    """Introspects a SQLite database using PRAGMA commands."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def discover_schema(self) -> DatabaseSchema:
        db_schema = DatabaseSchema()
        ns = DatabaseSchemaNamespace(name=SQLITE_MAIN_SCHEMA)
        db_schema.namespaces[SQLITE_MAIN_SCHEMA] = ns

        # 1. Enumerate tables (excludes internal sqlite_ tables)
        async with self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ) as cur:
            table_rows = await cur.fetchall()

        for (table_name,) in table_rows:
            table = Table(name=table_name, schema=SQLITE_MAIN_SCHEMA)
            ns.tables[table_name] = table

            # 2. Columns via PRAGMA table_info
            async with self.conn.execute(f"PRAGMA table_info({table_name})") as cur:
                col_rows = await cur.fetchall()

            pk_cols: set[int] = set()
            for row in col_rows:
                # PRAGMA table_info columns:
                # cid, name, type, notnull, dflt_value, pk
                cid, col_name, declared_type, notnull, _dflt, pk = (
                    row["cid"],
                    row["name"],
                    row["type"],
                    row["notnull"],
                    row["dflt_value"],
                    row["pk"],
                )
                if pk:
                    pk_cols.add(cid)

                normalised = _normalise_type(declared_type or "", col_name)
                col = Column(
                    name=col_name,
                    type=normalised,
                    nullable=not bool(notnull),
                    is_primary_key=bool(pk),
                    is_foreign_key=False,  # updated below
                )
                table.columns.append(col)

            # 3. Foreign keys via PRAGMA foreign_key_list
            async with self.conn.execute(f"PRAGMA foreign_key_list({table_name})") as cur:
                fk_rows = await cur.fetchall()

            # Group FK rows by FK id (each FK can span multiple columns)
            fk_groups: dict[int, list[tuple[str, str, str]]] = {}
            for fk in fk_rows:
                fk_id = fk["id"]
                src_col = fk["from"]
                tgt_table = fk["table"]
                tgt_col = fk["to"]
                fk_groups.setdefault(fk_id, [])
                fk_groups[fk_id].append((src_col, tgt_table, tgt_col))

            for _fk_id, refs in fk_groups.items():
                src_cols = [r[0] for r in refs]
                tgt_table_name = refs[0][1]
                tgt_cols = [r[2] for r in refs]

                # Mark FK columns on the table
                for col in table.columns:
                    if col.name in src_cols:
                        col.is_foreign_key = True

                # Many-to-one on source table (e.g. post → author)
                table.relationships.append(
                    Relationship(
                        name=tgt_table_name.lower(),
                        target_table=tgt_table_name,
                        kind="many_to_one",
                        source_columns=src_cols,
                        target_columns=tgt_cols,
                    )
                )

                # We register the inverse (one-to-many) in a second pass once
                # all tables are known.
                # Store enough info for the inverse relationship
                table._pending_inverse = getattr(table, "_pending_inverse", [])  # type: ignore[attr-defined]
                table._pending_inverse.append(  # type: ignore[attr-defined]
                    (tgt_table_name, tgt_cols, table_name, src_cols)
                )

        # Second pass: add inverse one_to_many relationships
        for table_name, table in ns.tables.items():
            for tgt_table_name, tgt_cols, src_table_name, src_cols in getattr(
                table, "_pending_inverse", []
            ):
                target_table = ns.tables.get(tgt_table_name)
                if target_table:
                    target_table.relationships.append(
                        Relationship(
                            name=f"{src_table_name.lower()}s",
                            target_table=src_table_name,
                            kind="one_to_many",
                            source_columns=tgt_cols,
                            target_columns=src_cols,
                        )
                    )

        # Clean up temporary attribute
        for table in ns.tables.values():
            if hasattr(table, "_pending_inverse"):
                del table._pending_inverse

        # 4. Views
        async with self.conn.execute("SELECT name FROM sqlite_master WHERE type='view'") as cur:
            view_rows = await cur.fetchall()

        for (view_name,) in view_rows:
            # Reuse Table to represent views (is_view flag set on GraphQLTypeIR, not here)
            view_table = Table(name=view_name, schema=SQLITE_MAIN_SCHEMA)
            ns.views[view_name] = view_table  # type: ignore[assignment]

            async with self.conn.execute(f"PRAGMA table_info({view_name})") as cur:
                vcol_rows = await cur.fetchall()

            for row in vcol_rows:
                col_name = row["name"]
                declared_type = row["type"]
                notnull = row["notnull"]
                pk = row["pk"]
                normalised = _normalise_type(declared_type or "", col_name)
                col = Column(
                    name=col_name,
                    type=normalised,
                    nullable=not bool(notnull),
                    is_primary_key=bool(pk),
                    is_foreign_key=False,
                )
                view_table.columns.append(col)

        return db_schema


def sqlite_version_tuple() -> tuple[int, ...]:
    """Return the SQLite library version as a tuple of ints, e.g. (3, 39, 2)."""
    return tuple(int(x) for x in sqlite3.sqlite_version.split("."))
