from typing import Any, Optional
import enum
import strawberry

from db_graphql_gateway.database.adapters.interfaces import (
    FilterCondition,
    FilterGroup,
    OrderByItem,
)
from db_graphql_gateway.schema.ir.models import GraphQLTypeIR


@enum.unique
class SortDirectionEnum(str, enum.Enum):
    ASC = "ASC"
    DESC = "DESC"


SortDirection = strawberry.enum(SortDirectionEnum)


def create_filter_input_for_type(ir_type: GraphQLTypeIR, scalar_mapper_fn: Any) -> Any:
    """Dynamically build Strawberry InputType for filtering a given IR type."""
    field_annotations: dict[str, Any] = {}

    for field in ir_type.fields:
        python_scalar: Any = scalar_mapper_fn(field.graphql_type)

        # Build individual field filter input
        scalar_filter_annotations: dict[str, Any] = {
            "eq": python_scalar | None,
            "neq": python_scalar | None,
            "gt": python_scalar | None,
            "gte": python_scalar | None,
            "lt": python_scalar | None,
            "lte": python_scalar | None,
            "in_": list[python_scalar] | None,
            "is_null": bool | None,
        }
        if python_scalar is str:
            scalar_filter_annotations["like"] = str | None
            scalar_filter_annotations["ilike"] = str | None
            scalar_filter_annotations["contains"] = str | None

        # Use field.name for scalar filter type name uniqueness
        filter_cls_name = f"{ir_type.name}_{field.name}_FilterInput"
        scalar_filter_cls = strawberry.input(
            type(
                filter_cls_name,
                (),
                {
                    "__annotations__": scalar_filter_annotations,
                    "eq": None,
                    "neq": None,
                    "gt": None,
                    "gte": None,
                    "lt": None,
                    "lte": None,
                    "in_": None,
                    "is_null": None,
                    "like": None,
                    "ilike": None,
                    "contains": None,
                },
            )
        )

        field_annotations[field.name] = Optional[scalar_filter_cls]

    # Recursive logical operators
    filter_input_name = f"{ir_type.name}FilterInput"

    filter_input_cls_dict: dict[str, Any] = {"AND": None, "OR": None, "NOT": None}
    for field in ir_type.fields:
        filter_input_cls_dict[field.name] = None

    filter_input_cls = type(filter_input_name, (), filter_input_cls_dict)
    field_annotations["AND"] = list[filter_input_cls] | None  # type: ignore
    field_annotations["OR"] = list[filter_input_cls] | None  # type: ignore
    field_annotations["NOT"] = filter_input_cls | None

    filter_input_cls.__annotations__ = field_annotations
    return strawberry.input(filter_input_cls)


def create_order_by_input_for_type(ir_type: GraphQLTypeIR) -> Any:
    """Dynamically build Strawberry InputType for sorting a given IR type."""
    annotations: dict[str, Any] = {field.name: Optional[SortDirection] for field in ir_type.fields}
    cls_dict: dict[str, Any] = {field.name: None for field in ir_type.fields}
    cls_dict["__annotations__"] = annotations
    class_name = f"{ir_type.name}OrderByInput"
    cls = type(class_name, (), cls_dict)
    return strawberry.input(cls)


def parse_filter_input(filter_obj: Any) -> FilterGroup | FilterCondition | None:
    if filter_obj is None:
        return None

    # Check for AND, OR, NOT
    and_list = getattr(filter_obj, "AND", None)
    if and_list:
        parsed_sub = [parse_filter_input(sub) for sub in and_list if sub is not None]
        return FilterGroup(operator="AND", conditions=[p for p in parsed_sub if p is not None])

    or_list = getattr(filter_obj, "OR", None)
    if or_list:
        parsed_sub = [parse_filter_input(sub) for sub in or_list if sub is not None]
        return FilterGroup(operator="OR", conditions=[p for p in parsed_sub if p is not None])

    not_obj = getattr(filter_obj, "NOT", None)
    if not_obj:
        parsed_sub_not: Any = parse_filter_input(not_obj)
        if parsed_sub_not:
            if isinstance(parsed_sub_not, (FilterCondition, FilterGroup)):
                return FilterGroup(operator="NOT", conditions=[parsed_sub_not])

    # Check field level filters
    conditions: list[FilterCondition | FilterGroup] = []
    for attr in dir(filter_obj):
        if attr.startswith("_") or attr in ("AND", "OR", "NOT"):
            continue
        field_filter = getattr(filter_obj, attr, None)
        if field_filter is None:
            continue

        for op_attr in (
            "eq",
            "neq",
            "gt",
            "gte",
            "lt",
            "lte",
            "in_",
            "like",
            "ilike",
            "contains",
            "is_null",
        ):
            val = getattr(field_filter, op_attr, None)
            if val is not None:
                op_name = "in" if op_attr == "in_" else op_attr
                conditions.append(FilterCondition(column=attr, op=op_name, value=val))

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return FilterGroup(operator="AND", conditions=conditions)


def parse_order_by_input(order_by_list: list[Any] | None) -> list[OrderByItem] | None:
    if not order_by_list:
        return None

    items: list[OrderByItem] = []
    for order_obj in order_by_list:
        if order_obj is None:
            continue
        for attr in dir(order_obj):
            if attr.startswith("_"):
                continue
            val = getattr(order_obj, attr, None)
            if val is not None:
                dir_str = val.value if hasattr(val, "value") else str(val)
                items.append(OrderByItem(column=attr, direction=dir_str))

    return items if items else None
