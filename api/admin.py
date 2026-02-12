from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from .models import FuelStation

# Register your models here.

@admin.register(FuelStation)
class FuelStationAdmin(GISModelAdmin):
    list_display = (
        "truckstop_name",
        "city",
        "state",
        "retail_price",
    )
    search_fields = ("truckstop_name", "city", "state")