import enum
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Type, Optional

import strawberry
from strawberry.types import Info
from strawberry.schema.config import StrawberryConfig
from strawberry.types.field import StrawberryField

from db_graphql_gateway.auth.authorization import AuthorizationEngine
from db_graphql_gateway.auth.interfaces import AuthContext
from db_graphql_gateway.database.adapters.interfaces import (
    DatabaseAdapter,
    FilterGroup,
    FilterCondition,
    MutationPlan,
    QueryPlan,
    TableRef,
)
from db_graphql_gateway.database.models.schema import DatabaseSchema
from db_graphql_gateway.graphql.dataloader import DataLoaderRegistry
from db_graphql_gateway.graphql.filter_builder import (
    create_filter_input_for_type,
    create_order_by_input_for_type,
    parse_filter_input,
    parse_order_by_input,
)
from db_graphql_gateway.graphql.mutation_builder import create_mutation_input_types
from db_graphql_gateway.graphql.pagination import (
    Connection,
    Edge,
    PageInfo,
    decode_cursor,
    encode_cursor,
)
from db_graphql_gateway.graphql.query_planner import QueryPlanner
from db_graphql_gateway.schema.ir.models import GraphQLTypeIR, GraphQLRelationshipIR


def _combine_filters(f1: Any, f2: Any) -> Any:
    if not f1:
        return f2
    if not f2:
        return f1
    return FilterGroup(operator="AND", conditions=[f1, f2])


