curl -X POST http://127.0.0.1:8000/api/v1/route/ \
  -H "Content-Type: application/json" \
  -d '{
    "start_lat": "34.052235",
    "start_lon": "-118.243683",
    "end_lat": "36.169941",
    "end_lon": "-115.139832"
  }'