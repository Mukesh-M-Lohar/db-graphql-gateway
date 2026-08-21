"""Dialect-parameterized base query compiler.

All SQL SELECT / DML logic lives here.  Dialect-specific subclasses
(``PostgresQueryCompiler``, ``SQLiteQueryCompiler``, ``MySQLQueryCompiler``)
only override the three class-level attributes below and, where necessary,
``_compile_ilike``.
"""

from typing import Any, Literal

from db_graphql_gateway.database.adapters.interfaces import (
    CompiledQuery,
    FilterCondition,
    FilterGroup,
    MutationPlan,
    QueryPlan,
)


class BaseQueryCompiler:
    """Abstract base — subclasses set these three class-level attributes."""

    placeholder_style: Literal["named", "numbered", "qmark", "format"] = "numbered"
    identifier_quote_char: str = '"'
    supports_returning: bool = True
    supports_upsert_on_conflict: bool = False
    ilike_supported: bool = True

    # ------------------------------------------------------------------
    # Dialect helpers
    # ------------------------------------------------------------------

    def _ph(self, params: list[Any]) -> str:
        """Emit the next positional placeholder for the current dialect.

        Called *after* the value has been appended to ``params`` so
        ``len(params)`` already reflects the new entry.
        """
        if self.placeholder_style == "numbered":
            return f"${len(params)}"
        elif self.placeholder_style == "qmark":
            return "?"
        elif self.placeholder_style == "format":
            return "%s"
        else:
            # "named" — @p1, @p2, …
            return f"@p{len(params)}"

    def _qi(self, identifier: str) -> str:
        """Quote a single SQL identifier with the dialect-correct character."""
        q = self.identifier_quote_char
        close = "]" if q == "[" else q
        return f"{q}{identifier}{close}"

    def _table_ref(self, schema: str, name: str) -> str:
        """Produce a fully-qualified, quoted table reference."""
        if schema:
            return f"{self._qi(schema)}.{self._qi(name)}"
        return self._qi(name)

    # ------------------------------------------------------------------
    # Filter compilation
    # ------------------------------------------------------------------

    def _compile_filter(
        self,
        node: FilterGroup | FilterCondition,
        params: list[Any],
    ) -> str:
        if isinstance(node, FilterCondition):
            col = self._qi(node.column)
            op = node.op.lower()

            if op == "eq":
                params.append(node.value)
                return f"{col} = {self._ph(params)}"
            elif op == "neq":
                params.append(node.value)
                return f"{col} != {self._ph(params)}"
            elif op == "gt":
                params.append(node.value)
                return f"{col} > {self._ph(params)}"
            elif op == "gte":
                params.append(node.value)
                return f"{col} >= {self._ph(params)}"
            elif op == "lt":
                params.append(node.value)
                return f"{col} < {self._ph(params)}"
            elif op == "lte":
                params.append(node.value)
                return f"{col} <= {self._ph(params)}"
            elif op == "in":
                if not isinstance(node.value, list | tuple) or len(node.value) == 0:
                    return "FALSE"
                placeholders: list[str] = []
                for v in node.value:
                    params.append(v)
                    placeholders.append(self._ph(params))
                return f"{col} IN ({', '.join(placeholders)})"
            elif op == "like":
                params.append(node.value)
                return f"{col} LIKE {self._ph(params)}"
            elif op == "ilike":
                return self._compile_ilike(col, params, node.value)
            elif op == "contains":
                return self._compile_contains(col, params, node.value)
            elif op == "is_null":
                return f"{col} IS NULL" if node.value else f"{col} IS NOT NULL"
            else:
                raise ValueError(f"Unsupported filter operator: {node.op!r}")

        elif isinstance(node, FilterGroup):
            operator = node.operator.upper()
            if not node.conditions:
                return "TRUE" if operator != "NOT" else "FALSE"

            if operator == "NOT":
                sub_sql = self._compile_filter(node.conditions[0], params)
                return f"NOT ({sub_sql})"
            else:
                sub_sqls = [self._compile_filter(cond, params) for cond in node.conditions]
                join_str = f" {operator} "
                return f"({join_str.join(sub_sqls)})"

        raise TypeError(f"Invalid filter tree node type: {type(node)}")

    def _compile_ilike(self, col: str, params: list[Any], value: Any) -> str:
        """Case-insensitive LIKE.  Postgres: ILIKE.  Others: LIKE (ci collation)."""
        if self.ilike_supported:
            params.append(value)
            return f"{col} ILIKE {self._ph(params)}"
        # SQLite LIKE is case-insensitive for ASCII by default.
        # MySQL LIKE on _ci collations is also case-insensitive.
        params.append(value)
        return f"{col} LIKE {self._ph(params)}"

    def _compile_contains(self, col: str, params: list[Any], value: Any) -> str:
        """Substring containment — dialect-independent via LIKE %value%."""
        params.append(f"%{value}%")
        if self.ilike_supported:
            return f"{col} ILIKE {self._ph(params)}"
        return f"{col} LIKE {self._ph(params)}"

    # ------------------------------------------------------------------
    # SELECT compiler
    # ------------------------------------------------------------------

    def compile(self, plan: QueryPlan) -> CompiledQuery:
        table_name = self._table_ref(plan.table.schema, plan.table.name)
        params: list[Any] = []
        where_clauses: list[str] = []

        if plan.pk_column and plan.pk_value is not None:
            params.append(plan.pk_value)
            where_clauses.append(f"{self._qi(plan.pk_column)} = {self._ph(params)}")

        if plan.batch_column and plan.batch_values is not None:
            if len(plan.batch_values) == 0:
                where_clauses.append("FALSE")
            else:
                placeholders: list[str] = []
                for val in plan.batch_values:
                    params.append(val)
                    placeholders.append(self._ph(params))
                where_clauses.append(
                    f"{self._qi(plan.batch_column)} IN ({', '.join(placeholders)})"
                )

        if plan.filter_tree:
            where_clauses.append(self._compile_filter(plan.filter_tree, params))

        if plan.selected_columns:
            cols_sql = ", ".join(self._qi(col) for col in plan.selected_columns)
        else:
            cols_sql = "*"

        sql_parts = [f"SELECT {cols_sql} FROM {table_name}"]
        if where_clauses:
            sql_parts.append("WHERE " + " AND ".join(where_clauses))

        if plan.order_by:
            order_strings: list[str] = []
            for item in plan.order_by:
                direction = "DESC" if item.direction.upper() == "DESC" else "ASC"
                order_strings.append(f"{self._qi(item.column)} {direction}")
            sql_parts.append("ORDER BY " + ", ".join(order_strings))

        if plan.limit is not None:
            params.append(plan.limit)
            sql_parts.append(f"LIMIT {self._ph(params)}")

        if plan.offset is not None:
            params.append(plan.offset)
            sql_parts.append(f"OFFSET {self._ph(params)}")

        return CompiledQuery(sql=" ".join(sql_parts), params=params)

    # ------------------------------------------------------------------
    # DML compiler
    # ------------------------------------------------------------------

    def compile_mutation(self, plan: MutationPlan) -> CompiledQuery:
        table_name = self._table_ref(plan.table.schema, plan.table.name)
        params: list[Any] = []
        returning_suffix = " RETURNING *" if self.supports_returning else ""

        if plan.operation == "insert":
            if not plan.data:
                raise ValueError("Insert mutation requires data")
            cols = list(plan.data.keys())
            col_names = ", ".join(self._qi(c) for c in cols)
            placeholders: list[str] = []
            for c in cols:
                params.append(plan.data[c])
                placeholders.append(self._ph(params))
            val_placeholders = ", ".join(placeholders)
            sql = (
                f"INSERT INTO {table_name} ({col_names})"
                f" VALUES ({val_placeholders}){returning_suffix}"
            )
            cq = CompiledQuery(sql=sql, params=params)
            if not self.supports_returning:
                cq.fetch_after_write = True
                cq.fetch_table = plan.table.name
                cq.fetch_pk_col = plan.pk_column
                # pk_value not known yet for INSERT; adapter uses cursor.lastrowid
            return cq

        elif plan.operation == "update":
            if not plan.data:
                raise ValueError("Update mutation requires data")
            set_clauses: list[str] = []
            for c, val in plan.data.items():
                params.append(val)
                set_clauses.append(f"{self._qi(c)} = {self._ph(params)}")

            where_clauses: list[str] = []
            if plan.pk_column and plan.pk_value is not None:
                params.append(plan.pk_value)
                where_clauses.append(f"{self._qi(plan.pk_column)} = {self._ph(params)}")

            if plan.filter_tree:
                where_clauses.append(self._compile_filter(plan.filter_tree, params))

            if not where_clauses:
                raise ValueError("Update mutation requires a WHERE condition")

            set_sql = ", ".join(set_clauses)
            where_sql = " AND ".join(where_clauses)
            sql = f"UPDATE {table_name} SET {set_sql} WHERE {where_sql}{returning_suffix}"
            cq = CompiledQuery(sql=sql, params=params)
            if not self.supports_returning:
                cq.fetch_after_write = True
                cq.fetch_table = plan.table.name
                cq.fetch_pk_col = plan.pk_column
                cq.fetch_pk_value = plan.pk_value
            return cq

        elif plan.operation == "delete":
            where_clauses_del: list[str] = []
            if plan.pk_column and plan.pk_value is not None:
                params.append(plan.pk_value)
                where_clauses_del.append(f"{self._qi(plan.pk_column)} = {self._ph(params)}")

            if plan.filter_tree:
                where_clauses_del.append(self._compile_filter(plan.filter_tree, params))

            if not where_clauses_del:
                raise ValueError("Delete mutation requires a WHERE condition")

            where_sql_del = " AND ".join(where_clauses_del)
            sql = f"DELETE FROM {table_name} WHERE {where_sql_del}{returning_suffix}"
            cq = CompiledQuery(sql=sql, params=params)
            if not self.supports_returning:
                cq.fetch_after_write = True
                cq.fetch_table = plan.table.name
                cq.fetch_pk_col = plan.pk_column
                cq.fetch_pk_value = plan.pk_value
            return cq

        else:
            raise ValueError(f"Unsupported mutation operation: {plan.operation!r}")
