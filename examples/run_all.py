import os
import uvicorn
from fastapi import FastAPI
from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from core import create_gateway_app
from run_sqlite import setup_db

if __name__ == "__main__":
    setup_db()
    
    sqlite_adapter = SQLiteAdapter("example.db")
    sqlite_app = create_gateway_app(sqlite_adapter)
    
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    postgres_adapter = PostgresAdapter(dsn=dsn)
    postgres_app = create_gateway_app(postgres_adapter)
    
    main_app = FastAPI(title="Multi-DB Gateway")
    
    # Mount the independent gateway apps on different paths
    main_app.mount("/sqlite", sqlite_app)
    main_app.mount("/postgres", postgres_app)
    
    print("Starting Multi-DB Gateway...")
    print("SQLite GraphQL endpoint: http://127.0.0.1:8000/sqlite/graphql")
    print("Postgres GraphQL endpoint: http://127.0.0.1:8000/postgres/graphql")
    
    uvicorn.run(main_app, host="127.0.0.1", port=8000)
