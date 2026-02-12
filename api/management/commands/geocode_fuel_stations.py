import json
import random
import time
from pathlib import Path
import concurrent.futures

import requests
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import FuelStation

# Using Photon (OSM-based) for faster geocoding than standard Nominatim
GEOCODE_URL = "https://photon.komoot.io/api/"
HEADERS = {"User-Agent": "FuelRouteAssessment/1.0"}

# Fallback state centroids (lon, lat) for when city lookup fails
STATE_CENTROIDS = {
    "AL": (-86.9023, 32.3182), "AK": (-153.4694, 64.2008),
    "AZ": (-111.0937, 34.0489), "AR": (-92.3731, 34.7999),
    "CA": (-119.4179, 36.7783), "CO": (-105.7821, 39.5501),
    "CT": (-72.7554, 41.6032), "DE": (-75.5277, 38.9108),
    "FL": (-81.5158, 27.6648), "GA": (-83.6431, 32.1574),
    "HI": (-155.5828, 19.8968), "ID": (-114.7420, 44.0682),
    "IL": (-88.9865, 40.6331), "IN": (-86.1349, 40.2672),
    "IA": (-93.0977, 41.8780), "KS": (-98.4842, 38.5266),
    "KY": (-84.2700, 37.8393), "LA": (-91.9623, 30.9843),
    "ME": (-69.4455, 45.2538), "MD": (-76.6413, 39.0458),
    "MA": (-71.3824, 42.4072), "MI": (-85.6024, 44.3148),
    "MN": (-94.6859, 46.7296), "MS": (-89.3985, 32.3547),
    "MO": (-91.8318, 37.9643), "MT": (-110.3626, 46.8797),
    "NE": (-99.9018, 41.4925), "NV": (-116.4194, 38.8026),
    "NH": (-71.5724, 43.1939), "NJ": (-74.4057, 40.0583),
    "NM": (-106.2485, 34.5199), "NY": (-74.2179, 43.2994),
    "NC": (-79.0193, 35.7596), "ND": (-101.0020, 47.5515),
    "OH": (-82.9071, 40.4173), "OK": (-97.0929, 35.5677),
    "OR": (-120.5542, 43.8041), "PA": (-77.1945, 41.2033),
    "RI": (-71.4774, 41.5801), "SC": (-81.1637, 33.8361),
    "SD": (-99.4388, 43.9695), "TN": (-86.5804, 35.7478),
    "TX": (-99.9018, 31.9686), "UT": (-111.0937, 39.3210),
    "VT": (-72.7107, 44.5588), "VA": (-78.6569, 37.4316),
    "WA": (-120.7401, 47.7511), "WV": (-80.4549, 38.5976),
    "WI": (-89.6165, 44.2685), "WY": (-107.2903, 43.0760),
    "DC": (-77.0369, 38.9072),
}


