import uvicorn
import sqlite3
from db_graphql_gateway.database.adapters.sqlite.adapter import SQLiteAdapter
from core import create_gateway_app

def setup_db():
    conn = sqlite3.connect("example.db")
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT OR IGNORE INTO users (id, name) VALUES (1, 'Alice')")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    setup_db()
    adapter = SQLiteAdapter("example.db")
    
    print("Initializing SQLite GraphQL Gateway...")
    print("GraphQL endpoint will be available at http://127.0.0.1:8000/graphql")
    
    app = create_gateway_app(adapter)
    uvicorn.run(app, host="127.0.0.1", port=8000)
