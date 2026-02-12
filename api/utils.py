import requests
from django.contrib.gis.geos import LineString, Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from api.models import FuelStation

# -----------------------
# Constants
# -----------------------
TANK_CAPACITY_GALLONS = 50
FUEL_EFFICIENCY_MPG = 10       # miles per gallon
MILES_TO_METERS = 1609.34
MAX_RANGE_MILES = TANK_CAPACITY_GALLONS * FUEL_EFFICIENCY_MPG  # 500 miles
LOW_FUEL_THRESHOLD = 0.25      # refuel when below 25% tank

# OSRM API URL (public demo server)
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving"


# -----------------------
# Routing Utilities
# -----------------------
def get_osrm_route(start_lon, start_lat, end_lon, end_lat):
    """
    Query OSRM to get a driving route from start to end coordinates.

    Returns:
        route_geojson: GeoJSON geometry of the route
        distance_m: total route distance in meters
    """
    coords = f"{start_lon},{start_lat};{end_lon},{end_lat}"
    url = f"{OSRM_BASE_URL}/{coords}?overview=full&geometries=geojson"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    route_geojson = data["routes"][0]["geometry"]
    distance_m = data["routes"][0]["distance"]
    return route_geojson, distance_m


# -----------------------
# Fuel Routing Utilities
# -----------------------
def calculate_fuel_route(start_lon, start_lat, end_lon, end_lat, buffer_miles=50):
    """
    Calculate a fuel-efficient route between two points.

    Returns a dict with:
        - route_geometry  : GeoJSON LineString
        - fuel_stops      : ordered list of stations to stop at
        - total_distance  : miles (float)
        - total_fuel_cost : USD (float)
    """
    # ── 1. Get the driving route ──────────────────────────────────────────────
    route_geojson, route_distance_m = get_osrm_route(
        start_lon, start_lat, end_lon, end_lat
    )

    # Build a Django GEOS LineString (SRID 4326)
    route_line = LineString(route_geojson["coordinates"], srid=4326)
    total_distance_miles = route_distance_m / MILES_TO_METERS

    print(f"\n{'='*60}")
    print(f"📍 ROUTE: {total_distance_miles:.2f} miles")
    print(f"📍 Buffer: {buffer_miles} miles")
    print(f"📍 Total stations in DB: {FuelStation.objects.count()}")
    print(f"📍 Geocoded stations: {FuelStation.objects.filter(location__isnull=False).count()}")
    print(f"{'='*60}\n")

    # ── 2. Find stations near the route ───────────────────────────────────────
    def query_nearby(buf_miles):
        return (
            FuelStation.objects
            .filter(location__isnull=False)
            .annotate(
                distance_to_route=Distance("location", route_line)
            )
            .filter(distance_to_route__lte=D(mi=buf_miles))
            .order_by("distance_to_route")
        )

    # Try with increasing buffers until we find stations
    nearby_stations = query_nearby(buffer_miles)
    count = nearby_stations.count()
    print(f"📍 Nearby stations ({buffer_miles} mi buffer): {count}")

    # Progressive buffer increases
    buffers_tried = [buffer_miles]
    while count == 0 and buffer_miles <= 200:
        buffer_miles *= 2
        buffers_tried.append(buffer_miles)
        nearby_stations = query_nearby(buffer_miles)
        count = nearby_stations.count()
        print(f"📍 Nearby stations ({buffer_miles} mi buffer): {count}")

    if count == 0:
        print(f"❌ No stations found even at {buffer_miles} miles!")
        return {
            "route_geometry": route_geojson,
            "fuel_stops": [],
            "total_distance": round(total_distance_miles, 2),
            "total_fuel_cost": 0.0,
            "message": f"No fuel stations found within {buffer_miles} miles of route",
        }

    # Debug: show sample of found stations
    print(f"\n✅ Found {count} stations within {buffer_miles} miles. Sample:")
    for s in nearby_stations[:5]:
        try:
            dist_mi = s.distance_to_route.mi
        except:
            dist_mi = s.distance_to_route.m / MILES_TO_METERS
        print(f"  🚛 {dist_mi:6.2f} mi - {s.truckstop_name[:30]:30} - ${s.retail_price} - {s.city}, {s.state}")

    # ── 3. Sort stations along the route ─────────────────────────────────────
    stations_with_progress = []
    for station in nearby_stations:
        try:
            # Create a point with the same SRID as the route line
            pt = Point(station.location.x, station.location.y, srid=4326)
            # Get normalized distance along line (0 = start, 1 = end)
            progress = route_line.project_normalized(pt)
            stations_with_progress.append((progress, station))
        except Exception as e:
            print(f"⚠️  Could not project station {station.id}: {e}")
            continue

    stations_with_progress.sort(key=lambda x: x[0])
    print(f"\n📍 Stations ordered along route: {len(stations_with_progress)}")

    if not stations_with_progress:
        return {
            "route_geometry": route_geojson,
            "fuel_stops": [],
            "total_distance": round(total_distance_miles, 2),
            "total_fuel_cost": 0.0,
            "message": "Could not project any stations onto route",
        }

    # ── 4. SIMPLE FUEL OPTIMISATION - GUARANTEED TO BUY FUEL! ────────────────
    route_stops = []
    stop_gallons = []
    total_fuel_cost = 0.0
    current_fuel = TANK_CAPACITY_GALLONS  # Start with full tank (50 gal)
    current_miles = 0.0
    
    print(f"\n⛽ FUEL OPTIMIZATION (Range: {MAX_RANGE_MILES} miles on full tank)")
    
    # Keep track of cheapest station seen so far
    best_price_so_far = 999.99
    last_stop_miles = 0
    
    for i, (progress, station) in enumerate(stations_with_progress):
        station_miles = progress * total_distance_miles
        leg_miles = station_miles - current_miles
        fuel_used = leg_miles / FUEL_EFFICIENCY_MPG
        
        # Travel to this station
        current_fuel -= fuel_used
        current_miles = station_miles
        
        # Get price
        price_here = float(station.retail_price)
        miles_to_end = total_distance_miles - station_miles
        fuel_to_finish = miles_to_end / FUEL_EFFICIENCY_MPG
        
        # Update best price
        if price_here < best_price_so_far:
            best_price_so_far = price_here
        
        # --- DECISION LOGIC ---
        gallons_to_buy = 0
        reason = ""
        
        # Case 1: LOW FUEL - MUST BUY (below 25%)
        if current_fuel < TANK_CAPACITY_GALLONS * 0.25:
            gallons_to_buy = TANK_CAPACITY_GALLONS - current_fuel
            reason = f"LOW FUEL ({current_fuel:.1f} gal left)"
        
        # Case 2: This is a GOOD PRICE (within 10% of best seen)
        elif price_here <= best_price_so_far * 1.10:
            # Don't buy if we have plenty and end is near
            if miles_to_end < 100 and current_fuel >= fuel_to_finish:
                reason = f"enough to finish (need {fuel_to_finish:.1f}, have {current_fuel:.1f})"
                print(f"  ➖ PASS:  {station.truckstop_name[:25]} - {reason}")
                continue
            
            # Buy 30 gallons or enough to go 300 miles
            buy_amount = min(30, TANK_CAPACITY_GALLONS - current_fuel)
            # But don't overbuy beyond what we need to finish
            if fuel_to_finish < buy_amount + current_fuel:
                buy_amount = max(0, fuel_to_finish - current_fuel)
            
            gallons_to_buy = max(0, buy_amount)
            if gallons_to_buy > 0.5:
                reason = f"good price (${price_here:.3f}, best ${best_price_so_far:.3f})"
        
        # Case 3: LAST CHANCE - approaching end and need fuel
        elif miles_to_end < 150 and current_fuel < fuel_to_finish:
            gallons_to_buy = fuel_to_finish - current_fuel
            reason = "last stop before finish"
        
        # Case 4: Been a long time since last stop (200+ miles)
        elif station_miles - last_stop_miles > 200 and current_fuel < TANK_CAPACITY_GALLONS * 0.5:
            gallons_to_buy = TANK_CAPACITY_GALLONS - current_fuel
            reason = "regular stop (200+ miles)"
        
        # Execute purchase
        if gallons_to_buy > 0.5:  # Buy at least 0.5 gallons
            cost = gallons_to_buy * price_here
            total_fuel_cost += cost
            current_fuel += gallons_to_buy
            last_stop_miles = station_miles
            
            route_stops.append(station)
            stop_gallons.append(gallons_to_buy)
            print(f"  ⛽ STOP {len(route_stops)}: +{gallons_to_buy:5.2f} gal @ ${price_here:.3f} = ${cost:6.2f} - {station.truckstop_name[:25]} - {reason}")
        else:
            print(f"  ➖ PASS:  {station.truckstop_name[:25]} (${price_here:.3f}) - {reason or 'skip'}")
    
    # FINAL CHECK - Make sure we can finish!
    miles_to_end = total_distance_miles - current_miles
    fuel_needed = miles_to_end / FUEL_EFFICIENCY_MPG
    
    if fuel_needed > current_fuel + 0.1:
        # Need to buy emergency fuel
        if route_stops:
            # Add to last stop
            last_station = route_stops[-1]
            shortfall = fuel_needed - current_fuel
            cost = shortfall * float(last_station.retail_price)
            total_fuel_cost += cost
            stop_gallons[-1] += shortfall
            print(f"  🏁 EMERGENCY: +{shortfall:.2f} gal @ ${float(last_station.retail_price):.3f} = ${cost:.2f}")
        else:
            # No stops made - buy at first station in list
            if stations_with_progress:
                first_station = stations_with_progress[0][1]
                cost = fuel_needed * float(first_station.retail_price)
                total_fuel_cost += cost
                route_stops.append(first_station)
                stop_gallons.append(fuel_needed)
                print(f"  🚨 FORCED STOP: +{fuel_needed:.2f} gal @ ${float(first_station.retail_price):.3f} = ${cost:.2f}")

    print(f"\n{'='*60}")
    print(f"💰 TOTAL FUEL COST : ${total_fuel_cost:.2f}")
    print(f"⛽ STOPS MADE      : {len(route_stops)}")
    print(f"📍 TOTAL DISTANCE  : {total_distance_miles:.2f} miles")
    print(f"{'='*60}\n")

    # ── 6. Build JSON-safe response ───────────────────────────────────────────
    response_data = {
        "route_geometry": route_geojson,
        "fuel_stops": [
            {
                "id": s.id,
                "truckstop_name": s.truckstop_name,
                "address": s.address,
                "city": s.city,
                "state": s.state,
                "location": [s.location.x, s.location.y],
                "retail_price": float(s.retail_price),
                "gallons_purchased": round(float(stop_gallons[idx]), 2),
            }
            for idx, s in enumerate(route_stops)
        ],
        "total_distance": round(float(total_distance_miles), 2),
        "total_fuel_cost": round(float(total_fuel_cost), 2),
    }

    return response_data