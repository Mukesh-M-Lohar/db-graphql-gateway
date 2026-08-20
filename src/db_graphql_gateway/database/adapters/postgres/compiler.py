from typing import Any

from db_graphql_gateway.database.adapters.interfaces import (
    CompiledQuery,
    FilterCondition,
    FilterGroup,
    MutationPlan,
    QueryCompiler,
    QueryPlan,
)


class PostgresQueryCompiler(QueryCompiler):
    def _compile_filter(
        self,
        node: FilterGroup | FilterCondition,
        params: list[Any],
    ) -> str:
        if isinstance(node, FilterCondition):
            col = f'"{node.column}"'
            op = node.op.lower()
            if op == "eq":
                params.append(node.value)
                return f"{col} = ${len(params)}"
            elif op == "neq":
                params.append(node.value)
                return f"{col} != ${len(params)}"
            elif op == "gt":
                params.append(node.value)
                return f"{col} > ${len(params)}"
            elif op == "gte":
                params.append(node.value)
                return f"{col} >= ${len(params)}"
            elif op == "lt":
                params.append(node.value)
                return f"{col} < ${len(params)}"
            elif op == "lte":
                params.append(node.value)
                return f"{col} <= ${len(params)}"
            elif op == "in":
                if not isinstance(node.value, list | tuple) or len(node.value) == 0:
                    return "FALSE"
                param_placeholders = []
                for v in node.value:
                    params.append(v)
                    param_placeholders.append(f"${len(params)}")
                return f"{col} IN ({', '.join(param_placeholders)})"
            elif op in ("like", "ilike"):
                params.append(node.value)
                sql_op = "LIKE" if op == "like" else "ILIKE"
                return f"{col} {sql_op} ${len(params)}"
            elif op == "contains":
                params.append(f"%{node.value}%")
                return f"{col} ILIKE ${len(params)}"
            elif op == "is_null":
                return f"{col} IS NULL" if node.value else f"{col} IS NOT NULL"
            else:
                raise ValueError(f"Unsupported filter operator: {node.op}")

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

    def compile(self, plan: QueryPlan) -> CompiledQuery:
        table_name = f'"{plan.table.schema}"."{plan.table.name}"'
        params: list[Any] = []
        where_clauses: list[str] = []

        if plan.pk_column and plan.pk_value is not None:
            params.append(plan.pk_value)
            where_clauses.append(f'"{plan.pk_column}" = ${len(params)}')

        if plan.batch_column and plan.batch_values is not None:
            if len(plan.batch_values) == 0:
                where_clauses.append("FALSE")
            else:
                placeholders = []
                for val in plan.batch_values:
                    params.append(val)
                    placeholders.append(f"${len(params)}")
                where_clauses.append(f'"{plan.batch_column}" IN ({", ".join(placeholders)})')

        if plan.filter_tree:
            where_clauses.append(self._compile_filter(plan.filter_tree, params))

        if plan.selected_columns:
            cols_sql = ", ".join(f'"{col}"' for col in plan.selected_columns)
        else:
            cols_sql = "*"

        sql_parts = [f"SELECT {cols_sql} FROM {table_name}"]
        if where_clauses:
            sql_parts.append("WHERE " + " AND ".join(where_clauses))

        if plan.order_by:
            order_strings = []
            for item in plan.order_by:
                direction = "DESC" if item.direction.upper() == "DESC" else "ASC"
                order_strings.append(f'"{item.column}" {direction}')
            sql_parts.append("ORDER BY " + ", ".join(order_strings))

        if plan.limit is not None:
            params.append(plan.limit)
            sql_parts.append(f"LIMIT ${len(params)}")

        if plan.offset is not None:
            params.append(plan.offset)
            sql_parts.append(f"OFFSET ${len(params)}")

        sql = " ".join(sql_parts)
        return CompiledQuery(sql=sql, params=params)

    def compile_mutation(self, plan: MutationPlan) -> CompiledQuery:
        schema_prefix = f'"{plan.table.schema}".' if plan.table.schema else ""
        table_name = f'{schema_prefix}"{plan.table.name}"'
        params: list[Any] = []

        if plan.operation == "insert":
            if not plan.data:
                raise ValueError("Insert mutation requires data")
            cols = list(plan.data.keys())
            col_names = ", ".join(f'"{c}"' for c in cols)
            placeholders = []
            for c in cols:
                params.append(plan.data[c])
                placeholders.append(f"${len(params)}")
            val_placeholders = ", ".join(placeholders)
            sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({val_placeholders}) RETURNING *"
            return CompiledQuery(sql=sql, params=params)

        elif plan.operation == "update":
            if not plan.data:
                raise ValueError("Update mutation requires data")
            set_clauses = []
            for c, val in plan.data.items():
                params.append(val)
                set_clauses.append(f'"{c}" = ${len(params)}')

            where_clauses = []
            if plan.pk_column and plan.pk_value is not None:
                params.append(plan.pk_value)
                where_clauses.append(f'"{plan.pk_column}" = ${len(params)}')

            if plan.filter_tree:
                auth_sql = self._compile_filter(plan.filter_tree, params)
                where_clauses.append(auth_sql)

            if not where_clauses:
                raise ValueError("Update mutation requires a WHERE condition")

            set_sql = ", ".join(set_clauses)
            where_sql = " AND ".join(where_clauses)
            sql = f"UPDATE {table_name} SET {set_sql} WHERE {where_sql} RETURNING *"
            return CompiledQuery(sql=sql, params=params)

        elif plan.operation == "delete":
            where_clauses = []
            if plan.pk_column and plan.pk_value is not None:
                params.append(plan.pk_value)
                where_clauses.append(f'"{plan.pk_column}" = ${len(params)}')

            if plan.filter_tree:
                auth_sql = self._compile_filter(plan.filter_tree, params)
                where_clauses.append(auth_sql)

            if not where_clauses:
                raise ValueError("Delete mutation requires a WHERE condition")

            where_sql = " AND ".join(where_clauses)
            sql = f"DELETE FROM {table_name} WHERE {where_sql} RETURNING *"
            return CompiledQuery(sql=sql, params=params)

        else:
            raise ValueError(f"Unsupported mutation operation: {plan.operation}")
