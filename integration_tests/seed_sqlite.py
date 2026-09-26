import asyncio
import aiosqlite
from faker import Faker
import random

fake = Faker()

DB_DSN = "sgql_test_db.sqlite3"


async def run_seed() -> None:
    conn = await aiosqlite.connect(DB_DSN)

    # Enable foreign keys and setup schema
    await conn.execute("PRAGMA foreign_keys = ON;")

    with open("schema_sqlite.sql", "r") as f:
        schema_sql = f.read()

    await conn.executescript(schema_sql)

    print("Database schema created and reset.")

    # 1. Insert Tenants
    tenant_ids = []
    for _ in range(5):
        cursor = await conn.execute("INSERT INTO tenants (name) VALUES (?)", (fake.company(),))
        assert cursor.lastrowid is not None
        tenant_ids.append(cursor.lastrowid)

    # 2. Insert Users
    users = []
    for _ in range(50):
        t_id = random.choice(tenant_ids)
        users.append((t_id, fake.user_name(), fake.email(), True))

    await conn.executemany(
        "INSERT INTO users (tenant_id, username, email, is_active) VALUES (?, ?, ?, ?)", users
    )

    async with conn.execute("SELECT id FROM users") as cursor:
        user_ids = [row[0] for row in await cursor.fetchall()]

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
        "INSERT INTO posts (user_id, title, body, published_at) VALUES (?, ?, ?, ?)", posts
    )

    async with conn.execute("SELECT id FROM posts") as cursor:
        post_ids = [row[0] for row in await cursor.fetchall()]

    # 4. Insert Comments
    comments = []
    for _ in range(400):
        post_id = random.choice(post_ids)
        user_id = random.choice(user_ids)
        comments.append((post_id, user_id, fake.text()))

    await conn.executemany(
        "INSERT INTO comments (post_id, user_id, body) VALUES (?, ?, ?)", comments
    )

    # 5. Insert Tags
    tags = [(fake.word(),) for _ in range(50)]
    await conn.executemany("INSERT OR IGNORE INTO tags (name) VALUES (?)", tags)

    async with conn.execute("SELECT id FROM tags") as cursor:
        tag_ids = [row[0] for row in await cursor.fetchall()]

    # 6. Insert Post_Tags (M2M)
    post_tags = set()
    for _ in range(150):
        post_id = random.choice(post_ids)
        tag_id = random.choice(tag_ids)
        post_tags.add((post_id, tag_id))

    await conn.executemany(
        "INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)",
        list(post_tags),
    )

    await conn.commit()

    print(
        f"Seed complete. Inserted {len(tenant_ids)} tenants, {len(user_ids)} users, {len(posts)} posts, {len(comments)} comments, and M2M links."
    )
    await conn.close()


if __name__ == "__main__":
    asyncio.run(run_seed())
