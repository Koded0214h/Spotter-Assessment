import requests
import json

# LA to Vegas
payload = {
    "start_lat": 34.052235,
    "start_lon": -118.243683,
    "end_lat": 36.169941,
    "end_lon": -115.139832
}

response = requests.post(
    "http://127.0.0.1:8000/api/v1/route/",
    json=payload,
    headers={"Content-Type": "application/json"}
)

print(f"Status: {response.status_code}")
data = response.json()
print(f"Distance: {data['total_distance']} miles")
print(f"Fuel Cost: ${data['total_fuel_cost']}")
print(f"Stops: {len(data['fuel_stops'])}")

for i, stop in enumerate(data['fuel_stops'], 1):
    print(f"  {i}. {stop['truckstop_name']} - ${stop['retail_price']} @ {stop['city']}, {stop['state']}")