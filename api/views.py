import json
import decimal
import hashlib
import redis
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework import status
from django.conf import settings
from django.http import JsonResponse
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import LineString
from drf_spectacular.utils import extend_schema
from api.models import FuelStation
from api.utils import calculate_fuel_route, get_osrm_route
from api.serializers import RouteRequestSerializer, RouteResponseSerializer

# Create your views here

# ── Redis client ──────────────────────────────────────────────────────────────
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    password=getattr(settings, "REDIS_PASSWORD", None),
    db=0,
    decode_responses=True,
)

CACHE_TTL_SECONDS = 86_400  # 24 hours


# ── JSON encoder that handles Decimal values (safety net) ─────────────────────
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super().default(obj)


# ── Fuel Route Endpoint ───────────────────────────────────────────────────────
class FuelRouteAPIView(APIView):
    """
    POST /api/v1/route/

    Body (JSON):
        start_lat, start_lon, end_lat, end_lon  – all floats / float-strings

    Response (JSON):
        route_geometry  – GeoJSON LineString of the driving route
        fuel_stops      – ordered list of recommended fuel stops
        total_distance  – total route distance in miles
        total_fuel_cost – estimated fuel cost in USD
    """

    @extend_schema(
        request=RouteRequestSerializer,
        responses={200: RouteResponseSerializer},
    )
    def post(self, request):
        data = request.data

        # ── Validate input ────────────────────────────────────────────────────
        try:
            start_lat = float(data["start_lat"])
            start_lon = float(data["start_lon"])
            end_lat   = float(data["end_lat"])
            end_lon   = float(data["end_lon"])
        except (KeyError, ValueError, TypeError):
            return Response(
                {
                    "error": (
                        "start_lat, start_lon, end_lat, end_lon are required "
                        "and must be valid numbers."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Basic sanity-check: USA bounding box (loose)
        for name, val, lo, hi in [
            ("start_lat",  start_lat,  24.0,  50.0),
            ("end_lat",    end_lat,    24.0,  50.0),
            ("start_lon",  start_lon, -125.0, -66.0),
            ("end_lon",    end_lon,   -125.0, -66.0),
        ]:
            if not (lo <= val <= hi):
                return Response(
                    {"error": f"{name}={val} is outside the continental USA."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ── Cache lookup ──────────────────────────────────────────────────────
        raw_key   = f"{start_lat},{start_lon}:{end_lat},{end_lon}"
        cache_key = "route:" + hashlib.md5(raw_key.encode()).hexdigest()

        cached = redis_client.get(cache_key)
        if cached:
            return Response(json.loads(cached), status=status.HTTP_200_OK)

        # ── Compute route ─────────────────────────────────────────────────────
        try:
            response_data = calculate_fuel_route(
                start_lon=start_lon,
                start_lat=start_lat,
                end_lon=end_lon,
                end_lat=end_lat,
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ── Cache & return ────────────────────────────────────────────────────
        serialized = json.dumps(response_data, cls=DecimalEncoder)
        redis_client.set(cache_key, serialized, ex=CACHE_TTL_SECONDS)

        return Response(response_data, status=status.HTTP_200_OK)


# ── Debug Endpoint ────────────────────────────────────────────────────────────
@extend_schema(exclude=True)
@api_view(['GET'])
def debug_route(request):
    """Debug endpoint to see what stations are near I-15"""
    # LA to Vegas
    start_lon, start_lat = -118.243683, 34.052235
    end_lon, end_lat = -115.139832, 36.169941
    
    try:
        # Get route
        route_geojson, route_distance_m = get_osrm_route(start_lon, start_lat, end_lon, end_lat)
        route_line = LineString(route_geojson["coordinates"], srid=4326)
        
        # Find ALL geocoded stations
        all_stations = FuelStation.objects.filter(location__isnull=False)
        total_geocoded = all_stations.count()
        
        # Annotate with distance
        stations_with_dist = all_stations.annotate(
            d=Distance("location", route_line)
        ).order_by('d')[:50]
        
        results = []
        for s in stations_with_dist:
            dist_mi = s.d.m / 1609.34
            results.append({
                'name': s.truckstop_name,
                'city': s.city,
                'state': s.state,
                'price': float(s.retail_price),
                'distance_miles': round(dist_mi, 2),
                'coords': [s.location.x, s.location.y]
            })
        
        return JsonResponse({
            'success': True,
            'route_distance_miles': round(route_distance_m / 1609.34, 2),
            'total_geocoded': total_geocoded,
            'stations_found': len(results),
            'stations': results
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
