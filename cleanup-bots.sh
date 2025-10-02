#!/bin/bash

echo "Stopping all Discord bot containers..."

# Find all containers with name starting with "bot-"
containers=$(docker ps -a --filter "name=bot-" --format "{{.Names}}")

if [ -z "$containers" ]; then
    echo "No bot containers found."
    exit 0
fi

echo "Found containers:"
echo "$containers"
echo ""

# Stop and remove each container
for container in $containers; do
    echo "Stopping $container..."
    docker stop "$container" 2>/dev/null
    echo "Removing $container..."
    docker rm "$container" 2>/dev/null
    echo "✅ Cleaned up $container"
done

echo ""
echo "All bot containers stopped and removed!"
