#!/usr/bin/env bash
set -e

echo "=== AI Data Store Teardown ==="
echo ""

# Warn if data will be lost
if docker volume ls -q | grep -q "ai-data-store_mongo_data"; then
    echo "WARNING: This will permanently delete all stored data."
    read -r -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Aborted."
        exit 0
    fi
fi

docker compose down -v

echo ""
echo "=== Teardown Complete ==="
