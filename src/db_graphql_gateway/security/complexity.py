from typing import Any, Type
from graphql import (
    ASTValidationRule,
    FieldNode,
    GraphQLError,
    InlineFragmentNode,
    OperationDefinitionNode,
)


def create_max_complexity_rule(max_complexity: int = 100) -> Type[ASTValidationRule]:
    """
    Creates an AST validation rule that limits the maximum query complexity.
    Complexity is calculated by assigning a cost to each field.
    Nested fields multiply the cost.
    """

    class CustomMaxComplexityRule(ASTValidationRule):
        def enter_operation_definition(
            self, node: OperationDefinitionNode, key: Any, parent: Any, path: Any, ancestors: Any
        ) -> None:
            complexity = self._calculate_complexity(node.selection_set, 1)
            if complexity > max_complexity:
                self.report_error(
                    GraphQLError(
                        f"Query exceeds maximum complexity of {max_complexity} (actual complexity: {complexity})"
                    )
                )

        def _calculate_complexity(self, selection_set: Any, multiplier: int) -> int:
            if (
                not selection_set
                or not hasattr(selection_set, "selections")
                or not selection_set.selections
            ):
                return 0

            cost = 0
            for selection in selection_set.selections:
                if isinstance(selection, FieldNode):
                    if selection.name.value.startswith("__"):
                        continue

                    # Base cost for a field
                    field_cost = 1 * multiplier
                    cost += field_cost

                    if selection.selection_set:
                        # Nested selection, increase multiplier (e.g., assuming average 10 items per list)
                        sub_cost = self._calculate_complexity(
                            selection.selection_set, multiplier * 10
                        )
                        cost += sub_cost
                elif isinstance(selection, InlineFragmentNode):
                    if selection.selection_set:
                        cost += self._calculate_complexity(selection.selection_set, multiplier)

            return cost

    return CustomMaxComplexityRule
