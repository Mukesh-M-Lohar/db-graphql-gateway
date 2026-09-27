import uvicorn
import subprocess
import os
from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
from core import create_gateway_app


def setup_db() -> str:
    print("Running database seed script to inject data...")
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_dir = os.path.join(root_dir, "integration_tests")
    db_path = os.path.join(test_dir, "sgql_test_db.sqlite3")
    if os.path.exists(db_path):
        os.remove(db_path)
    subprocess.run(["python", "seed_sqlite.py"], cwd=test_dir, check=True)
    return db_path


if __name__ == "__main__":
    db_path = setup_db()
    adapter = SQLiteAdapter(db_path)

    print("Initializing SQLite GraphQL Gateway...")
    print("GraphQL endpoint will be available at http://127.0.0.1:8000/graphql")

    app = create_gateway_app(adapter)
    uvicorn.run(app, host="127.0.0.1", port=8000)
