from strawberry.types import Info
from db_graphql_gateway.schema.ir.models import GraphQLTypeIR


class QueryPlanner:
    @staticmethod
    def extract_selected_columns(info: Info, ir_type: GraphQLTypeIR) -> list[str]:
        """Extract requested scalar field names from GraphQL AST and map to database column names."""
        selected_db_columns: set[str] = set()

        if not hasattr(info, "selected_fields") or not info.selected_fields:
            return []

        root_field = info.selected_fields[0]

        # Build mapping from GraphQL field name -> source column name
        field_to_col: dict[str, str] = {}
        for f in ir_type.fields:
            if not f.relationship and f.source_column:
                field_to_col[f.name] = f.source_column.name

        for selected in root_field.selections:
            name = getattr(selected, "name", None)
            if name and name in field_to_col:
                selected_db_columns.add(field_to_col[name])

        # Always include foreign key columns if relationships might be queried
        for f in ir_type.fields:
            if f.relationship:
                for src_col in f.relationship.join.source_columns:
                    selected_db_columns.add(src_col)

        return list(selected_db_columns) if selected_db_columns else []
