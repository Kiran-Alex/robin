#!/bin/bash
echo "Testing /generate endpoint..."

curl -X POST http://localhost:8001/generate \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Simple hello world bot",
    "discordToken": "test_token_abc",
    "applicationId": "test_app_abc",
    "commands": [
      {"name": "hello", "description": "Say hello"}
    ],
    "prefix": "!",
    "user_id": "test_user_123"
  }' \
  --max-time 90

echo ""
echo "Request completed"
