#!/bin/bash
echo "Testing /plan endpoint..."
echo "Start time: $(date +%s)"

START=$(date +%s)
curl -X POST http://localhost:8001/plan \
  -H "Content-Type: application/json" \
  -d '{"description": "Create a simple moderation bot"}' \
  -w "\nHTTP Status: %{http_code}\nTime: %{time_total}s\n" \
  -o /tmp/plan_response.json \
  --max-time 45

END=$(date +%s)
DURATION=$((END - START))

echo "Total time: ${DURATION}s"
echo "Response:"
cat /tmp/plan_response.json
echo ""
