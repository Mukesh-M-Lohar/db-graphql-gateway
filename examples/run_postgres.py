import os
import uvicorn
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from core import create_gateway_app

if __name__ == "__main__":
    # Ensure you have a running Postgres instance matching this DSN
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    adapter = PostgresAdapter(dsn=dsn)
    
    print(f"Initializing Postgres GraphQL Gateway with DSN: {dsn}")
    print("GraphQL endpoint will be available at http://127.0.0.1:8001/graphql")
    
    app = create_gateway_app(adapter)
    uvicorn.run(app, host="127.0.0.1", port=8001)
