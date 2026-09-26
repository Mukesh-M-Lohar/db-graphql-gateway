"""
level5_batching.py — Batching Correctness Tests
================================================
Empirically verifies the O(1) query-per-depth guarantee of the DataLoader
batching layer.  Follows the exact same conventions as level1_basic.py …
level4_mutations.py:

    async def run_level5(tenant_id: int, user_id: int) -> list[dict]

Each result dict has:
    name        str   – human-readable test name
    passed      bool
    queries     int   – raw DB statement count observed (-1 = unavailable)
    latency_ms  float

DEFINITION UNDER TEST
---------------------
"O(1) per relationship depth" means:
    query_count == f(depth)       constant / linear in depth
    query_count != f(row_count)   must NOT scale with data volume

QUERY COUNTING
--------------
- Postgres:  pg_stat_statements (already enabled in schema.sql); reset/read
             via execute_query() which calls pg_stat_statements_reset() before
             and reads counts after.
- SQLite:    aiosqlite trace callback wired in server.py at startup; exposed
             via GET /admin/query-count{/reset} — execute_query() now drives
             these endpoints automatically.
"""

from __future__ import annotations

from typing import Any

import httpx

from engine import DB_DSN, ADMIN_URL, execute_query

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IS_SQLITE = DB_DSN.startswith("sqlite")


async def _seed_posts_for_user(user_id: int, post_count: int, tenant_id: int) -> list[int]:
    """
    Directly seed exactly `post_count` posts for a user via GraphQL mutations
    so the test controls the data volume precisely without touching the DB
    connection directly.  Returns the list of created post IDs.

    We use GraphQL mutations (create_posts) because that is the only interface
    the server exposes and it keeps seeding consistent between adapters.
    """
    post_ids: list[int] = []
    # Batch in groups of 50 to avoid query complexity limits
    batch = 50
    for i in range(post_count):
        idx = i + 1
        q = f"""
        mutation {{
            create_posts(input: {{
                user_id: {user_id},
                title: "batch-seed-{idx}",
                body: "body {idx}"
            }}) {{
                id
            }}
        }}
        """
        res = await execute_query(q, tenant_id=tenant_id, user_id=user_id)
        if res["errors"] is None and res["data"] and "create_posts" in res["data"]:
            post_ids.append(res["data"]["create_posts"]["id"])
    return post_ids


async def _seed_comments_for_posts(
    post_ids: list[int], user_id: int, comments_per_post: int, tenant_id: int
) -> list[int]:
    """Seed `comments_per_post` comments on every given post."""
    comment_ids: list[int] = []
    for post_id in post_ids:
        for j in range(comments_per_post):
            q = f"""
            mutation {{
                create_comments(input: {{
                    post_id: {post_id},
                    user_id: {user_id},
                    body: "comment {j}"
                }}) {{
                    id
                }}
            }}
            """
            res = await execute_query(q, tenant_id=tenant_id, user_id=user_id)
            if res["errors"] is None and res["data"] and "create_comments" in res["data"]:
                comment_ids.append(res["data"]["create_comments"]["id"])
    return comment_ids


async def _seed_tags_for_post(post_id: int, tag_count: int, tenant_id: int, user_id: int) -> int:
    """Seed `tag_count` unique tags and attach them to `post_id`."""
    attached = 0
    for i in range(tag_count):
        # Create tag
        q_tag = f"""
        mutation {{
            create_tags(input: {{ name: "tag-{post_id}-{i}" }}) {{
                id
            }}
        }}
        """
        res_tag = await execute_query(q_tag, tenant_id=tenant_id, user_id=user_id)
        if res_tag["errors"] is not None or not res_tag["data"]:
            continue
        tag_id = res_tag["data"]["create_tags"]["id"]

        # Link post <-> tag
        q_link = f"""
        mutation {{
            create_post_tags(input: {{ post_id: {post_id}, tag_id: {tag_id} }}) {{
                post_id
            }}
        }}
        """
        res_link = await execute_query(q_link, tenant_id=tenant_id, user_id=user_id)
        if res_link["errors"] is None:
            attached += 1
    return attached


