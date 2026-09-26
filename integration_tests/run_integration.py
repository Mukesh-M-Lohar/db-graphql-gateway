import asyncio
from typing import Any
import sys
import asyncpg
from level1_basic import run_level1
from level2_medium import run_level2
from level3_advanced import run_level3

DB_DSN = "postgresql://sgql_test:sgql_password@localhost:5433/sgql_test_db"


def print_report(results: list[dict[str, Any]]) -> None:
    print("\n\n" + "=" * 50)
    print(" INTEGRATION TEST REPORT ")
    print("=" * 50)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    for r in results:
        status_icon = "✅" if r["passed"] else "❌"
        q_str = f"{r['queries']} queries" if r["queries"] >= 0 else "N/A queries"
        print(f"{status_icon} {r['name']} ({r['latency_ms']:.1f}ms, {q_str})")

    print("-" * 50)
    print(f"PASS: {passed} / {total}")

    if passed < total:
        sys.exit(1)


async def main() -> None:
    print("Fetching active user from DB for tests...")
    conn = await asyncpg.connect(DB_DSN)

    # Get a power user (highest post count)
    user = await conn.fetchrow("""
        SELECT u.id as user_id, u.tenant_id 
        FROM users u 
        JOIN posts p ON p.user_id = u.id 
        GROUP BY u.id, u.tenant_id 
        ORDER BY count(p.id) DESC 
        LIMIT 1
    """)

    await conn.close()

    if not user:
        print("Error: No users found. Did seed script run?")
        sys.exit(1)

    tenant_id = user["tenant_id"]
    user_id = user["user_id"]

    print(f"Running tests as Tenant: {tenant_id}, User: {user_id}")

    all_results = []

    all_results.extend(await run_level1(tenant_id, user_id))
    all_results.extend(await run_level2(tenant_id, user_id))
    all_results.extend(await run_level3(tenant_id, user_id))

    print_report(all_results)


if __name__ == "__main__":
    asyncio.run(main())
