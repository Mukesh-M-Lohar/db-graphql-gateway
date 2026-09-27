import os
import time
import subprocess
import uvicorn
from db_graphql_gateway.database.adapters.postgres.adapter import PostgresAdapter
from core import create_gateway_app

def setup_postgres():
    print("Resetting Postgres database via Docker Compose...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_dir = os.path.join(root_dir, "integration_tests")
    
    # Destroy and recreate postgres container
    subprocess.run(["docker-compose", "down", "-v"], cwd=test_dir, check=True)
    subprocess.run(["docker-compose", "up", "-d", "postgres"], cwd=test_dir, check=True)
    
    print("Waiting for Postgres to be healthy...")
    time.sleep(5)
    
    print("Running Postgres seed script to inject data...")
    subprocess.run(["python", "seed.py"], cwd=test_dir, check=True)

if __name__ == "__main__":
    setup_postgres()
    
    dsn = os.getenv("DATABASE_URL", "postgresql://sgql_test:sgql_password@localhost:5433/sgql_test_db")
    adapter = PostgresAdapter(dsn=dsn)
    
    print(f"Initializing Postgres GraphQL Gateway with DSN: {dsn}")
    print("GraphQL endpoint will be available at http://127.0.0.1:8001/graphql")
    
    app = create_gateway_app(adapter)
    uvicorn.run(app, host="127.0.0.1", port=8001)