class GraphQLSchemaBuilder:
    def __init__(
        self,
        db_adapter: DatabaseAdapter,
        max_page_size: int = 100,
        auth_engine: AuthorizationEngine | None = None,
    ) -> None:
        self.db_adapter = db_adapter
        self.max_page_size = max_page_size
        self.auth_engine = auth_engine
        self.generated_types: dict[str, type] = {}
        self.generated_enums: dict[str, type] = {}

    def map_scalar_type(self, type_name: str) -> Type[Any]:
        if type_name in self.generated_enums:
            return self.generated_enums[type_name]

        type_name_lower = type_name.lower()
        if "int" in type_name_lower or "serial" in type_name_lower:
            return int
        if "bool" in type_name_lower:
            return bool
        if (
            "float" in type_name_lower
            or "numeric" in type_name_lower
            or "double" in type_name_lower
            or "real" in type_name_lower
        ):
            return float
        if "timestamp" in type_name_lower or "date" in type_name_lower or "time" in type_name_lower:
            return datetime
        if "json" in type_name_lower:
            import typing

            return typing.cast(Type[Any], strawberry.scalars.JSON)
            import uuid

            return uuid.UUID
        # Fallback to string for varchar, text, enums, etc.
        return str

    def _build_enums(self, db_schema: DatabaseSchema) -> None:
        for namespace in db_schema.namespaces.values():
            for enum_obj in namespace.enums.values():
                enum_dict = {val: val for val in enum_obj.values}
                python_enum = enum.Enum(enum_obj.name, enum_dict)  # type: ignore
                self.generated_enums[enum_obj.name] = strawberry.enum(python_enum)

    def _create_relationship_resolver(
        self, rel: GraphQLRelationshipIR
    ) -> Callable[..., Awaitable[Any]]:
        async def resolver(root: Any, info: Info) -> Any:
            registry: DataLoaderRegistry | None = (
                info.context.get("dataloader_registry") if info.context is not None else None
            )
            if not registry:
                auth_ctx: AuthContext | None = (
                    info.context.get("auth_context") if info.context else None
                )
                registry = DataLoaderRegistry(
                    self.db_adapter,
                    auth_engine=self.auth_engine,
                    auth_ctx=auth_ctx,
                )
                if info.context is not None:
                    info.context["dataloader_registry"] = registry

            loader = registry.get_loader(rel)

            src_col = rel.join.source_columns[0]
            parent_key = getattr(root, src_col, None)
            if parent_key is None:
                return [] if rel.kind in ("one_to_many", "many_to_many") else None

            result_data = await loader.load(parent_key)
            target_type = self.generated_types[rel.target_type]

            if rel.kind in ("many_to_one", "one_to_one"):
                return target_type(**result_data) if result_data else None
            else:
                return [target_type(**row) for row in (result_data or [])]

        return resolver

    def _build_strawberry_type(self, ir_type: GraphQLTypeIR) -> Any:
        annotations: dict[str, Any] = {}
        cls_dict: dict[str, Any] = {}

        # 1. Scalar fields
        for field in ir_type.fields:
            if field.relationship:
                continue

            python_type = self.map_scalar_type(field.graphql_type)
            if field.nullable:
                annotations[field.name] = python_type | None
                cls_dict[field.name] = None
            else:
                annotations[field.name] = python_type
                cls_dict[field.name] = None

        cls_dict["__annotations__"] = annotations
        cls = type(ir_type.name, (), cls_dict)
        return strawberry.type(cls)

    def _attach_relationships_to_strawberry_type(self, ir_type: GraphQLTypeIR) -> None:
        sb_type = self.generated_types[ir_type.name]
        type_def = getattr(sb_type, "__strawberry_definition__")

        for field in ir_type.fields:
            if not field.relationship:
                continue

            rel = field.relationship
            rel_resolver = self._create_relationship_resolver(rel)
            target_sb_type: Any = self.generated_types[rel.target_type]

            if rel.kind in ("one_to_many", "many_to_many"):
                type_annotation: Any = list[target_sb_type] | None
            else:
                type_annotation = target_sb_type | None

            rel_resolver.__annotations__ = {
                "root": sb_type,
                "info": Info,
                "return": type_annotation,
            }

            field_def = StrawberryField(
                python_name=field.name,
                graphql_name=field.name,
                type_annotation=strawberry.annotation.StrawberryAnnotation(type_annotation),
                base_resolver=strawberry.field(resolver=rel_resolver).base_resolver,
            )
            type_def.fields.append(field_def)

    def _create_list_resolver(
        self, ir_type: GraphQLTypeIR, return_type: type
    ) -> Callable[..., Awaitable[list[Any]]]:
        async def resolver(
            info: Info,
            where: Optional[Any] = None,
            order_by: Optional[list[Any]] = None,
            limit: Optional[int] = None,
            offset: Optional[int] = None,
        ) -> list[Any]:
            if info.context is not None and "dataloader_registry" not in info.context:
                auth_ctx_list: AuthContext | None = (
                    info.context.get("auth_context") if info.context else None
                )
                info.context["dataloader_registry"] = DataLoaderRegistry(
                    self.db_adapter,
                    auth_engine=self.auth_engine,
                    auth_ctx=auth_ctx_list,
                )

            effective_limit = self.max_page_size
            if limit is not None:
                effective_limit = min(limit, self.max_page_size)

            filter_tree = parse_filter_input(where)

            # Evaluate authorization policy predicate
            if self.auth_engine:
                auth_ctx: AuthContext | None = (
                    info.context.get("auth_context") if info.context else None
                )
                auth_filter = self.auth_engine.get_read_filter(ir_type.source_table.name, auth_ctx)
                filter_tree = _combine_filters(auth_filter, filter_tree)

            if any(f.name == "deleted_at" for f in ir_type.fields):
                soft_delete_filter = FilterCondition(column="deleted_at", op="is_null", value=True)
                filter_tree = _combine_filters(filter_tree, soft_delete_filter)

            order_by_items = parse_order_by_input(order_by)

            selected_cols = QueryPlanner.extract_selected_columns(info, ir_type)

            plan = QueryPlan(
                table=TableRef(schema=ir_type.source_table.schema, name=ir_type.source_table.name),
                selected_columns=selected_cols if selected_cols else None,
                filter_tree=filter_tree,
                order_by=order_by_items,
                limit=effective_limit,
                offset=offset,
            )
            compiler = self.db_adapter.compiler()
            compiled_query = compiler.compile(plan)

            result = await self.db_adapter.execute(compiled_query)
            return [return_type(**row) for row in result.data]

        return resolver

    def _create_connection_resolver(
        self, ir_type: GraphQLTypeIR, return_type: type
    ) -> Callable[..., Awaitable[Any]]:
        async def resolver(
            info: Info,
            where: Optional[Any] = None,
            order_by: Optional[list[Any]] = None,
            first: Optional[int] = None,
            after: Optional[str] = None,
        ) -> Connection[return_type]:  # type: ignore
            if info.context is not None and "dataloader_registry" not in info.context:
                auth_ctx_conn: AuthContext | None = (
                    info.context.get("auth_context") if info.context else None
                )
                info.context["dataloader_registry"] = DataLoaderRegistry(
                    self.db_adapter,
                    auth_engine=self.auth_engine,
                    auth_ctx=auth_ctx_conn,
                )

            requested_limit = first if first is not None else self.max_page_size
            effective_limit = min(requested_limit, self.max_page_size)

            current_offset = decode_cursor(after) if after else 0

            filter_tree = parse_filter_input(where)

            # Evaluate authorization policy predicate
            if self.auth_engine:
                auth_ctx: AuthContext | None = (
                    info.context.get("auth_context") if info.context else None
                )
                auth_filter = self.auth_engine.get_read_filter(ir_type.source_table.name, auth_ctx)
                filter_tree = _combine_filters(auth_filter, filter_tree)

            order_by_items = parse_order_by_input(order_by)

            plan = QueryPlan(
                table=TableRef(schema=ir_type.source_table.schema, name=ir_type.source_table.name),
                filter_tree=filter_tree,
                order_by=order_by_items,
                limit=effective_limit + 1,
                offset=current_offset,
            )
            compiler = self.db_adapter.compiler()
            compiled_query = compiler.compile(plan)

            result = await self.db_adapter.execute(compiled_query)
            rows = result.data

            has_next_page = len(rows) > effective_limit
            data_rows = rows[:effective_limit]

            edges: list[Any] = []
            for idx, row in enumerate(data_rows):
                node_obj = return_type(**row)
                cursor_str = encode_cursor(current_offset + idx + 1)
                edges.append(Edge(node=node_obj, cursor=cursor_str))  # type: ignore[call-arg]

            start_cursor = edges[0].cursor if edges else None
            end_cursor = edges[-1].cursor if edges else None

            page_info = PageInfo(  # type: ignore[call-arg]
                has_next_page=has_next_page,
                has_previous_page=current_offset > 0,
                start_cursor=start_cursor,
                end_cursor=end_cursor,
            )

            return Connection(edges=edges, page_info=page_info)  # type: ignore[call-arg]

        return resolver

    def _create_create_mutation_resolver(
        self, ir_type: GraphQLTypeIR, return_type: type
    ) -> Callable[..., Awaitable[Any]]:
        async def resolver(info: Info, input: Any) -> Any:
            data = {k: v for k, v in vars(input).items() if v is not None}

            # Evaluate authorization filter if needed for create attributes
            plan = MutationPlan(
                operation="insert",
                table=TableRef(schema=ir_type.source_table.schema, name=ir_type.source_table.name),
                data=data,
            )
            compiler = self.db_adapter.compiler()
            compiled_query = compiler.compile_mutation(plan)

            result = await self.db_adapter.execute(compiled_query)
            if not result.data:
                return None
            return return_type(**result.data[0])

        return resolver

    def _create_update_mutation_resolver(
        self, ir_type: GraphQLTypeIR, return_type: type
    ) -> Callable[..., Awaitable[Any]]:
        pk_col = next((f.name for f in ir_type.fields if f.is_primary_key), "id")
        has_version = any(f.name == "version" for f in ir_type.fields)

        async def resolver(
            info: Info, id: Any, input: Any, expected_version: Optional[int] = None
        ) -> Any:
            data = {k: v for k, v in vars(input).items() if v is not None}

            auth_filter = None
            if self.auth_engine:
                auth_ctx: AuthContext | None = (
                    info.context.get("auth_context") if info.context else None
                )
                auth_filter = self.auth_engine.get_read_filter(ir_type.source_table.name, auth_ctx)

            if has_version and expected_version is not None:
                version_filter = FilterCondition(column="version", op="eq", value=expected_version)
                auth_filter = _combine_filters(auth_filter, version_filter)
                data["version"] = expected_version + 1

            if not data:
                # No fields to update -> fetch current record
                return None

            plan = MutationPlan(
                operation="update",
                table=TableRef(schema=ir_type.source_table.schema, name=ir_type.source_table.name),
                data=data,
                pk_column=pk_col,
                pk_value=id,
                filter_tree=auth_filter,
            )
            compiler = self.db_adapter.compiler()
            compiled_query = compiler.compile_mutation(plan)

            result = await self.db_adapter.execute(compiled_query)
            if not result.data:
                if has_version and expected_version is not None:
                    from graphql import GraphQLError

                    raise GraphQLError(
                        "Optimistic concurrency failure: record modified by another transaction or not found."
                    )
                return None
            return return_type(**result.data[0])

        return resolver

    def _create_delete_mutation_resolver(
        self, ir_type: GraphQLTypeIR, return_type: type
    ) -> Callable[..., Awaitable[Any]]:
        pk_col = next((f.name for f in ir_type.fields if f.is_primary_key), "id")
        has_deleted_at = any(f.name == "deleted_at" for f in ir_type.fields)

        async def resolver(info: Info, id: Any) -> Any:
            auth_filter = None
            if self.auth_engine:
                auth_ctx: AuthContext | None = (
                    info.context.get("auth_context") if info.context else None
                )
                auth_filter = self.auth_engine.get_read_filter(ir_type.source_table.name, auth_ctx)

            from datetime import datetime, timezone

            if has_deleted_at:
                plan = MutationPlan(
                    operation="update",
                    table=TableRef(
                        schema=ir_type.source_table.schema, name=ir_type.source_table.name
                    ),
                    data={"deleted_at": datetime.now(timezone.utc)},
                    pk_column=pk_col,
                    pk_value=id,
                    filter_tree=auth_filter,
                )
            else:
                plan = MutationPlan(
                    operation="delete",
                    table=TableRef(
                        schema=ir_type.source_table.schema, name=ir_type.source_table.name
                    ),
                    pk_column=pk_col,
                    pk_value=id,
                    filter_tree=auth_filter,
                )

            compiler = self.db_adapter.compiler()
            compiled_query = compiler.compile_mutation(plan)

            result = await self.db_adapter.execute(compiled_query)
            if not result.data:
                return None
            return return_type(**result.data[0])

        return resolver

    def build(
        self,
        ir_types: list[GraphQLTypeIR],
        db_schema: DatabaseSchema | None = None,
        extensions: list[Any] | None = None,
    ) -> strawberry.Schema:
        if db_schema:
            self._build_enums(db_schema)

        # 1. Create base types
        for ir_type in ir_types:
            sb_type = self._build_strawberry_type(ir_type)
            self.generated_types[ir_type.name] = sb_type

        # 2. Attach relationship fields after all base types are registered
        for ir_type in ir_types:
            self._attach_relationships_to_strawberry_type(ir_type)

        query_annotations: dict[str, Any] = {}
        query_namespace: dict[str, Any] = {}

        mutation_annotations: dict[str, Any] = {}
        mutation_namespace: dict[str, Any] = {}

        # 3. Build root queries and mutations
        for ir_type in ir_types:
            sb_type = self.generated_types[ir_type.name]

            filter_input_type = create_filter_input_for_type(ir_type, self.map_scalar_type)
            order_by_input_type = create_order_by_input_for_type(ir_type)

            # List query name
            list_query_name = f"{ir_type.name.lower()}s"

            list_resolver_fn = self._create_list_resolver(ir_type, sb_type)
            list_resolver_fn.__annotations__ = {
                "info": Info,
                "where": Optional[filter_input_type],
                "order_by": Optional[list[order_by_input_type]],  # type: ignore[valid-type]
                "limit": Optional[int],
                "offset": Optional[int],
                "return": list[sb_type],  # type: ignore[valid-type]
            }

            query_annotations[list_query_name] = list[sb_type]  # type: ignore[valid-type]
            query_namespace[list_query_name] = strawberry.field(resolver=list_resolver_fn)

            # Connection query name
            connection_query_name = f"{ir_type.name.lower()}s_connection"
            conn_type = Connection[sb_type]  # type: ignore[valid-type]

            conn_resolver_fn = self._create_connection_resolver(ir_type, sb_type)
            conn_resolver_fn.__annotations__ = {
                "info": Info,
                "where": Optional[filter_input_type],
                "order_by": Optional[list[order_by_input_type]],  # type: ignore[valid-type]
                "first": Optional[int],
                "after": Optional[str],
                "return": conn_type,
            }

            query_annotations[connection_query_name] = conn_type
            query_namespace[connection_query_name] = strawberry.field(resolver=conn_resolver_fn)

            # Build Mutations ONLY for non-views
            if not ir_type.is_view:
                create_input_type, update_input_type = create_mutation_input_types(
                    ir_type, self.map_scalar_type
                )
                pk_field = next((f for f in ir_type.fields if f.is_primary_key), None)
                pk_type = self.map_scalar_type(pk_field.graphql_type) if pk_field else int

                # Create mutation: create_<type>(input: ...)
                create_name = f"create_{ir_type.name.lower()}"
                create_fn = self._create_create_mutation_resolver(ir_type, sb_type)
                create_fn.__annotations__ = {
                    "info": Info,
                    "input": create_input_type,
                    "return": Optional[sb_type],
                }
                mutation_annotations[create_name] = Optional[sb_type]
                mutation_namespace[create_name] = strawberry.mutation(resolver=create_fn)

                # Update mutation: update_<type>(id: ..., input: ...)
                update_name = f"update_{ir_type.name.lower()}"
                update_fn = self._create_update_mutation_resolver(ir_type, sb_type)
                update_annotations = {
                    "info": Info,
                    "id": pk_type,
                    "input": update_input_type,
                    "expected_version": Optional[int],
                    "return": Optional[sb_type],
                }

                update_fn.__annotations__ = update_annotations
                mutation_annotations[update_name] = Optional[sb_type]
                mutation_namespace[update_name] = strawberry.mutation(resolver=update_fn)

                # Delete mutation: delete_<type>(id: ...)
                delete_name = f"delete_{ir_type.name.lower()}"
                delete_fn = self._create_delete_mutation_resolver(ir_type, sb_type)
                delete_fn.__annotations__ = {
                    "info": Info,
                    "id": pk_type,
                    "return": Optional[sb_type],
                }
                mutation_annotations[delete_name] = Optional[sb_type]
                mutation_namespace[delete_name] = strawberry.mutation(resolver=delete_fn)

        query_namespace["__annotations__"] = query_annotations
        Query = strawberry.type(type("Query", (), query_namespace))

        Mutation = None
        if mutation_namespace:
            mutation_namespace["__annotations__"] = mutation_annotations
            Mutation = strawberry.type(type("Mutation", (), mutation_namespace))

        return strawberry.Schema(
            query=Query,
            mutation=Mutation,
            extensions=extensions if extensions else [],
            config=StrawberryConfig(auto_camel_case=False),
        )
