from typing import Any
import asyncio
from engine import execute_query


async def run_level3(tenant_id: int, user_id: int) -> list[dict[str, Any]]:
    results = []

    print("\n--- Level 3: Advanced Queries ---")

    # 1. Deep Nesting to trip complexity/depth budgets
    query1 = """
    query {
        users_connection(first: 5) {
            edges {
                node {
                    posts {
                        comments {
                            users {
                                posts {
                                    comments {
                                        users {
                                            id
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """
    res1 = await execute_query(query1, tenant_id=tenant_id, user_id=user_id)
    passed1 = res1["errors"] is not None and len(res1["errors"]) > 0

    results.append(
        {
            "name": "L3: Deep Nesting (Complexity Trip)",
            "passed": passed1,
            "queries": res1["query_count"],
            "latency_ms": res1["latency_ms"],
        }
    )

    # 2. Alias limit stress test
    query2 = "query {\n"
    for i in range(25):
        query2 += f"  alias{i}: users_connection(first: 1) {{ edges {{ node {{ id }} }} }}\n"
    query2 += "}"

    res2 = await execute_query(query2, tenant_id=tenant_id, user_id=user_id)
    passed2 = res2["errors"] is not None and len(res2["errors"]) > 0

    results.append(
        {
            "name": "L3: Alias Limit Stress Test",
            "passed": passed2,
            "queries": res2["query_count"],
            "latency_ms": res2["latency_ms"],
        }
    )

    # 3. Cross-tenant query attempt (Row-level auth block check)
    query3 = """
    query {
        posts_connection(where: { user_id: { eq: %d } }) {
            edges {
                node {
                    id
                }
            }
        }
    }
    """ % (user_id + 1)
    res3 = await execute_query(query3, tenant_id=tenant_id, user_id=user_id)
    passed3 = (
        res3["status"] == 200
        and not res3["errors"]
        and len(res3["data"]["posts_connection"]["edges"]) == 0
    )

    results.append(
        {
            "name": "L3: Cross-tenant row-level auth blocking",
            "passed": passed3,
            "queries": res3["query_count"],
            "latency_ms": res3["latency_ms"],
        }
    )

    # 4. Concurrent / Parallel requests (N+1 regression test)
    query4 = """
    query {
        posts_connection(first: 50) {
            edges {
                node {
                    id
                    title
                    users {
                        id
                        username
                    }
                    comments {
                        id
                        body
                        users {
                            id
                        }
                    }
                }
            }
        }
    }
    """

    tasks = [execute_query(query4, tenant_id=tenant_id, user_id=user_id) for _ in range(10)]
    res4_batch = await asyncio.gather(*tasks)

    all_passed = all(r["status"] == 200 and not r["errors"] for r in res4_batch)

    results.append(
        {
            "name": "L3: Concurrent Requests (DataLoader/N+1)",
            "passed": all_passed,
            "queries": -1,
            "latency_ms": max(r["latency_ms"] for r in res4_batch),
        }
    )

    # 5. Backward Pagination (last/before)
    # First get a forward cursor, then backward paginate from it.
    query5_setup = """
    query {
        posts_connection(first: 3) {
            edges {
                node { id }
                cursor
            }
        }
    }
    """
    res5_setup = await execute_query(query5_setup, tenant_id=tenant_id, user_id=user_id)
    passed5 = False
    queries5 = -1
    lat5 = -1

    if res5_setup["status"] == 200 and not res5_setup["errors"]:
        edges = res5_setup["data"]["posts_connection"]["edges"]
        if len(edges) >= 2:
            cursor = edges[1]["cursor"]  # get the cursor of the 2nd item
            query5 = f"""
            query {{
                posts_connection(last: 1, before: "{cursor}") {{
                    edges {{
                        node {{ id }}
                    }}
                }}
            }}
            """
            res5 = await execute_query(query5, tenant_id=tenant_id, user_id=user_id)
            passed5 = (
                res5["status"] == 200
                and not res5["errors"]
                and len(res5["data"]["posts_connection"]["edges"]) == 1
            )
            queries5 = res5_setup["query_count"] + res5["query_count"]
            lat5 = res5_setup["latency_ms"] + res5["latency_ms"]

    results.append(
        {
            "name": "L3: Backward Pagination (last/before)",
            "passed": passed5,
            "queries": queries5,
            "latency_ms": lat5,
        }
    )

    # 6. Many-to-Many Join Table
    query6 = """
    query {
        posts_connection(first: 5) {
            edges {
                node {
                    id
                    title
                    tags {
                        id
                        name
                    }
                }
            }
        }
    }
    """
    res6 = await execute_query(query6, tenant_id=tenant_id, user_id=user_id)
    passed6 = res6["status"] == 200 and not res6["errors"]

    results.append(
        {
            "name": "L3: Many-to-Many nested join",
            "passed": passed6,
            "queries": res6["query_count"],
            "latency_ms": res6["latency_ms"],
        }
    )

    return results
