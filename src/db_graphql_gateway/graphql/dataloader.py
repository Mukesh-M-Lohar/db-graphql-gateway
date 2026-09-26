"""Request-scoped DataLoader registry for relationship batching.

Eliminates N+1 queries by batching foreign-key lookups across all resolvers
that execute within the same GraphQL request.

The ``schema_map`` parameter (``{type_name: schema_name}``) is built by
``GraphQLSchemaBuilder`` from the IR and injected here so the DataLoader
never hardcodes a dialect-specific default schema name (e.g. ``"public"``).
"""

from collections import defaultdict
from typing import Any

from strawberry.dataloader import DataLoader

from db_graphql_gateway.auth.authorization import AuthorizationEngine
from db_graphql_gateway.auth.interfaces import AuthContext
from db_graphql_gateway.database.adapters.interfaces import (
    DatabaseAdapter,
    FilterCondition,
    FilterGroup,
    QueryPlan,
    TableRef,
)
from db_graphql_gateway.schema.ir.models import GraphQLRelationshipIR


def _combine_filters(
    f1: FilterGroup | FilterCondition | None,
    f2: FilterGroup | FilterCondition | None,
) -> FilterGroup | FilterCondition | None:
    if not f1:
        return f2
    if not f2:
        return f1
    return FilterGroup(operator="AND", conditions=[f1, f2])


class DataLoaderRegistry:
    def __init__(
        self,
        db_adapter: DatabaseAdapter,
        schema_map: dict[str, str],
        auth_engine: AuthorizationEngine | None = None,
        auth_ctx: AuthContext | None = None,
    ) -> None:
        self.db_adapter = db_adapter
        # Maps GraphQL type name → source schema name (e.g. "public", "main")
        self.schema_map = schema_map
        self.auth_engine = auth_engine
        self.auth_ctx = auth_ctx
        self.loaders: dict[str, DataLoader[Any, Any]] = {}

    def get_loader(self, rel: GraphQLRelationshipIR) -> DataLoader[Any, Any]:
        key = f"{rel.join.source_columns[0]}->{rel.target_type}.{rel.join.target_columns[0]}"
        if key not in self.loaders:
            self.loaders[key] = DataLoader(load_fn=self._create_batch_load_fn(rel))
        return self.loaders[key]

    def _create_batch_load_fn(self, rel: GraphQLRelationshipIR) -> Any:
        async def batch_load_fn(keys: list[Any]) -> list[Any]:
            if rel.kind == "many_to_many":
                if (
                    not rel.join.join_table
                    or not rel.join.join_source_columns
                    or not rel.join.join_target_columns
                ):
                    return [[] for _ in keys]

                join_schema = rel.join.join_table.schema
                join_table_name = rel.join.join_table.name
                join_source_col = rel.join.join_source_columns[0]
                join_target_col = rel.join.join_target_columns[0]

                junction_plan = QueryPlan(
                    table=TableRef(schema=join_schema, name=join_table_name),
                    batch_column=join_source_col,
                    batch_values=list(keys),
                )

                compiler = self.db_adapter.compiler()
                junction_query = compiler.compile(junction_plan)
                junction_result = await self.db_adapter.execute(junction_query)

                target_keys_set = set()
                source_to_targets: dict[Any, list[Any]] = defaultdict(list)
                for row in junction_result.data:
                    s_key = row[join_source_col]
                    t_key = row[join_target_col]
                    target_keys_set.add(t_key)
                    source_to_targets[s_key].append(t_key)

                target_keys = list(target_keys_set)

                if not target_keys:
                    return [[] for _ in keys]

                target_col = rel.join.target_columns[0]
                target_schema = self.schema_map.get(rel.target_type, "public")

                auth_filter: FilterGroup | FilterCondition | None = None
                if self.auth_engine:
                    auth_filter = self.auth_engine.get_read_filter(rel.target_type, self.auth_ctx)

                target_plan = QueryPlan(
                    table=TableRef(schema=target_schema, name=rel.target_type),
                    batch_column=target_col,
                    batch_values=target_keys,
                    filter_tree=auth_filter,
                )

                target_query = compiler.compile(target_plan)
                target_result = await self.db_adapter.execute(target_query)

                target_map = {row[target_col]: row for row in target_result.data}

                output = []
                for k in keys:
                    t_keys = source_to_targets.get(k, [])
                    t_rows = [target_map[tk] for tk in t_keys if tk in target_map]
                    output.append(t_rows)

                return output

            # Standard 1-query logic for one_to_one, one_to_many, many_to_one
            target_col = rel.join.target_columns[0]
            target_schema = self.schema_map.get(rel.target_type, "public")

            auth_filter = None
            if self.auth_engine:
                auth_filter = self.auth_engine.get_read_filter(rel.target_type, self.auth_ctx)

            plan = QueryPlan(
                table=TableRef(schema=target_schema, name=rel.target_type),
                batch_column=target_col,
                batch_values=list(keys),
                filter_tree=auth_filter,
            )

            compiler = self.db_adapter.compiler()
            compiled_query = compiler.compile(plan)
            result = await self.db_adapter.execute(compiled_query)

            if rel.kind == "many_to_one" or rel.kind == "one_to_one":
                result_map = {row[target_col]: row for row in result.data}
                return [result_map.get(k) for k in keys]
            else:
                result_list_map: dict[Any, list[Any]] = defaultdict(list)
                for row in result.data:
                    result_list_map[row[target_col]].append(row)
                return [result_list_map.get(k, []) for k in keys]

        return batch_load_fn
