#!/bin/bash

# Kill any existing uvicorn processes
echo "Stopping old backend processes..."
pkill -f "uvicorn.*app" || true

# Wait a moment
sleep 1

# Start the backend with correct path
echo "Starting backend..."
cd /Users/kiranalex/demo
source venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