def geocode_city(city: str, state: str) -> tuple[float, float] | None:
    """Return (lon, lat) for a city, or None on failure."""
    query = f"{city}, {state}, United States"
    params = {
        "q": query,
        "limit": 1,
    }
    try:
        resp = requests.get(GEOCODE_URL, params=params, headers=HEADERS, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data["features"]:
            coords = data["features"][0]["geometry"]["coordinates"]
            return float(coords[0]), float(coords[1])
    except Exception:
        pass
    return None


class Command(BaseCommand):
    help = "Geocode fuel stations by city/state (fast batch approach)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workers", type=int, default=12,
            help="Number of concurrent workers (default 8)",
        )
        parser.add_argument(
            "--resume", action="store_true",
            help="Resume from cache file .geocode_cache.json if it exists",
        )
        parser.add_argument(
            "--cache-file", type=str, default=".geocode_cache.json",
            help="Path to the JSON cache file",
        )

    def handle(self, *args, **options):
        workers    = options["workers"]
        resume     = options["resume"]
        cache_path = Path(options["cache_file"])

        # ── Load cache ─────────────────────────────────────────────────────────
        cache: dict[str, list[float]] = {}   # "City|ST" -> [lon, lat]
        if resume and cache_path.exists():
            with open(cache_path) as f:
                cache = json.load(f)
            self.stdout.write(f"Resumed cache: {len(cache)} cities already resolved.")

        # ── Find all unique (city, state) pairs that still need geocoding ──────
        stations_needing_geocoding = FuelStation.objects.filter(location__isnull=True)
        total_stations = stations_needing_geocoding.count()

        if total_stations == 0:
            self.stdout.write(self.style.SUCCESS("All stations already geocoded!"))
            return

        self.stdout.write(f"Stations needing geocoding: {total_stations}")

        city_state_pairs = (
            stations_needing_geocoding
            .values_list("city", "state")
            .distinct()
            .order_by("state", "city")
        )
        
        # Filter out what we already have
        pairs_to_fetch = [
            (c, s) for c, s in city_state_pairs 
            if f"{c}|{s}" not in cache
        ]
        
        self.stdout.write(f"Unique city/state pairs to fetch: {len(pairs_to_fetch)}")

        # ── Geocode each unique city ───────────────────────────────────────────
        resolved = 0
        failed   = 0

        if pairs_to_fetch:
            self.stdout.write(f"Starting parallel geocoding with {workers} workers...")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_pair = {
                    executor.submit(geocode_city, city, state): (city, state)
                    for city, state in pairs_to_fetch
                }
                
                for i, future in enumerate(concurrent.futures.as_completed(future_to_pair)):
                    city, state = future_to_pair[future]
                    cache_key = f"{city}|{state}"
                    
                    try:
                        lon_lat = future.result()
                        if lon_lat:
                            cache[cache_key] = list(lon_lat)
                            resolved += 1
                        else:
                            # Fallback
                            if state in STATE_CENTROIDS:
                                cache[cache_key] = list(STATE_CENTROIDS[state])
                                resolved += 1
                            else:
                                failed += 1
                    except Exception:
                        failed += 1
                    
                    if (i + 1) % 50 == 0:
                        self.stdout.write(f"  Processed {i+1}/{len(pairs_to_fetch)}...")
                        with open(cache_path, "w") as f:
                            json.dump(cache, f)

        # Final cache save
        with open(cache_path, "w") as f:
            json.dump(cache, f)

        self.stdout.write(f"\nGeocoding complete. Resolved: {resolved}  Failed: {failed}")
        self.stdout.write("Applying coordinates to stations...")

        # ── Apply coordinates to all stations ─────────────────────────────────
        JITTER = 0.003   # ~300 meters, enough to separate co-located stations
        updated = 0
        skipped = 0

        # Process in chunks to avoid loading all stations into memory
        chunk_size = 500
        all_ids = list(
            FuelStation.objects.filter(location__isnull=True).values_list("id", "city", "state")
        )

        with transaction.atomic():
            batch = []
            for station_id, city, state in all_ids:
                cache_key = f"{city}|{state}"
                if cache_key not in cache:
                    skipped += 1
                    continue

                lon, lat = cache[cache_key]
                # Apply tiny random jitter so stations in the same city
                # don't all land on the exact same coordinate
                jlon = lon + random.uniform(-JITTER, JITTER)
                jlat = lat + random.uniform(-JITTER, JITTER)

                station = FuelStation(id=station_id)
                station.location = Point(jlon, jlat, srid=4326)
                batch.append(station)

                if len(batch) >= chunk_size:
                    FuelStation.objects.bulk_update(batch, ["location"])
                    updated += len(batch)
                    batch = []
                    self.stdout.write(f"  Applied to {updated} stations...")

            if batch:
                FuelStation.objects.bulk_update(batch, ["location"])
                updated += len(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Done! Updated: {updated}  Skipped (no coords): {skipped}"
            )
        )
        self.stdout.write(
            f"Geocoded stations: {FuelStation.objects.filter(location__isnull=False).count()}"
        )