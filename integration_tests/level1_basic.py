from typing import Any
from engine import execute_query


async def run_level1(tenant_id: int, user_id: int) -> list[dict[str, Any]]:
    results = []

    print("\n--- Level 1: Basic Queries ---")

    # 1. Single-entity query
    query1 = """
    query {
        users_connection(first: 10) {
            edges {
                node {
                    id
                    username
                    email
                }
            }
        }
    }
    """
    res1 = await execute_query(query1, tenant_id=tenant_id, user_id=user_id)
    passed1 = res1["status"] == 200 and not res1["errors"]

    results.append(
        {
            "name": "L1: Simple fetch users",
            "passed": passed1,
            "queries": res1["query_count"],
            "latency_ms": res1["latency_ms"],
        }
    )

    # 2. Simple filter
    query2 = """
    query {
        posts_connection(where: { title: { contains: "a" } }, first: 5) {
            edges {
                node {
                    id
                    title
                }
            }
        }
    }
    """
    res2 = await execute_query(query2, tenant_id=tenant_id, user_id=user_id)
    passed2 = res2["status"] == 200 and not res2["errors"]

    results.append(
        {
            "name": "L1: Filter posts by title contains",
            "passed": passed2,
            "queries": res2["query_count"],
            "latency_ms": res2["latency_ms"],
        }
    )

    return results
