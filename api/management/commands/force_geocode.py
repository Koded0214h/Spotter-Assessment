import csv
import random
from pathlib import Path
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from django.db import transaction
from api.models import FuelStation

# SUPER SIMPLE FALLBACK COORDINATES - just get it working!
STATE_APPROX = {
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

# Known city coordinates for major cities (hardcode a few to make it work)
CITY_KNOWN = {
    ("Los Angeles", "CA"): (-118.2437, 34.0522),
    ("San Francisco", "CA"): (-122.4194, 37.7749),
    ("San Diego", "CA"): (-117.1611, 32.7157),
    ("Sacramento", "CA"): (-121.4944, 38.5816),
    ("Las Vegas", "NV"): (-115.1398, 36.1699),
    ("Phoenix", "AZ"): (-112.0740, 33.4484),
    ("Denver", "CO"): (-104.9903, 39.7392),
    ("Salt Lake City", "UT"): (-111.8910, 40.7608),
    ("Seattle", "WA"): (-122.3321, 47.6062),
    ("Portland", "OR"): (-122.6765, 45.5231),
    ("Boise", "ID"): (-116.2023, 43.6150),
    ("Albuquerque", "NM"): (-106.6504, 35.0853),
    ("Tucson", "AZ"): (-110.9265, 32.2226),
    ("Fresno", "CA"): (-119.7726, 36.7378),
    ("Bakersfield", "CA"): (-119.0187, 35.3733),
    ("Stockton", "CA"): (-121.2908, 37.9577),
    ("Reno", "NV"): (-119.8138, 39.5296),
    ("Spokane", "WA"): (-117.4260, 47.6588),
    ("Tacoma", "WA"): (-122.4443, 47.2529),
    ("Eugene", "OR"): (-123.0868, 44.0521),
    ("Salem", "OR"): (-123.0351, 44.9429),
    ("Vancouver", "WA"): (-122.6615, 45.6387),
    ("Olympia", "WA"): (-122.9007, 47.0379),
    ("Billings", "MT"): (-108.5007, 45.7833),
    ("Cheyenne", "WY"): (-104.8202, 41.1400),
    ("Carson City", "NV"): (-119.7674, 39.1638),
    ("Helena", "MT"): (-112.0361, 46.5884),
    ("Pierre", "SD"): (-100.3505, 44.3683),
    ("Bismarck", "ND"): (-100.7837, 46.8083),
    ("Lincoln", "NE"): (-96.6852, 40.8136),
    ("Des Moines", "IA"): (-93.6091, 41.6005),
    ("Madison", "WI"): (-89.4012, 43.0731),
    ("Springfield", "IL"): (-89.6501, 39.7817),
    ("Indianapolis", "IN"): (-86.1581, 39.7684),
    ("Columbus", "OH"): (-82.9988, 39.9612),
    ("Lansing", "MI"): (-84.5555, 42.7325),
    ("Detroit", "MI"): (-83.0458, 42.3314),
    ("Chicago", "IL"): (-87.6298, 41.8781),
    ("Milwaukee", "WI"): (-87.9065, 43.0389),
    ("Minneapolis", "MN"): (-93.2650, 44.9778),
    ("St. Paul", "MN"): (-93.0899, 44.9537),
    ("Kansas City", "MO"): (-94.5786, 39.0997),
    ("St. Louis", "MO"): (-90.1994, 38.6270),
    ("Omaha", "NE"): (-95.9345, 41.2565),
    ("Wichita", "KS"): (-97.3308, 37.6872),
    ("Oklahoma City", "OK"): (-97.5164, 35.4676),
    ("Tulsa", "OK"): (-95.9928, 36.1539),
    ("Dallas", "TX"): (-96.7970, 32.7767),
    ("Fort Worth", "TX"): (-97.3308, 32.7555),
    ("Houston", "TX"): (-95.3698, 29.7604),
    ("San Antonio", "TX"): (-98.4936, 29.4241),
    ("Austin", "TX"): (-97.7431, 30.2672),
    ("El Paso", "TX"): (-106.4850, 31.7619),
    ("New Orleans", "LA"): (-90.0715, 29.9511),
    ("Baton Rouge", "LA"): (-91.1403, 30.4583),
    ("Little Rock", "AR"): (-92.2896, 34.7465),
    ("Memphis", "TN"): (-90.0490, 35.1495),
    ("Nashville", "TN"): (-86.7816, 36.1627),
    ("Knoxville", "TN"): (-83.9207, 35.9606),
    ("Louisville", "KY"): (-85.7585, 38.2527),
    ("Lexington", "KY"): (-84.5037, 38.0406),
    ("Cincinnati", "OH"): (-84.5120, 39.1031),
    ("Cleveland", "OH"): (-81.6944, 41.4993),
    ("Pittsburgh", "PA"): (-79.9959, 40.4406),
    ("Philadelphia", "PA"): (-75.1652, 39.9526),
    ("New York", "NY"): (-74.0060, 40.7128),
    ("Buffalo", "NY"): (-78.8784, 42.8864),
    ("Rochester", "NY"): (-77.6114, 43.1566),
    ("Boston", "MA"): (-71.0589, 42.3601),
    ("Springfield", "MA"): (-72.5898, 42.1015),
    ("Providence", "RI"): (-71.4128, 41.8240),
    ("Hartford", "CT"): (-72.6851, 41.7658),
    ("New Haven", "CT"): (-72.9288, 41.3083),
    ("Portland", "ME"): (-70.2553, 43.6615),
    ("Manchester", "NH"): (-71.4548, 42.9956),
    ("Burlington", "VT"): (-73.2121, 44.4759),
    ("Montpelier", "VT"): (-72.5715, 44.2601),
    ("Baltimore", "MD"): (-76.6122, 39.2904),
    ("Annapolis", "MD"): (-76.4922, 38.9784),
    ("Washington", "DC"): (-77.0369, 38.9072),
    ("Richmond", "VA"): (-77.4360, 37.5407),
    ("Norfolk", "VA"): (-76.2859, 36.8508),
    ("Virginia Beach", "VA"): (-75.9780, 36.8529),
    ("Charleston", "WV"): (-81.6326, 38.3498),
    ("Charlotte", "NC"): (-80.8431, 35.2271),
    ("Raleigh", "NC"): (-78.6382, 35.7796),
    ("Greensboro", "NC"): (-79.7920, 36.0726),
    ("Columbia", "SC"): (-81.0348, 34.0007),
    ("Charleston", "SC"): (-79.9311, 32.7765),
    ("Atlanta", "GA"): (-84.3880, 33.7490),
    ("Savannah", "GA"): (-81.0998, 32.0809),
    ("Jacksonville", "FL"): (-81.6557, 30.3322),
    ("Miami", "FL"): (-80.1918, 25.7617),
    ("Orlando", "FL"): (-81.3792, 28.5383),
    ("Tampa", "FL"): (-82.4572, 27.9506),
    ("Tallahassee", "FL"): (-84.2807, 30.4383),
    ("Birmingham", "AL"): (-86.8025, 33.5207),
    ("Montgomery", "AL"): (-86.3006, 32.3792),
    ("Mobile", "AL"): (-88.0399, 30.6954),
    ("Jackson", "MS"): (-90.1848, 32.2988),
    ("Honolulu", "HI"): (-157.8583, 21.3069),
    ("Anchorage", "AK"): (-149.9003, 61.2181),
    ("Fairbanks", "AK"): (-147.7164, 64.8378),
    ("Juneau", "AK"): (-134.4197, 58.3019),
}

class Command(BaseCommand):
    help = "FORCE geocode all stations NOW with fallback coordinates"

    def handle(self, *args, **options):
        # Get all stations without location
        stations = FuelStation.objects.filter(location__isnull=True)
        total = stations.count()
        
        if total == 0:
            self.stdout.write(self.style.SUCCESS("All stations already geocoded!"))
            return
        
        self.stdout.write(f"Geocoding {total} stations...")
        
        batch = []
        updated = 0
        skipped = 0
        
        # Process in chunks
        for station in stations.iterator(chunk_size=500):
            cache_key = (station.city.strip(), station.state.strip())
            
            # Try city-specific first
            if cache_key in CITY_KNOWN:
                lon, lat = CITY_KNOWN[cache_key]
            # Fallback to state centroid
            elif station.state in STATE_APPROX:
                lon, lat = STATE_APPROX[station.state]
            else:
                skipped += 1
                continue
            
            # Add small random jitter so stations don't overlap
            jitter = 0.01  # ~1km
            lon += random.uniform(-jitter, jitter)
            lat += random.uniform(-jitter, jitter)
            
            station.location = Point(lon, lat, srid=4326)
            batch.append(station)
            
            if len(batch) >= 500:
                FuelStation.objects.bulk_update(batch, ["location"])
                updated += len(batch)
                batch = []
                self.stdout.write(f"  Updated {updated} stations...")
        
        # Final batch
        if batch:
            FuelStation.objects.bulk_update(batch, ["location"])
            updated += len(batch)
        
        self.stdout.write(
            self.style.SUCCESS(f"✅ DONE! Updated: {updated}, Skipped: {skipped}")
        )
        
        # Verify
        geocoded = FuelStation.objects.filter(location__isnull=False).count()
        self.stdout.write(f"Total geocoded stations: {geocoded}")