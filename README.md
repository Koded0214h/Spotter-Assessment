# Spotter-Assessment

# Route Fuel Optimization API

A production-minded backend API that computes **cost-optimal fuel stops along a road trip** within the United States, given fuel price data, vehicle constraints, and a single routing API call.

This project was built as part of a backend systems & AI engineering assessment, with a strong focus on **correctness, performance, spatial querying, and explainable algorithmic trade-offs**.

---

## 🚗 Problem Overview

Given:

* A **start** and **end** location (within the USA)
* A vehicle with:

  * Maximum range: **500 miles**
  * Fuel efficiency: **10 miles per gallon**
* A dataset of fuel prices across the US

The API must:

* Compute the driving route between the two locations
* Identify **optimal fuel stops along the route** (cost-effective)
* Handle **multiple refueling stops** if needed
* Return:

  * The route geometry (for map rendering)
  * Ordered fuel stops
  * Total distance
  * Total fuel cost

Key constraints:

* The routing API should be called **at most once per unique route**
* The API should respond **quickly**, even with large fuel datasets

---

## 🧠 Core Design Decisions

### 1. Routing is Delegated, Optimization is Not

* Shortest-path routing (Dijkstra / A*) is handled by an **external routing API**.
* This system focuses on a **refueling optimization problem along a fixed path**, not global routing.

This separation simplifies the system and avoids duplicating expensive graph computations.

---

### 2. Spatial Queries with PostGIS

Fuel stations are filtered using **database-level spatial queries**:

* The route geometry is converted to a `LineString`
* Fuel stations are selected using `ST_DWithin` within a small buffer of the route
* A GIST spatial index ensures millisecond-level performance

This reduces tens of thousands of stations to only those relevant to the route.

---

### 3. Linear Optimization via Route Ordering

Each fuel station near the route is ordered using:

* `ST_LineLocatePoint(route, station)` → value between `0.0 – 1.0`

This converts the spatial problem into a **1-dimensional ordered list**, enabling an efficient greedy optimization strategy.

---

### 4. Fuel Optimization Algorithm

The system uses a **greedy refueling strategy** that is optimal for this problem:

At each stop:

* Look ahead to all reachable stations within 500 miles
* If a cheaper station exists ahead:

  * Buy only enough fuel to reach the nearest cheaper station
* Otherwise:

  * Buy enough fuel to maximize range (or reach destination)

This minimizes total fuel cost while respecting vehicle constraints.

> A full graph + Dijkstra solution was intentionally avoided to reduce complexity and improve explainability.

---

### 5. Caching with Redis

Redis is used for:

* **Route caching** (start → end → geometry + distance)
* **Response caching** for repeated requests

This ensures:

* Minimal external API usage
* Fast repeat responses
* Stability under load

---

## 🏗️ System Architecture

High-level flow:

1. Client sends request (start, end)
2. API checks Redis for cached route
3. On cache miss:

   * Routing API is called once
   * Geometry is cached
4. PostGIS filters fuel stations near the route
5. Stations are ordered along the route
6. Fuel optimization algorithm runs
7. Response is returned as JSON + GeoJSON

---

## 🧰 Tech Stack

* **Backend**: Django (latest stable)
* **API**: Django REST Framework
* **Database**: PostgreSQL + PostGIS
* **Caching**: Redis (local & cloud)
* **Docs**: drf-spectacular (OpenAPI)
* **Routing API**: OpenRouteService / OSRM (free tier)

---

## 📦 Data Ingestion

Fuel price data is loaded via a **Django management command**:

* Coordinates are validated and normalized
* Stations are stored as `PointField`
* Bulk inserts are used for performance
* Spatial indexes are created

This is a one-time operation and never performed at request time.

---

## 📄 API Documentation

* OpenAPI schema is generated via **drf-spectacular**
* Clearly defined request/response contracts
* Supports easy testing via Swagger / Postman

---

## ⚖️ Trade-offs & Rationale

| Decision                 | Reason                                   |
| ------------------------ | ---------------------------------------- |
| No custom Dijkstra       | Routing already solved by external API   |
| Greedy refueling         | Optimal for linear path, simpler than DP |
| PostGIS over Python math | Orders of magnitude faster               |
| Redis caching            | Lower latency & API cost                 |

---

> will talk more in teh next commit