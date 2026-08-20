from typing import Any, Type
from graphql import (
    ASTValidationRule,
    FieldNode,
    GraphQLError,
    InlineFragmentNode,
    OperationDefinitionNode,
)


def create_max_depth_rule(max_depth: int = 5) -> Type[ASTValidationRule]:
    class CustomMaxDepthRule(ASTValidationRule):
        def enter_operation_definition(
            self, node: OperationDefinitionNode, key: Any, parent: Any, path: Any, ancestors: Any
        ) -> None:
            depth = self._calculate_depth(node.selection_set, 1)
            if depth > max_depth:
                self.report_error(
                    GraphQLError(
                        f"Query exceeds maximum depth of {max_depth} (actual depth: {depth})"
                    )
                )

        def _calculate_depth(self, selection_set: Any, current_depth: int) -> int:
            if (
                not selection_set
                or not hasattr(selection_set, "selections")
                or not selection_set.selections
            ):
                return current_depth

            max_sub_depth = current_depth
            for selection in selection_set.selections:
                if isinstance(selection, FieldNode):
                    if selection.name.value.startswith("__"):
                        continue
                    if selection.selection_set:
                        sub_depth = self._calculate_depth(
                            selection.selection_set, current_depth + 1
                        )
                        max_sub_depth = max(max_sub_depth, sub_depth)
                elif isinstance(selection, InlineFragmentNode):
                    if selection.selection_set:
                        sub_depth = self._calculate_depth(selection.selection_set, current_depth)
                        max_sub_depth = max(max_sub_depth, sub_depth)

            return max_sub_depth

    return CustomMaxDepthRule


def create_max_aliases_rule(max_aliases: int = 15) -> Type[ASTValidationRule]:
    class CustomMaxAliasesRule(ASTValidationRule):
        def enter_operation_definition(
            self, node: OperationDefinitionNode, key: Any, parent: Any, path: Any, ancestors: Any
        ) -> None:
            alias_count = self._count_aliases(node.selection_set)
            if alias_count > max_aliases:
                self.report_error(
                    GraphQLError(
                        f"Query exceeds maximum alias limit of {max_aliases} (actual aliases: {alias_count})"
                    )
                )

        def _count_aliases(self, selection_set: Any) -> int:
            if (
                not selection_set
                or not hasattr(selection_set, "selections")
                or not selection_set.selections
            ):
                return 0

            count = 0
            for selection in selection_set.selections:
                if isinstance(selection, FieldNode):
                    if selection.alias:
                        count += 1
                    if selection.selection_set:
                        count += self._count_aliases(selection.selection_set)
                elif isinstance(selection, InlineFragmentNode):
                    if selection.selection_set:
                        count += self._count_aliases(selection.selection_set)

            return count

    return CustomMaxAliasesRule


def create_introspection_lockdown_rule() -> Type[ASTValidationRule]:
    """Rejects __schema and __type queries (used for introspection) in production."""

    class IntrospectionLockdownRule(ASTValidationRule):
        def enter_field(
            self, node: FieldNode, key: Any, parent: Any, path: Any, ancestors: Any
        ) -> None:
            if node.name.value in ("__schema", "__type"):
                self.report_error(
                    GraphQLError("Introspection queries are disabled in this environment.")
                )

    return IntrospectionLockdownRule