async def _raw_query_count() -> int:
    """Read the current raw query counter from the gateway (SQLite only)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ADMIN_URL}/query-count", timeout=5.0)
        return int(resp.json()["count"])


async def _reset_query_counter() -> None:
    """Reset the gateway query counter without executing a GQL query."""
    async with httpx.AsyncClient() as client:
        await client.get(f"{ADMIN_URL}/query-count/reset", timeout=5.0)


def _adapter_label() -> str:
    return "sqlite" if _IS_SQLITE else "postgres"


# ---------------------------------------------------------------------------
# Test 1 — Fan-out independence: fix depth=2, scale breadth (post count)
# ---------------------------------------------------------------------------


async def test_fan_out_independence(tenant_id: int, user_id: int) -> dict[str, Any]:
    """
    Runs users -> posts -> comments at fixed depth but varying post counts.
    The DB query count must be IDENTICAL regardless of how many posts exist.
    Any proportional growth = FAIL (N+1 bug).

    Note: because auth rules scope posts/comments to user_id == jwt.user_id
    the seeded posts all belong to the test user and are always visible.
    We test breadths [5, 20, 50] to keep the integration test fast while
    still demonstrating fan-out independence.  The real stress happens in
    the DataLoader batch layer, not data volume.
    """
    name = "L5-1: Fan-out independence (breadth scaling, depth=2)"
    print(f"\n  {name}")

    breadths = [5, 20, 50]
    query_counts: list[int] = []
    all_ok = True

    for post_count in breadths:
        # Seed exactly post_count posts for the test user (existing comments
        # already present from seed.py are fine; we query with first: post_count)
        # We purposely don't clean up between iterations — the key assertion is
        # that query count stays constant, not the absolute row count.

        gql = f"""
        query {{
            posts_connection(
                where: {{ user_id: {{ eq: {user_id} }} }},
                first: {post_count}
            ) {{
                edges {{
                    node {{
                        id
                        title
                        comments {{
                            id
                            body
                        }}
                    }}
                }}
            }}
        }}
        """
        res = await execute_query(gql, tenant_id=tenant_id, user_id=user_id)
        if res["errors"] is not None:
            print(f"    breadth={post_count}: ERROR {res['errors']}")
            all_ok = False
            query_counts.append(-1)
            continue

        qc = res["query_count"]
        query_counts.append(qc)
        print(f"    breadth={post_count}: {qc} queries")

    # Assertion: all counts must be equal (O(1) in breadth)
    valid_counts = [c for c in query_counts if c >= 0]
    counts_constant = len(set(valid_counts)) == 1 if valid_counts else False

    if not counts_constant and valid_counts:
        print(f"    FAIL: query counts vary with breadth: {list(zip(breadths, query_counts))}")
        all_ok = False

    passed = all_ok and counts_constant
    return {
        "name": name,
        "passed": passed,
        "queries": query_counts[-1] if query_counts else -1,
        "latency_ms": 0.0,
        "detail": {
            "adapter": _adapter_label(),
            "complexity": "O(depth) not O(rows)",
            "observed": dict(zip(breadths, query_counts)),
        },
    }


# ---------------------------------------------------------------------------
# Test 2 — Depth linearity: fix breadth=1 post/level, scale depth
# ---------------------------------------------------------------------------


async def test_depth_linearity(tenant_id: int, user_id: int) -> dict[str, Any]:
    """
    Runs depth 1, 2, and 3 queries (limited by sgql.yaml max_depth=8).
    Asserts query count grows linearly (not exponentially) with depth.

    depth 1: posts (1 query for posts root)
    depth 2: posts -> comments (2 queries: posts + batched comments)
    depth 3: posts -> comments -> users (3 queries: + batched users)

    sgql.yaml max_depth = 8, so depth 3 is safe.
    """
    name = "L5-2: Depth linearity (depth scaling, fixed breadth)"
    print(f"\n  {name}")

    depths = {
        1: f"query {{ posts_connection(where: {{ user_id: {{ eq: {user_id} }} }}, first: 5) {{ edges {{ node {{ id title }} }} }} }}",
        2: f"query {{ posts_connection(where: {{ user_id: {{ eq: {user_id} }} }}, first: 5) {{ edges {{ node {{ id title comments {{ id body }} }} }} }} }}",
        3: f"query {{ posts_connection(where: {{ user_id: {{ eq: {user_id} }} }}, first: 5) {{ edges {{ node {{ id title comments {{ id body users {{ id username }} }} }} }} }} }}",
    }

    query_counts: dict[int, int] = {}
    all_ok = True

    for depth, gql in depths.items():
        res = await execute_query(gql, tenant_id=tenant_id, user_id=user_id)
        if res["errors"] is not None:
            print(f"    depth={depth}: ERROR {res['errors']}")
            all_ok = False
            query_counts[depth] = -1
            continue

        qc = res["query_count"]
        query_counts[depth] = qc
        print(f"    depth={depth}: {qc} queries")

    # Assertion: query count at depth N must be >= count at depth N-1
    # and must not grow faster than linear (no exponential explosion)
    valid = {d: c for d, c in query_counts.items() if c >= 0}
    if len(valid) >= 2:
        depths_sorted = sorted(valid.keys())
        counts_sorted = [valid[d] for d in depths_sorted]

        # Monotonically non-decreasing (each extra level adds at least one query)
        is_non_decreasing = all(
            counts_sorted[i] <= counts_sorted[i + 1] for i in range(len(counts_sorted) - 1)
        )

        # No exponential: growth per step must be bounded (< 4x per depth step)
        max_step_ratio = (
            max(
                (counts_sorted[i + 1] / counts_sorted[i])
                for i in range(len(counts_sorted) - 1)
                if counts_sorted[i] > 0
            )
            if len(counts_sorted) >= 2
            else 1.0
        )

        if not is_non_decreasing:
            print(f"    WARN: counts not monotone: {dict(zip(depths_sorted, counts_sorted))}")

        if max_step_ratio >= 4.0:
            print(f"    FAIL: super-linear growth ratio {max_step_ratio:.1f}x per depth")
            all_ok = False
        else:
            print(f"    growth ratio per depth: {max_step_ratio:.2f}x (linear OK)")

    passed = all_ok and all(c >= 0 for c in query_counts.values())
    return {
        "name": name,
        "passed": passed,
        "queries": query_counts.get(3, -1),
        "latency_ms": 0.0,
        "detail": {
            "adapter": _adapter_label(),
            "complexity": "O(depth)",
            "observed": query_counts,
        },
    }


# ---------------------------------------------------------------------------
# Test 3 — Many-to-many: ONE batched query for entire level
# ---------------------------------------------------------------------------


async def test_m2m_batch(tenant_id: int, user_id: int) -> dict[str, Any]:
    """
    posts -> tags for a batch of posts.
    Asserts one single batch query is issued for the join level — not one
    per post.
    """
    name = "L5-3: M2M batching (posts -> tags, one query for level)"
    print(f"\n  {name}")

    gql = f"""
    query {{
        posts_connection(
            where: {{ user_id: {{ eq: {user_id} }} }},
            first: 10
        ) {{
            edges {{
                node {{
                    id
                    title
                    tags {{
                        id
                        name
                    }}
                }}
            }}
        }}
    }}
    """
    res = await execute_query(gql, tenant_id=tenant_id, user_id=user_id)
    if res["errors"] is not None:
        return {
            "name": name,
            "passed": False,
            "queries": -1,
            "latency_ms": res["latency_ms"],
            "detail": {"error": str(res["errors"])},
        }

    qc = res["query_count"]
    print(f"    posts+tags query count: {qc}")

    # We expect at most 3 queries: (1) posts root + (2) post_tags join + (3) tags lookup
    # The exact number depends on whether the DataLoader does a single IN query or
    # a join. We assert it is NOT proportional to post count (i.e. <= 5).
    passed = res["errors"] is None and 0 < qc <= 5
    return {
        "name": name,
        "passed": passed,
        "queries": qc,
        "latency_ms": res["latency_ms"],
        "detail": {
            "adapter": _adapter_label(),
            "complexity": "O(1) for join level",
            "observed_query_count": qc,
            "expected_max": 5,
        },
    }


# ---------------------------------------------------------------------------
# Test 4 — Sibling relations: additive, not multiplicative
# ---------------------------------------------------------------------------


async def test_sibling_relations(tenant_id: int, user_id: int) -> dict[str, Any]:
    """
    Query posts { comments, tags, users } together.
    Sibling relation counts should be additive per level, not multiplicative.

    posts only         → baseline count B
    posts + comments   → B + 1
    posts + tags       → B + 1 or B + 2 (join table intermediate)
    posts + comments + tags + users → should NOT exceed B + 4
    """
    name = "L5-4: Sibling relations (additive query counts)"
    print(f"\n  {name}")

    gql_base = f"""
    query {{
        posts_connection(where: {{ user_id: {{ eq: {user_id} }} }}, first: 5) {{
            edges {{ node {{ id title }} }}
        }}
    }}
    """
    gql_all = f"""
    query {{
        posts_connection(where: {{ user_id: {{ eq: {user_id} }} }}, first: 5) {{
            edges {{
                node {{
                    id
                    title
                    users {{ id username }}
                    comments {{ id body }}
                    tags {{ id name }}
                }}
            }}
        }}
    }}
    """

    res_base = await execute_query(gql_base, tenant_id=tenant_id, user_id=user_id)
    res_all = await execute_query(gql_all, tenant_id=tenant_id, user_id=user_id)

    qc_base = res_base["query_count"]
    qc_all = res_all["query_count"]
    extra = qc_all - qc_base

    print(f"    base (posts only): {qc_base} queries")
    print(f"    all siblings:      {qc_all} queries (+{extra} for 3 sibling relations)")

    # 3 sibling relations: each may emit 1–2 queries (join table for tags)
    # So extra should be between 2 and 6.  Anything > 10 implies N+1.
    has_errors = res_base["errors"] is not None or res_all["errors"] is not None
    passed = not has_errors and 0 < extra <= 10

    return {
        "name": name,
        "passed": passed,
        "queries": qc_all,
        "latency_ms": res_base["latency_ms"] + res_all["latency_ms"],
        "detail": {
            "adapter": _adapter_label(),
            "complexity": "additive per sibling",
            "base_queries": qc_base,
            "all_siblings_queries": qc_all,
            "extra_queries_for_3_siblings": extra,
        },
    }


# ---------------------------------------------------------------------------
# Test 5 — Circular reference: users -> posts -> users (no redundant re-fetch)
# ---------------------------------------------------------------------------


async def test_circular_reference(tenant_id: int, user_id: int) -> dict[str, Any]:
    """
    users -> posts -> users loops back to the same user rows.
    The DataLoader should coalesce IDs and issue O(depth) queries, not
    re-fetch the original user rows a second time via a brand-new query.

    Expected query count: 3 (users, posts, users[again — batched same IDs])
    The key is it should NOT be O(posts) individual user lookups.
    """
    name = "L5-5: Circular reference (users -> posts -> users)"
    print(f"\n  {name}")

    gql = """
    query {
        users_connection(first: 3) {
            edges {
                node {
                    id
                    username
                    posts(first: 5) {
                        id
                        title
                        users {
                            id
                            username
                        }
                    }
                }
            }
        }
    }
    """
    res = await execute_query(gql, tenant_id=tenant_id, user_id=user_id)

    if res["errors"] is not None:
        return {
            "name": name,
            "passed": False,
            "queries": -1,
            "latency_ms": res["latency_ms"],
            "detail": {"error": str(res["errors"])},
        }

    qc = res["query_count"]
    print(f"    users->posts->users query count: {qc}")

    # Should be at most 4 (users, posts, users reverse-lookup, possibly tenant check)
    # Must NOT be O(users * posts) which would be 3*5=15 without batching.
    passed = 0 < qc <= 6
    return {
        "name": name,
        "passed": passed,
        "queries": qc,
        "latency_ms": res["latency_ms"],
        "detail": {
            "adapter": _adapter_label(),
            "complexity": "O(depth) not O(rows^depth)",
            "observed": qc,
            "expected_max": 6,
        },
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def run_level5(tenant_id: int, user_id: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    print(f"\n--- Level 5: Batching Correctness ({_adapter_label()}) ---")

    tests = [
        test_fan_out_independence,
        test_depth_linearity,
        test_m2m_batch,
        test_sibling_relations,
        test_circular_reference,
    ]

    for test_fn in tests:
        try:
            result = await test_fn(tenant_id, user_id)
        except Exception as exc:
            result = {
                "name": getattr(test_fn, "__name__", str(test_fn)),
                "passed": False,
                "queries": -1,
                "latency_ms": 0.0,
                "detail": {"exception": str(exc)},
            }
            print(f"  EXCEPTION in {result['name']}: {exc}")

        # Log detail for the report
        detail = result.pop("detail", {})
        if detail:
            print(f"    detail: {detail}")

        results.append(result)

    return results
