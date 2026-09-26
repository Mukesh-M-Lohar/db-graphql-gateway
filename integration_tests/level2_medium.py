from typing import Any
from engine import execute_query


async def run_level2(tenant_id: int, user_id: int) -> list[dict[str, Any]]:
    results = []
    print("\n--- Level 2: Medium Queries ---")

    query1 = """
    query {
        users_connection(first: 5) {
            edges {
                node {
                    id
                    username
                    posts {
                        id
                        title
                        comments {
                            id
                            body
                        }
                    }
                }
            }
        }
    }
    """
    res1 = await execute_query(query1, tenant_id=tenant_id, user_id=user_id)
    passed1 = res1["status"] == 200 and not res1["errors"]
    results.append(
        {
            "name": "L2: Nested (User -> Posts -> Comments)",
            "passed": passed1,
            "queries": res1["query_count"],
            "latency_ms": res1["latency_ms"],
        }
    )

    query2 = (
        """
    query {
        posts_connection(
            where: { user_id: { eq: %d } },
            order_by: { created_at: DESC },
            first: 10
        ) {
            edges {
                node {
                    id
                    title
                    created_at
                }
                cursor
            }
            page_info {
                has_next_page
                end_cursor
            }
        }
    }
    """
        % user_id
    )
    res2 = await execute_query(query2, tenant_id=tenant_id, user_id=user_id)
    passed2 = res2["status"] == 200 and not res2["errors"]
    results.append(
        {
            "name": "L2: Filter + Sort + Pagination",
            "passed": passed2,
            "queries": res2["query_count"],
            "latency_ms": res2["latency_ms"],
        }
    )

    query3 = (
        """
    mutation {
        create_comments(input: { post_id: 1, user_id: %d, body: "Great post!" }) {
            id
            body
            post_id
        }
    }
    """
        % user_id
    )
    res3 = await execute_query(query3, tenant_id=tenant_id, user_id=user_id)
    passed3 = res3["status"] == 200 and not res3["errors"]
    results.append(
        {
            "name": "L2: Mutation Create Comment",
            "passed": passed3,
            "queries": res3["query_count"],
            "latency_ms": res3["latency_ms"],
        }
    )

    return results
