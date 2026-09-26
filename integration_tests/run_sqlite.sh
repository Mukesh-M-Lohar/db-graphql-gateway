#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "1. Cleaning up old SQLite database..."
rm -f sgql_test_db.sqlite3

echo "2. Running seed script..."
export SGQL_DATABASE_URL="sqlite:///sgql_test_db.sqlite3"
uv run python seed_sqlite.py

echo "3. Starting gateway in background..."
export SGQL_CONFIG=sgql.yaml
uv run python server.py &
GATEWAY_PID=$!

echo "Waiting for gateway to boot..."
sleep 5

echo "4. Running integration tests..."
uv run python run_integration.py || (echo "Tests failed"; kill $GATEWAY_PID; rm -f sgql_test_db.sqlite3; exit 1)

echo "5. Teardown..."
kill $GATEWAY_PID
rm -f sgql_test_db.sqlite3
