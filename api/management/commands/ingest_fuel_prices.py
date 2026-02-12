import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from tqdm import tqdm

from api.models import FuelStation

CHUNK_SIZE = 500  # Number of rows per bulk insert


class Command(BaseCommand):
    help = "Ingest fuel prices from a CSV file into the FuelStation model."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            required=True,
            help="Path to the CSV file containing fuel prices",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            self.stderr.write(f"File not found: {file_path}")
            return

        self.stdout.write("Starting ingestion...")

        to_create = []
        malformed_rows = 0
        total_rows = sum(1 for _ in open(file_path)) - 1  # exclude header

        with open(file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)

            for row in tqdm(reader, total=total_rows, desc="Processing rows"):
                try:
                    opis_id = int(row["OPIS Truckstop ID"])
                    rack_id = int(row["Rack ID"])
                    truckstop_name = row["Truckstop Name"].strip()
                    address = row["Address"].strip()
                    city = row["City"].strip()
                    state = row["State"].strip()
                    retail_price = Decimal(row["Retail Price"])

                    # Skip location for now; you can populate later with geocoding
                    obj = FuelStation(
                        opis_id=opis_id,
                        rack_id=rack_id,
                        truckstop_name=truckstop_name,
                        address=address,
                        city=city,
                        state=state,
                        retail_price=retail_price,
                    )
                    to_create.append(obj)

                    # Bulk insert in chunks
                    if len(to_create) >= CHUNK_SIZE:
                        with transaction.atomic():
                            FuelStation.objects.bulk_create(to_create, ignore_conflicts=True)
                        to_create = []

                except Exception:
                    malformed_rows += 1
                    continue

        # Insert remaining rows
        if to_create:
            with transaction.atomic():
                FuelStation.objects.bulk_create(to_create, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS("Ingestion complete."))
        self.stdout.write(f"Malformed rows skipped: {malformed_rows}")
        self.stdout.write(f"Total rows ingested: {total_rows - malformed_rows}")
