from rest_framework import serializers
from rest_framework_gis.serializers import GeoFeatureModelSerializer
from .models import FuelStation


# Route Requests Serializer for INPUT
class RouteRequestSerializer(serializers.Serializer):
    start_lat = serializers.FloatField()
    start_lon = serializers.FloatField()
    end_lat = serializers.FloatField()
    end_lon = serializers.FloatField()

# Fuel Stop description along the route

class FuelStopSerializer(GeoFeatureModelSerializer):
    class Meta:
        model = FuelStation
        geo_field = "location"
        fields = (
            "truckstop_name",
            "address",
            "city",
            "state",
            "retail_price",
            "rack_id",
        )

# # Route Requests Serializer for OUTPUT
class RouteResponseSerializer(serializers.Serializer):
    route_geometry = serializers.JSONField()  
    fuel_stops = FuelStopSerializer(many=True)
    total_distance = serializers.FloatField()  
    total_fuel_cost = serializers.FloatField()  
