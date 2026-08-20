from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
import pytest_asyncio
from testcontainers.community.postgres import PostgresContainer


@pytest_asyncio.fixture(scope="session")
async def postgres_container() -> AsyncGenerator[Any, None]:
    # testcontainers handles docker pulling and binding
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres


@pytest_asyncio.fixture
async def db_pool(postgres_container: PostgresContainer) -> AsyncGenerator[asyncpg.Pool, None]:
    url = postgres_container.get_connection_url().replace("postgresql+psycopg2", "postgresql")

    # Create the test schema
    pool = await asyncpg.create_pool(url)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE posts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                title VARCHAR(255) NOT NULL,
                body TEXT,
                is_published BOOLEAN DEFAULT FALSE
            );
            
            CREATE VIEW published_posts AS
                SELECT * FROM posts WHERE is_published = TRUE;
        """)

    yield pool

    # Cleanup schema after test if needed
    async with pool.acquire() as conn:
        await conn.execute("DROP VIEW published_posts;")
        await conn.execute("DROP TABLE posts;")
        await conn.execute("DROP TABLE users;")
    await pool.close()
