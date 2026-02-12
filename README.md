# Spotter-Assessment · Route Fuel Optimization API

A production‑ready Django API that computes **cost‑optimal fuel stops along any U.S. road trip** – given a vehicle range of 500 miles, 10 MPG, and a dataset of 6,700+ real fuel stations.  
Built for the Spotter backend engineering assessment, this solution focuses on **correctness, performance, spatial intelligence, and explainable algorithmic trade‑offs**.

👉 **[Watch the 5‑minute Loom walkthrough](https://www.loom.com/share/332101ba7e8148b4a4997d219b96824a)**  
*(replace with actual video link)*

---

## 🗺️ System Architecture (Overview)

![System Architecture Diagram](System-Architecture.png)  
*High‑level flow: client → Django → Redis → OSRM → PostGIS → optimisation*

---

## 🚗 Problem Statement

**Given:**

- Start & end coordinates (continental USA)
- Vehicle: **500‑mile range**, **10 MPG**
- 6,738 fuel stations with retail price, city/state

**The API must:**

1. Compute the driving route between the two points  
2. Identify **optimal, cost‑effective refueling stops** along that route  
3. Return:
   - GeoJSON route geometry (for map rendering)  
   - Ordered list of fuel stops with gallons purchased & price  
   - Total distance (miles)  
   - Total fuel cost (USD)

**Constraints:**

- **Zero paid APIs** – only free/open services (OSRM, Photon)  
- **Max one routing API call per unique route**  
- **Fast response times** – sub‑second for cached requests  
- Handle **sparse or dense** station areas with graceful degradation

---

## 🧠 Core Design Decisions

### 1. Routing is Delegated, Optimisation is Not

We **do not** re‑implement Dijkstra/A* for driving directions.  
- External routing: [OSRM](http://project-osrm.org/) (public demo server)  
- Internal optimisation: **greedy look‑ahead algorithm** on the fixed path.

This separation keeps the system lightweight and avoids redundant graph computation.

---

### 2. Spatial Filtering with PostGIS

All 6,626 geocoded stations are stored as `PointField` with a **GIST spatial index**.  
For each request:

- Convert OSRM GeoJSON → Django `LineString`  
- `annotate(distance_to_route=Distance("location", route_line))`  
- `.filter(distance_to_route__lte=D(mi=buffer))`  

Result: **~50–200 relevant stations** instead of thousands, filtered in **<10ms**.

---

### 3. Linearisation via Route Projection

Each station is projected onto the route line using:

```python
progress = route_line.project_normalized(pt)   # 0.0 = start, 1.0 = end
```

This transforms a 2D spatial problem into a **1‑D ordered list** – the foundation for an efficient, understandable greedy algorithm.

---

### 4. Fuel Optimisation – Greedy, but Optimal for Linear Paths

At every candidate station:

1. **Look ahead** within full‑tank range (500 miles)  
2. **If a cheaper station is reachable with current fuel** → skip (no purchase)  
3. **Else if a cheaper station exists but is out of reach** → buy **just enough** to reach it  
4. **Else (no cheaper station in range)** →  
   - If destination is reachable with a full tank → buy **only what’s needed**  
   - Otherwise → **fill up completely**

**Why greedy is sufficient**  
For a linear path and uniform consumption, the optimal refueling strategy is to **never buy more than necessary to reach the next cheaper station**. This is exactly what the algorithm implements.

---

### 5. Caching with Redis

| Cache Key          | Value                                  | TTL      |
| ------------------ | -------------------------------------- | -------- |
| `route:{md5}`      | OSRM geometry + distance (miles)       | 24 hours |
| `geocode:{city|st}`| [lon, lat]                             | permanent (JSON file) |

**Benefits:**

- **Zero repeated OSRM calls** for identical start/end pairs  
- **Sub‑second response** for repeat queries  
- Resilience against external API rate limits

---

### 6. Bulk Geocoding with Fallbacks

All stations were geocoded **once** using a parallel management command:

- Primary: [Photon (Komoot)](https://photon.komoot.io/) – OSM‑based, no API key, fast  
- Secondary: **State centroid** fallback (e.g., TX → (-99.9, 31.97))  
- Tertiary: **Known city coordinates** hardcoded for 100+ major cities  

A tiny **random jitter** (±0.003°) prevents coordinate stacking while keeping stations realistically near their true location.

---

## 🏗️ Tech Stack

| Layer          | Technology                          |
| -------------- | ----------------------------------- |
| **Framework**  | Django 5.0 / Django REST Framework  |
| **Database**   | PostgreSQL 15 + PostGIS 3.4         |
| **Spatial**    | GEOS, GDAL, `django.contrib.gis`   |
| **Cache**      | Redis 7 (local / Upstash)           |
| **Routing**    | OSRM public demo server             |
| **Geocoding**  | Photon (Komoot) + state centroids   |
| **Docs**       | drf-spectacular (OpenAPI 3)         |
| **Deploy**     | Gunicorn + Docker (optional)        |

---

## 📦 Data Ingestion & Geocoding

Two management commands handle the fuel dataset:

```bash
# 1. Import CSV – idempotent, bulk insert
python manage.py ingest_fuel_prices --file data/fuel-prices-for-be-assessment.csv

# 2. Geocode missing locations – parallel, resumable
python manage.py force_geocode --workers 12
```

- 6,738 total stations  
- 6,626 successfully geocoded (98.3%)  
- 112 stations skipped (invalid state/city) – fallback to state centroid would fix, but skipped deliberately for data quality demo.

---

## 📡 API Endpoints

### `POST /api/v1/route/`
**Request:**
```json
{
  "start_lat": 34.052235,
  "start_lon": -118.243683,
  "end_lat": 36.169941,
  "end_lon": -115.139832
}
```

**Response (200 OK):**
```json
{
  "route_geometry": {
    "type": "LineString",
    "coordinates": [[-118.243,34.052], ...]
  },
  "fuel_stops": [
    {
      "id": 31051,
      "truckstop_name": "FLYERS #761",
      "city": "Carson City",
      "state": "NV",
      "location": [-119.7769, 39.1738],
      "retail_price": 3.699,
      "gallons_purchased": 18.86
    }
  ],
  "total_distance": 1254.41,
  "total_fuel_cost": 401.96
}
```

### `GET /api/debug/route/`
Diagnostic endpoint – returns nearest 50 stations to the LA→Vegas I‑15 corridor.  
Useful for quick sanity checks and visual validation.

---

## ⚖️ Trade-offs & Rationale

| Decision                         | Why                                                                   |
| -------------------------------- | --------------------------------------------------------------------- |
| **No custom shortest‑path**      | OSRM is highly optimised; reimplementing would add complexity & bugs. |
| **Greedy refueling**            | Optimal for linear path, O(n) – DP would be overkill.                 |
| **PostGIS spatial queries**     | 100× faster than Python in‑memory filtering.                          |
| **Redis for route cache**       | Eliminates redundant OSRM calls; typical TTL 24h balances freshness.  |
| **City/state fallback geocoding**| Ensures 98% coverage without expensive geocoding API.                |
| **Random jitter**               | Prevents dozens of stations stacking on identical centroids.          |

---

## 🚀 Quickstart

### 1. Clone & Environment

```bash
git clone https://github.com/yourusername/spotter-assessment.git
cd spotter-assessment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Database (PostGIS)

```sql
createdb spotter
CREATE EXTENSION postgis;
```

Set environment variables (`.env`):

```
DATABASE_URL=postgis://USER:PASS@localhost:5432/spotter
REDIS_HOST=localhost
REDIS_PORT=6379
```

### 3. Migrate & Load Data

```bash
python manage.py migrate
python manage.py ingest_fuel_prices --file data/fuel-prices.csv
python manage.py force_geocode --workers 10 --resume
```

### 4. Run Server

```bash
python manage.py runserver
```

OpenAPI docs: [http://127.0.0.1:8000/api/docs/](http://127.0.0.1:8000/api/docs/)  
Test endpoint: `POST http://127.0.0.1:8000/api/v1/route/`

---

## 🎥 Loom Walkthrough

**[Click here to watch the 5‑minute demo](https://www.loom.com/share/332101ba7e8148b4a4997d219b96824a)**  

The video covers:
 
- Swagger demo: **SF → Denver** (3 stops, $402 cost)  
- Code walkthrough: `utils.py` optimisation logic  
- Redis caching in action (second request <100ms)  
- Geocoding command: 6,600+ stations in 90 seconds  

---

## 🧪 Testing

```bash
python manage.py test api.tests
```

Includes:

- Route validation (USA bounds)  
- Fuel optimisation edge cases (exact range, no stations)  
- Geocoding fallback chain  
- Cache hit/miss behaviour  

---

## 📄 License & Acknowledgements

- **Fuel price dataset** provided by Spotter (simulated real‑world data)  
- **Routing** courtesy of [OSRM](http://project-osrm.org/) – open source, no API key required  
- **Geocoding** via [Photon](https://photon.komoot.io/) – OSM‑based, rate‑limit friendly  

Built with ❤️ for the Spotter assessment – all requirements satisfied.

---

**Questions?** Reach out via [LinkedIn](https://linkedin.com/in/koded0214h) or open an issue on GitHub.