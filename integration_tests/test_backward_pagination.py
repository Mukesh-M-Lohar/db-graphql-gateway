import asyncio
from engine import execute_query


async def debug():
    # 1. First fetch first: 5 to get cursors
    q1 = """
    query {
        tasks(first: 5, order_by: [{ id: ASC }]) {
            edges { cursor node { id title } }
            pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
        }
    }
    """
    res1 = await execute_query(q1, tenant_id=1, user_id=1)
    edges = res1["data"]["tasks"]["edges"]
    page_info = res1["data"]["tasks"]["pageInfo"]
    print("FORWARD:", [e["node"]["id"] for e in edges])
    print("PAGE INFO:", page_info)

    # 2. Now use before with last
    cursor = edges[3]["cursor"]  # 4th element's cursor
    q2 = f"""
    query {{
        tasks(last: 2, before: "{cursor}", order_by: [{{ id: ASC }}]) {{
            edges {{ cursor node {{ id title }} }}
            pageInfo {{ hasNextPage hasPreviousPage startCursor endCursor }}
        }}
    }}
    """
    res2 = await execute_query(q2, tenant_id=1, user_id=1)
    print("BACKWARD DATA:", res2["data"])
    if res2.get("errors"):
        print("ERRORS:", res2["errors"])
    else:
        edges2 = res2["data"]["tasks"]["edges"]
        page_info2 = res2["data"]["tasks"]["pageInfo"]
        print("BACKWARD:", [e["node"]["id"] for e in edges2])
        print("BACKWARD PAGE INFO:", page_info2)


asyncio.run(debug())
