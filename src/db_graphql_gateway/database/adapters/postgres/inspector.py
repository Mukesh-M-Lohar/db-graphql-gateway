import asyncpg

from db_graphql_gateway.database.adapters.interfaces import SchemaInspector
from db_graphql_gateway.database.models.schema import (
    Column,
    DatabaseSchema,
    DatabaseSchemaNamespace,
    Enum,
    Relationship,
    Table,
    View,
)


class PostgresSchemaInspector(SchemaInspector):
    def __init__(self, pool: asyncpg.Pool, schemas: list[str] | None = None) -> None:
        self.pool = pool
        self.schemas = schemas or ["public"]

    async def discover_schema(self) -> DatabaseSchema:
        db_schema = DatabaseSchema()
        for schema_name in self.schemas:
            db_schema.namespaces[schema_name] = DatabaseSchemaNamespace(name=schema_name)

        async with self.pool.acquire() as conn:
            # 1. Fetch tables and views
            tables_query = """
                SELECT c.oid, c.relname, c.relkind::text as relkind, n.nspname,
                       obj_description(c.oid, 'pg_class') as description
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY($1)
                  AND c.relkind IN ('r', 'v', 'm')
            """
            table_records = await conn.fetch(tables_query, self.schemas)

            # Map oid to Table/View objects
            oid_to_table: dict[int, Table] = {}
            attnum_to_colname: dict[tuple[int, int], str] = {}

            for row in table_records:
                schema_name = row["nspname"]
                name = row["relname"]
                kind = row["relkind"]
                description = row["description"]
                oid = row["oid"]

                if kind == "r":
                    table = Table(name=name, schema=schema_name, description=description)
                    db_schema.namespaces[schema_name].tables[name] = table
                    oid_to_table[oid] = table
                elif kind in ("v", "m"):
                    view = View(
                        name=name,
                        schema=schema_name,
                        description=description,
                        is_materialized=(kind == "m"),
                    )
                    db_schema.namespaces[schema_name].views[name] = view
                    oid_to_table[oid] = view

            # 2. Fetch columns
            if oid_to_table:
                columns_query = """
                    SELECT a.attrelid, a.attnum, a.attname, format_type(a.atttypid, a.atttypmod) as data_type,
                           not a.attnotnull as nullable,
                           col_description(a.attrelid, a.attnum) as description
                    FROM pg_attribute a
                    WHERE a.attrelid = ANY($1)
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                    ORDER BY a.attnum
                """
                column_records = await conn.fetch(columns_query, list(oid_to_table.keys()))

                for row in column_records:
                    table_oid = row["attrelid"]
                    attnum = row["attnum"]
                    colname = row["attname"]
                    attnum_to_colname[(table_oid, attnum)] = colname

                    table = oid_to_table[table_oid]
                    col = Column(
                        name=colname,
                        type=row["data_type"],
                        nullable=row["nullable"],
                        is_primary_key=False,
                        is_foreign_key=False,
                        description=row["description"],
                    )
                    table.columns.append(col)

                # 3. Fetch foreign key constraints to build relationships
                fk_query = """
                    SELECT
                        con.conrelid as src_oid,
                        con.confrelid as target_oid,
                        con.conkey as src_attnums,
                        con.confkey as target_attnums,
                        c_src.relname as src_table,
                        c_tgt.relname as target_table
                    FROM pg_constraint con
                    JOIN pg_class c_src ON c_src.oid = con.conrelid
                    JOIN pg_class c_tgt ON c_tgt.oid = con.confrelid
                    WHERE con.contype = 'f' AND con.conrelid = ANY($1)
                """
                fk_records = await conn.fetch(fk_query, list(oid_to_table.keys()))

                for fk in fk_records:
                    src_oid = fk["src_oid"]
                    target_oid = fk["target_oid"]
                    src_table_name = fk["src_table"]
                    target_table_name = fk["target_table"]

                    src_cols = [
                        attnum_to_colname[(src_oid, attnum)] for attnum in fk["src_attnums"]
                    ]
                    target_cols = [
                        attnum_to_colname[(target_oid, attnum)] for attnum in fk["target_attnums"]
                    ]

                    src_table = oid_to_table[src_oid]
                    target_table = oid_to_table.get(target_oid)

                    # Mark FK flags on columns
                    for col in src_table.columns:
                        if col.name in src_cols:
                            col.is_foreign_key = True

                    # 1. Add many_to_one relationship on src_table (e.g. post -> author)
                    rel_name_m2o = target_table_name.lower()
                    src_table.relationships.append(
                        Relationship(
                            name=rel_name_m2o,
                            target_table=target_table_name,
                            kind="many_to_one",
                            source_columns=src_cols,
                            target_columns=target_cols,
                        )
                    )

                    # 2. Add inverse one_to_many relationship on target_table (e.g. user -> posts)
                    if target_table:
                        rel_name_o2m = f"{src_table_name.lower()}s"
                        target_table.relationships.append(
                            Relationship(
                                name=rel_name_o2m,
                                target_table=src_table_name,
                                kind="one_to_many",
                                source_columns=target_cols,
                                target_columns=src_cols,
                            )
                        )

            # 4. Fetch enums
            enums_query = """
                SELECT t.typname, n.nspname, array_agg(e.enumlabel ORDER BY e.enumsortorder) as enum_values
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = ANY($1)
                GROUP BY t.typname, n.nspname
            """
            enum_records = await conn.fetch(enums_query, self.schemas)
            for row in enum_records:
                schema_name = row["nspname"]
                name = row["typname"]
                values = row["enum_values"]

                db_schema.namespaces[schema_name].enums[name] = Enum(
                    name=name,
                    values=values,
                )

        return db_schema
