from typing import Any
from engine import execute_query


async def run_level4(tenant_id: int, user_id: int) -> list[dict[str, Any]]:
    results = []

    print("\n--- Level 4: Edge Cases & Advanced Mutations ---")

    # 1. Composite PK insert / update (Table: user_roles)
    # We will try to insert a user_role, then delete it.
    
    mutation1 = """
    mutation($id: JSON!) {
        create_user_roles(input: { user_id: 1, role_id: 1, assigned_by: 1 }) {
            user_id
            role_id
        }
        delete_user_roles(id: $id) {
            user_id
        }
    }
    """
    res1 = await execute_query(mutation1, tenant_id=tenant_id, user_id=user_id, variables={"id": {"user_id": 1, "role_id": 1}})
    passed1 = res1["errors"] is None and "create_user_roles" in res1["data"]

    results.append(
        {
            "name": "L4: Composite PK Mutation (Insert/Delete)",
            "passed": passed1,
            "queries": res1["query_count"],
            "latency_ms": res1["latency_ms"],
        }
    )

    # 2. PK-less table read-only test
    # We should not be able to create_audit_logs, but we should be able to query audit_logs
    mutation2 = """
    mutation {
        create_audit_logs(input: { action: "login" }) {
            action
        }
    }
    """
    res2 = await execute_query(mutation2, tenant_id=tenant_id, user_id=user_id)
    passed2_mut = res2["errors"] is not None and "Cannot query field" in str(res2["errors"][0])

    query2 = """
    query {
        audit_logs {
            action
            user_id
        }
    }
    """
    res2_q = await execute_query(query2, tenant_id=tenant_id, user_id=user_id)
    passed2_q = res2_q["errors"] is None and "audit_logs" in res2_q["data"]

    results.append(
        {
            "name": "L4: PK-less table is read-only",
            "passed": passed2_mut and passed2_q,
            "queries": res2["query_count"] + res2_q["query_count"],
            "latency_ms": res2["latency_ms"] + res2_q["latency_ms"],
        }
    )

    return results
