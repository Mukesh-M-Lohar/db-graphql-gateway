import asyncio
import asyncpg
from faker import Faker
import random

fake = Faker()

DB_DSN = "postgresql://sgql_test:sgql_password@localhost:5433/sgql_test_db"


async def run_seed() -> None:
    conn = await asyncpg.connect(DB_DSN)

    # Enable pg_stat_statements extension and setup schema
    with open("schema.sql", "r") as f:
        schema_sql = f.read()

    await conn.execute(schema_sql)

    print("Database schema created and reset.")

    # 1. Insert Tenants
    tenants = [(fake.company(),) for _ in range(5)]
    tenant_ids = [
        await conn.fetchval("INSERT INTO tenants (name) VALUES ($1) RETURNING id", t[0])
        for t in tenants
    ]

    # 2. Insert Users
    users = []
    for _ in range(50):
        t_id = random.choice(tenant_ids)
        users.append((t_id, fake.user_name(), fake.email(), True))

    await conn.executemany(
        "INSERT INTO users (tenant_id, username, email, is_active) VALUES ($1, $2, $3, $4)", users
    )

    user_ids = [row["id"] for row in await conn.fetch("SELECT id FROM users")]

    # Select 2 power users
    power_users = random.sample(user_ids, 2)
    normal_users = [uid for uid in user_ids if uid not in power_users]

    # 3. Insert Posts
    posts = []
    # Power users get 200 posts each
    for pu in power_users:
        for _ in range(200):
            posts.append((pu, fake.sentence(), fake.text(), fake.date_time_this_year()))

    # Normal users get 1-3 posts each
    for nu in normal_users:
        for _ in range(random.randint(1, 3)):
            posts.append((nu, fake.sentence(), fake.text(), fake.date_time_this_year()))

    await conn.executemany(
        "INSERT INTO posts (user_id, title, body, published_at) VALUES ($1, $2, $3, $4)", posts
    )

    post_ids = [row["id"] for row in await conn.fetch("SELECT id FROM posts")]

    # 4. Insert Comments
    comments = []
    for _ in range(400):
        post_id = random.choice(post_ids)
        user_id = random.choice(user_ids)
        comments.append((post_id, user_id, fake.text()))

    await conn.executemany(
        "INSERT INTO comments (post_id, user_id, body) VALUES ($1, $2, $3)", comments
    )

    # 5. Insert Tags
    tags = [(fake.word(),) for _ in range(50)]
    try:
        await conn.executemany("INSERT INTO tags (name) VALUES ($1) ON CONFLICT DO NOTHING", tags)
    except asyncpg.exceptions.UniqueViolationError:
        pass

    tag_ids = [row["id"] for row in await conn.fetch("SELECT id FROM tags")]

    # 6. Insert Post_Tags (M2M)
    post_tags = set()
    for _ in range(150):
        post_id = random.choice(post_ids)
        tag_id = random.choice(tag_ids)
        post_tags.add((post_id, tag_id))

    await conn.executemany(
        "INSERT INTO post_tags (post_id, tag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        list(post_tags),
    )

    print(
        f"Seed complete. Inserted {len(tenant_ids)} tenants, {len(user_ids)} users, {len(posts)} posts, {len(comments)} comments, and M2M links."
    )
    await conn.close()


if __name__ == "__main__":
    asyncio.run(run_seed())
