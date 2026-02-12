from django.urls import path
from .views import FuelRouteAPIView, debug_route

app_name = "api"

urlpatterns = [
    # Fuel route endpoint
    path("v1/route/", FuelRouteAPIView.as_view(), name="fuel-route"),

    path('debug/route/', debug_route, name='debug-route'),  # Add this line
]
