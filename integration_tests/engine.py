import httpx
import asyncpg
import time
from typing import Any
import jwt

import os

DB_DSN = os.getenv(
    "SGQL_DATABASE_URL", "postgresql://sgql_test:sgql_password@localhost:5433/sgql_test_db"
)
GRAPHQL_URL = "http://localhost:8000/graphql"
ADMIN_URL = "http://localhost:8000/admin"

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
    is_sqlite = DB_DSN.startswith("sqlite")

    async with httpx.AsyncClient() as client:
        if is_sqlite:
            # Reset the SQLite statement counter on the gateway server before the query
            await client.get(f"{ADMIN_URL}/query-count/reset", timeout=5.0)
        else:
            # Reset pg_stat_statements for Postgres
            conn = await asyncpg.connect(DB_DSN)
            await conn.execute("SELECT pg_stat_statements_reset()")
            await conn.close()

        start_time = time.time()

        token = get_token(tenant_id, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers=headers,
            timeout=30.0,
        )

        end_time = time.time()

        if is_sqlite:
            # Read back the counter from the gateway server
            count_resp = await client.get(f"{ADMIN_URL}/query-count", timeout=5.0)
            total_queries = count_resp.json()["count"]
        else:
            conn = await asyncpg.connect(DB_DSN)
            stats = await conn.fetch(
                """
                SELECT query, calls FROM pg_stat_statements
                WHERE query NOT LIKE '%pg_stat_statements%'
                  AND query NOT LIKE 'SET %'
                  AND query NOT LIKE 'BEGIN%'
                  AND query NOT LIKE 'COMMIT%'
                  AND query NOT LIKE 'ROLLBACK%'
                  AND query NOT LIKE 'SHOW %'
                  AND query NOT LIKE 'SELECT version%'
                  AND query NOT LIKE 'SELECT current_%'
                  AND query NOT ILIKE '%pg_catalog%'
                  AND query NOT ILIKE '%information_schema%'
                  AND (
                    query ILIKE 'SELECT %'
                    OR query ILIKE 'INSERT %'
                    OR query ILIKE 'UPDATE %'
                    OR query ILIKE 'DELETE %'
                  )
                """
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
