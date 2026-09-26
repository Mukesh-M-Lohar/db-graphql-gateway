import httpx
import asyncpg
import time
from typing import Any
import jwt

DB_DSN = "postgresql://sgql_test:sgql_password@localhost:5433/sgql_test_db"
GRAPHQL_URL = "http://localhost:8000/graphql"

SECRET = "supersecretkeythatisatleast32byteslong!"
ISSUER = "integration-test-issuer"
AUDIENCE = "integration-test-audience"


def get_token(tenant_id: int, user_id: int) -> str:
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "sub": str(user_id),
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


async def execute_query(
    query: str, variables: dict[str, Any] | None = None, tenant_id: int = 1, user_id: int = 1
) -> dict[str, Any]:
    conn = await asyncpg.connect(DB_DSN)

    # Get current query stats state to diff against
    await conn.execute("SELECT pg_stat_statements_reset()")

    start_time = time.time()

    token = get_token(tenant_id, user_id)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers=headers,
            timeout=30.0,
        )

    end_time = time.time()

    # Get query count
    # Note: query count might be multiple due to DataLoader
    stats = await conn.fetch(
        "SELECT query, calls FROM pg_stat_statements WHERE query NOT LIKE '%pg_stat_statements%'"
    )
    total_queries = sum(row["calls"] for row in stats)

    await conn.close()

    result = response.json()
    return {
        "status": response.status_code,
        "data": result.get("data"),
        "errors": result.get("errors"),
        "latency_ms": (end_time - start_time) * 1000,
        "query_count": total_queries,
    }
