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
        auth_engine: AuthorizationEngine | None = None,
        auth_ctx: AuthContext | None = None,
    ) -> None:
        self.db_adapter = db_adapter
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
            target_col = rel.join.target_columns[0]

            # Build authorization filter for the target table
            auth_filter: FilterGroup | FilterCondition | None = None
            if self.auth_engine:
                auth_filter = self.auth_engine.get_read_filter(rel.target_type, self.auth_ctx)

            plan = QueryPlan(
                table=TableRef(schema="public", name=rel.target_type),
                batch_column=target_col,
                batch_values=list(keys),
                filter_tree=auth_filter,
            )

            compiler = self.db_adapter.compiler()
            compiled_query = compiler.compile(plan)
            result = await self.db_adapter.execute(compiled_query)

            # Group results by key
            if rel.kind == "many_to_one" or rel.kind == "one_to_one":
                result_map: dict[Any, Any] = {row[target_col]: row for row in result.data}
                return [result_map.get(k) for k in keys]
            else:
                # one_to_many or many_to_many
                result_list_map: dict[Any, list[Any]] = defaultdict(list)
                for row in result.data:
                    result_list_map[row[target_col]].append(row)
                return [result_list_map.get(k, []) for k in keys]

        return batch_load_fn
