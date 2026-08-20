from typing import Any, Callable, Type
import strawberry

from db_graphql_gateway.schema.ir.models import GraphQLTypeIR


def create_mutation_input_types(
    ir_type: GraphQLTypeIR,
    map_scalar_fn: Callable[[str], Type[Any]],
) -> tuple[type, type]:
    # 1. CreateInput type
    create_annotations: dict[str, Any] = {}
    create_dict: dict[str, Any] = {}

    for field in ir_type.fields:
        if field.relationship or field.is_primary_key or field.name == "id":
            continue

        python_type = map_scalar_fn(field.graphql_type)
        if field.nullable:
            create_annotations[field.name] = python_type | None
            create_dict[field.name] = None
        else:
            create_annotations[field.name] = python_type

    create_dict["__annotations__"] = create_annotations
    create_cls = type(f"Create{ir_type.name}Input", (), create_dict)
    create_input_type = strawberry.input(create_cls)

    # 2. UpdateInput type (all fields optional)
    update_annotations: dict[str, Any] = {}
    update_dict: dict[str, Any] = {}

    for field in ir_type.fields:
        if field.relationship or field.is_primary_key or field.name == "id":
            continue

        python_type = map_scalar_fn(field.graphql_type)
        update_annotations[field.name] = python_type | None
        update_dict[field.name] = None

    update_dict["__annotations__"] = update_annotations
    update_cls = type(f"Update{ir_type.name}Input", (), update_dict)
    update_input_type = strawberry.input(update_cls)

    return create_input_type, update_input_type
