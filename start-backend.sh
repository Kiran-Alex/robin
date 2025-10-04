#!/bin/bash

# Start the Discord Bot Generator Backend
echo "🚀 Starting Discord Bot Generator Backend..."

# Navigate to project root
cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Go to backend directory
cd backend

# Start the server
echo "📡 Starting server on http://localhost:8000"
uvicorn main:app --reload --host 0.0.0.0 --port 8000



