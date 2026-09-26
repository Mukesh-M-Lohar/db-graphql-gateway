#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "1. Starting Docker Setup..."
docker compose up -d

echo "2. Waiting for Postgres to be healthy..."
sleep 5
until [ "`docker inspect -f {{.State.Health.Status}} integration_tests-postgres-1`" == "healthy" ]; do
    echo "Waiting..."
    sleep 2;
done

echo "3. Running seed script..."
uv run python seed.py

echo "4. Starting gateway in background..."
export SGQL_CONFIG=sgql.yaml
export SGQL_DATABASE_URL=postgresql://sgql_test:sgql_password@localhost:5433/sgql_test_db
uv run python server.py &
GATEWAY_PID=$!

echo "Waiting for gateway to boot..."
sleep 5

echo "5. Running integration tests..."
uv run python run_integration.py || (echo "Tests failed"; kill $GATEWAY_PID; docker compose down; exit 1)

echo "6. Teardown..."
kill $GATEWAY_PID
docker compose down
