from db_graphql_gateway.database.adapters.interfaces import TypeMapper
from db_graphql_gateway.database.models.schema import DatabaseSchema, Relationship
from db_graphql_gateway.schema.config import GatewayConfig
from db_graphql_gateway.schema.ir.models import (
    ColumnRef,
    GraphQLFieldIR,
    GraphQLRelationshipIR,
    GraphQLTypeIR,
    JoinPath,
    TableRef,
)


class IRBuilder:
    def __init__(self, type_mapper: TypeMapper) -> None:
        self.type_mapper = type_mapper

    def build(self, db_schema: DatabaseSchema, config: GatewayConfig) -> list[GraphQLTypeIR]:
        types_map: dict[str, GraphQLTypeIR] = {}
        junction_tables: set[str] = set()

        # 0. Pass 0: Detect junction tables for Many-to-Many
        for namespace_name, namespace in db_schema.namespaces.items():
            for table_name, table in namespace.tables.items():
                m2o_rels = [r for r in table.relationships if r.kind == "many_to_one"]
                o2m_rels = [r for r in table.relationships if r.kind == "one_to_many"]

                # Heuristic: exactly 2 many-to-one FKs, no one-to-many inverses
                if len(m2o_rels) == 2 and len(o2m_rels) == 0:
                    fk_cols = set(m2o_rels[0].source_columns + m2o_rels[1].source_columns)
                    non_fk_cols = [c.name for c in table.columns if c.name not in fk_cols]

                    allowed_extra = {"id", "created_at", "updated_at"}
                    if all(c in allowed_extra for c in non_fk_cols):
                        junction_tables.add(table_name)

                        t1_name = m2o_rels[0].target_table
                        t2_name = m2o_rels[1].target_table

                        t1 = namespace.tables.get(t1_name)
                        t2 = namespace.tables.get(t2_name)

                        if t1 and t2:
                            # Add many_to_many on T1
                            t1.relationships.append(
                                Relationship(
                                    name=t2_name if t2_name.endswith("s") else f"{t2_name}s",
                                    target_table=t2_name,
                                    kind="many_to_many",
                                    source_columns=m2o_rels[0].target_columns,
                                    target_columns=m2o_rels[1].target_columns,
                                    join_table=table_name,
                                    join_source_columns=m2o_rels[0].source_columns,
                                    join_target_columns=m2o_rels[1].source_columns,
                                )
                            )
                            # Add many_to_many on T2
                            t2.relationships.append(
                                Relationship(
                                    name=t1_name if t1_name.endswith("s") else f"{t1_name}s",
                                    target_table=t1_name,
                                    kind="many_to_many",
                                    source_columns=m2o_rels[1].target_columns,
                                    target_columns=m2o_rels[0].target_columns,
                                    join_table=table_name,
                                    join_source_columns=m2o_rels[1].source_columns,
                                    join_target_columns=m2o_rels[0].source_columns,
                                )
                            )

        # 1. First pass: build base scalar types & fields
        for namespace_name, namespace in db_schema.namespaces.items():
            for table_name, table in namespace.tables.items():
                if table_name in junction_tables:
                    continue
                table_config = config.tables.get(table_name)
                if table_config and table_config.hidden:
                    continue

                graphql_name = table_name
                if table_config and table_config.graphql_name:
                    graphql_name = table_config.graphql_name

                type_ir = GraphQLTypeIR(
                    name=graphql_name,
                    source_table=TableRef(schema=namespace_name, name=table_name),
                    is_view=False,
                    description=table.description,
                )

                for col in table.columns:
                    field_config = None
                    if table_config:
                        field_config = table_config.fields.get(col.name)

                    if field_config and field_config.hidden is not None:
                        if field_config.hidden:
                            continue
                    else:
                        is_sensitive = any(
                            pattern in col.name.lower()
                            for pattern in config.sensitive_field_patterns
                        )
                        if is_sensitive:
                            continue

                    field_name = col.name
                    if field_config and field_config.graphql_name:
                        field_name = field_config.graphql_name

                    if col.type in namespace.enums:
                        graphql_type = col.type
                    else:
                        graphql_type = self.type_mapper.to_graphql_type(col)

                    field_ir = GraphQLFieldIR(
                        name=field_name,
                        graphql_type=str(graphql_type),
                        nullable=col.nullable,
                        source_column=ColumnRef(
                            table=TableRef(schema=namespace_name, name=table_name),
                            name=col.name,
                        ),
                        is_primary_key=col.is_primary_key,
                    )
                    type_ir.fields.append(field_ir)

                types_map[table_name] = type_ir
                if not any(f.is_primary_key for f in type_ir.fields):
                    type_ir.is_read_only = True

            for view_name, view in namespace.views.items():
                view_config = config.tables.get(view_name)
                if view_config and view_config.hidden:
                    continue

                graphql_name = view_name
                if view_config and view_config.graphql_name:
                    graphql_name = view_config.graphql_name

                type_ir = GraphQLTypeIR(
                    name=graphql_name,
                    source_table=TableRef(schema=namespace_name, name=view_name),
                    is_view=True,
                    description=view.description,
                )

                for col in view.columns:
                    field_config = None
                    if view_config:
                        field_config = view_config.fields.get(col.name)

                    if field_config and field_config.hidden:
                        continue

                    field_name = col.name
                    if field_config and field_config.graphql_name:
                        field_name = field_config.graphql_name

                    if col.type in namespace.enums:
                        graphql_type = col.type
                    else:
                        graphql_type = self.type_mapper.to_graphql_type(col)

                    field_ir = GraphQLFieldIR(
                        name=field_name,
                        graphql_type=str(graphql_type),
                        nullable=col.nullable,
                        source_column=ColumnRef(
                            table=TableRef(schema=namespace_name, name=view_name),
                            name=col.name,
                        ),
                    )
                    type_ir.fields.append(field_ir)

                types_map[view_name] = type_ir

        # 2. Second pass: build relationship fields from DatabaseSchema relationships
        for namespace_name, namespace in db_schema.namespaces.items():
            for table_name, table in namespace.tables.items():
                if table_name not in types_map:
                    continue

                type_ir = types_map[table_name]

                for rel in table.relationships:
                    target_table_name = rel.target_table
                    if target_table_name not in types_map:
                        continue

                    target_type_ir = types_map[target_table_name]

                    join_path = JoinPath(
                        source_columns=rel.source_columns,
                        target_columns=rel.target_columns,
                        join_table=TableRef(schema=namespace_name, name=rel.join_table)
                        if rel.join_table
                        else None,
                        join_source_columns=rel.join_source_columns,
                        join_target_columns=rel.join_target_columns,
                    )

                    rel_ir = GraphQLRelationshipIR(
                        kind=rel.kind,
                        target_type=target_type_ir.name,
                        join=join_path,
                    )

                    is_list = rel.kind in ("one_to_many", "many_to_many")
                    graphql_type = f"[{target_type_ir.name}]" if is_list else target_type_ir.name

                    field_ir = GraphQLFieldIR(
                        name=rel.name,
                        graphql_type=graphql_type,
                        nullable=True,
                        relationship=rel_ir,
                    )
                    type_ir.fields.append(field_ir)

        return list(types_map.values())
