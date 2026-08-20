from dataclasses import dataclass, field
from typing import Any

from db_graphql_gateway.auth.interfaces import AuthContext
from db_graphql_gateway.database.adapters.interfaces import FilterCondition, FilterGroup


@dataclass
class PolicyRule:
    column: str
    op: str  # eq, neq, gt, gte, lt, lte, in
    value_template: str  # "$user_id", "$claims.tenant_id", or static literal


@dataclass
class TablePolicy:
    table: str
    read_rules: list[PolicyRule] = field(default_factory=list)


class AuthorizationEngine:
    def __init__(self, policies: list[TablePolicy] | None = None) -> None:
        self.policies: dict[str, TablePolicy] = {p.table: p for p in (policies or [])}

    def add_policy(self, policy: TablePolicy) -> None:
        self.policies[policy.table] = policy

    def _resolve_template_value(self, template: str, auth_ctx: AuthContext) -> Any:
        if template == "$user_id":
            return auth_ctx.user_id
        if template.startswith("$claims."):
            claim_name = template[len("$claims.") :]
            return auth_ctx.claims.get(claim_name)
        if template.startswith("$roles"):
            return auth_ctx.roles
        return template

    def get_read_filter(
        self, table_name: str, auth_ctx: AuthContext | None
    ) -> FilterGroup | FilterCondition | None:
        policy = self.policies.get(table_name)
        if not policy or not policy.read_rules:
            return None

        # Unauthenticated access when table policies exist -> evaluate to FALSE
        if not auth_ctx or not auth_ctx.is_authenticated:
            return FilterGroup(operator="NOT", conditions=[])  # Always false

        conditions: list[FilterCondition | FilterGroup] = []
        for rule in policy.read_rules:
            resolved_val = self._resolve_template_value(rule.value_template, auth_ctx)
            if resolved_val is None:
                # If required claim/user_id is missing, deny access
                return FilterGroup(operator="NOT", conditions=[])

            conditions.append(FilterCondition(column=rule.column, op=rule.op, value=resolved_val))

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return FilterGroup(operator="AND", conditions=conditions)
