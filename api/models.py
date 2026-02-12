from django.contrib.gis.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal

# Create your models here.

class FuelStation(models.Model):
    opis_id = models.IntegerField(unique=True)   # ← was part of composite; now sole unique key
    rack_id = models.IntegerField()

    truckstop_name = models.CharField(max_length=255)
    address        = models.CharField(max_length=255)
    city           = models.CharField(max_length=100)
    state          = models.CharField(max_length=10)

    retail_price = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        validators=[MinValueValidator(Decimal("0.0"))],
    )

    location = models.PointField(geography=True, srid=4326, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["state"]),
            models.Index(fields=["retail_price"]),   # helps cheapest-station lookups
        ]

    def __str__(self):
        return f"{self.truckstop_name} - {self.city}, {self.state}"

