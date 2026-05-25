"""
Creates a demo organization, analyst user, admin user, and uploads sample
files through the parser pipeline so the app has data on first boot.
"""
import os
import io
import csv
from django.core.management.base import BaseCommand
from django.core.files.uploadedfile import InMemoryUploadedFile
from apps.core.models import Organization, User
from apps.ingestion.models import IngestionJob
from apps.ingestion.parsers import sap, utility, travel
from apps.emissions.models import EmissionRecord


def make_csv(rows: list[dict]) -> InMemoryUploadedFile:
    buf = io.StringIO()
    # Build a stable superset of headers across all rows so optional fields
    # (e.g. "Distance (km)" in travel data) don't crash DictWriter.
    fieldnames = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    content = buf.getvalue().encode("utf-8")
    return InMemoryUploadedFile(
        io.BytesIO(content), "file", "sample.csv", "text/csv", len(content), None
    )


# ── SAP sample data ──────────────────────────────────────────────────────────
# Modeled on a real SE16 export from table MSEG (material documents)
# with SAP English column headers. Plant DE01 = fictional German site.
# GL accounts 4030/4031 = mobile fuel, 4020/4021 = stationary fuel (heating).
# Units intentionally mixed: L (liters) and TO (metric tons) to test conversion.
SAP_ROWS = [
    {"Posting Date": "20240115", "Plant": "DE01", "G/L Account": "4030",
     "Cost Center": "CC-FLEET", "Material Group": "002", "Quantity": "1250.000",
     "ME": "L", "Net Value": "1875.00", "WAERS": "EUR",
     "Vendor": "SHELL-DE", "Short Text": "Diesel fleet refuel Jan",
     "Belegnummer": "5000012301"},
    {"Posting Date": "20240115", "Plant": "DE01", "G/L Account": "4021",
     "Cost Center": "CC-FACIL", "Material Group": "001", "Quantity": "8.500",
     "ME": "TO",  # metric tons of heating oil — tests TO→kg→L conversion path
     "Net Value": "8075.00", "WAERS": "EUR",
     "Vendor": "HEIZOEL-AG", "Short Text": "Heating oil Jan boiler room",
     "Belegnummer": "5000012302"},
    {"Posting Date": "20240201", "Plant": "US02", "G/L Account": "4031",
     "Cost Center": "CC-FLEET", "Material Group": "002", "Quantity": "840.000",
     "ME": "GAL",  # US site uses gallons — tests GAL→L conversion
     "Net Value": "3024.00", "WAERS": "USD",
     "Vendor": "CHEVRON-US", "Short Text": "Petrol fleet Feb US site",
     "Belegnummer": "5000012310"},
    {"Posting Date": "20240201", "Plant": "DE01", "G/L Account": "5001",
     "Cost Center": "CC-PROC", "Material Group": "020", "Quantity": "1.000",
     "ME": "ST",  # pieces — unmappable unit, tests UNIT_PIECE_UNCONVERTIBLE flag
     "Net Value": "12500.00", "WAERS": "EUR",
     "Vendor": "BASF-AG", "Short Text": "Raw material procurement",
     "Belegnummer": "5000012315"},
    # Row with bad date to test error handling
    {"Posting Date": "not-a-date", "Plant": "DE01", "G/L Account": "4030",
     "Cost Center": "CC-FLEET", "Material Group": "002", "Quantity": "500.000",
     "ME": "L", "Net Value": "750.00", "WAERS": "EUR",
     "Vendor": "SHELL-DE", "Short Text": "Should fail — bad date",
     "Belegnummer": "5000099999"},
    # Outlier quantity to trigger VALUE_OUTLIER_HIGH flag
    {"Posting Date": "20240215", "Plant": "DE01", "G/L Account": "4030",
     "Cost Center": "CC-FLEET", "Material Group": "002", "Quantity": "9999999.000",
     "ME": "L", "Net Value": "999999.00", "WAERS": "EUR",
     "Vendor": "SHELL-DE", "Short Text": "Suspicious large quantity",
     "Belegnummer": "5000012399"},
]

# ── Utility sample data ───────────────────────────────────────────────────────
# Modeled on PG&E "Green Button" portal CSV export.
# Note: billing periods deliberately straddle calendar months (17th to 17th).
# One row has >35 days between reads — simulates estimated bill.
UTILITY_ROWS = [
    {"Account Number": "ACC-004821", "Meter ID": "MTR-A1023",
     "Service Address": "1 Market St, San Francisco, CA",
     "Billing Start Date": "12/17/2023", "Billing End Date": "01/17/2024",
     "Usage (kWh)": "142500", "Peak Demand (kW)": "285",
     "Amount ($)": "18525.00", "Rate Schedule": "E-19"},
    {"Account Number": "ACC-004821", "Meter ID": "MTR-A1023",
     "Service Address": "1 Market St, San Francisco, CA",
     "Billing Start Date": "01/17/2024", "Billing End Date": "02/17/2024",
     "Usage (kWh)": "138200", "Peak Demand (kW)": "276",
     "Amount ($)": "17966.00", "Rate Schedule": "E-19"},
    {"Account Number": "ACC-004821", "Meter ID": "MTR-A1023",
     "Service Address": "1 Market St, San Francisco, CA",
     "Billing Start Date": "02/17/2024", "Billing End Date": "02/24/2024",  # <25 days — short read
     "Usage (kWh)": "32000", "Peak Demand (kW)": "280",
     "Amount ($)": "4160.00", "Rate Schedule": "E-19"},
    {"Account Number": "ACC-004821", "Meter ID": "MTR-B2041",
     "Service Address": "500 Howard St, San Francisco, CA",
     "Billing Start Date": "12/20/2023", "Billing End Date": "02/05/2024",  # >35 days — estimated
     "Usage (kWh)": "298000", "Peak Demand (kW)": "410",
     "Amount ($)": "38740.00", "Rate Schedule": "E-20"},
    {"Account Number": "ACC-004821", "Meter ID": "MTR-B2041",
     "Service Address": "500 Howard St, San Francisco, CA",
     "Billing Start Date": "02/05/2024", "Billing End Date": "03/05/2024",
     "Usage (kWh)": "145000", "Peak Demand (kW)": "405",
     "Amount ($)": "18850.00", "Rate Schedule": "E-20"},
]

# ── Travel sample data ────────────────────────────────────────────────────────
# Modeled on Concur Travel "Detailed Trip Report" export.
# Mix of: flight with known IATA codes, flight with unknown airport (flags),
# hotel with explicit nights, hotel without nights (derived from dates),
# ground transport with distance, ground without distance (flags).
TRAVEL_ROWS = [
    {"Employee ID": "EMP-1042", "Employee Name": "Sarah Chen",
     "Trip Name": "Q1 Client Visit NYC", "Segment Type": "AIR",
     "Origin": "SFO", "Destination": "JFK",
     "Departure Date": "02/05/2024", "Return Date": "02/05/2024",
     "Vendor": "United Airlines", "Class of Service": "Economy",
     "Nights": "", "Amount": "487.00", "Currency": "USD"},
    {"Employee ID": "EMP-1042", "Employee Name": "Sarah Chen",
     "Trip Name": "Q1 Client Visit NYC", "Segment Type": "HOTEL",
     "Origin": "New York", "Destination": "New York",
     "Departure Date": "02/05/2024", "Return Date": "02/07/2024",
     "Vendor": "Marriott Midtown", "Class of Service": "",
     "Nights": "2", "Amount": "620.00", "Currency": "USD"},
    {"Employee ID": "EMP-1042", "Employee Name": "Sarah Chen",
     "Trip Name": "Q1 Client Visit NYC", "Segment Type": "CAR",
     "Origin": "JFK Airport", "Destination": "Midtown Manhattan",
     "Departure Date": "02/05/2024", "Return Date": "02/05/2024",
     "Vendor": "Lyft", "Class of Service": "",
     "Nights": "", "Distance (km)": "22", "Amount": "45.00", "Currency": "USD"},
    # Long-haul business class — tests multiplier (2.9x)
    {"Employee ID": "EMP-0291", "Employee Name": "Marcus Weber",
     "Trip Name": "APAC Strategy Meeting", "Segment Type": "Flight",
     "Origin": "FRA", "Destination": "SIN",
     "Departure Date": "03/10/2024", "Return Date": "03/10/2024",
     "Vendor": "Lufthansa", "Class of Service": "Business Class",
     "Nights": "", "Amount": "4200.00", "Currency": "EUR"},
    # Unknown airport code — tests AIRPORT_UNKNOWN flag
    {"Employee ID": "EMP-0291", "Employee Name": "Marcus Weber",
     "Trip Name": "APAC Strategy Meeting", "Segment Type": "AIR",
     "Origin": "XYZ", "Destination": "SIN",
     "Departure Date": "03/17/2024", "Return Date": "03/17/2024",
     "Vendor": "Regional Air", "Class of Service": "Economy",
     "Nights": "", "Amount": "380.00", "Currency": "SGD"},
    # Ground transport without distance — tests MISSING_DISTANCE flag
    {"Employee ID": "EMP-1042", "Employee Name": "Sarah Chen",
     "Trip Name": "Q1 Client Visit NYC", "Segment Type": "TAXI",
     "Origin": "", "Destination": "",
     "Departure Date": "02/07/2024", "Return Date": "02/07/2024",
     "Vendor": "NYC Yellow Cab", "Class of Service": "",
     "Nights": "", "Distance (km)": "", "Amount": "38.00", "Currency": "USD"},
    # Hotel without nights field — should derive from dates
    {"Employee ID": "EMP-0291", "Employee Name": "Marcus Weber",
     "Trip Name": "APAC Strategy Meeting", "Segment Type": "HOTEL",
     "Origin": "Singapore", "Destination": "Singapore",
     "Departure Date": "03/10/2024", "Return Date": "03/14/2024",
     "Vendor": "Marina Bay Sands", "Class of Service": "",
     "Nights": "", "Amount": "1800.00", "Currency": "SGD"},
]


class Command(BaseCommand):
    help = "Seed demo data for Breathe ESG prototype"

    def handle(self, *args, **options):
        self.stdout.write("Creating demo organization...")
        org, _ = Organization.objects.get_or_create(name="Acme Corp", slug="acme")

        self.stdout.write("Creating users...")
        admin, _ = User.objects.get_or_create(username="admin", defaults={
            "email": "admin@acme.com", "org": org, "role": "ADMIN",
            "is_staff": True, "is_superuser": True,
        })
        admin.set_password("breathe2024")
        admin.save()

        analyst, _ = User.objects.get_or_create(username="analyst", defaults={
            "email": "analyst@acme.com", "org": org, "role": "ANALYST",
        })
        analyst.set_password("breathe2024")
        analyst.save()

        self.stdout.write("Ingesting SAP sample data...")
        self._ingest(org, admin, "SAP_FLAT_FILE", SAP_ROWS, sap)

        self.stdout.write("Ingesting utility sample data...")
        self._ingest(org, admin, "UTILITY_CSV", UTILITY_ROWS, utility)

        self.stdout.write("Ingesting travel sample data...")
        self._ingest(org, admin, "TRAVEL_CSV", TRAVEL_ROWS, travel)

        self.stdout.write(self.style.SUCCESS(
            "\nSeed complete!\n"
            "  Admin:   admin / breathe2024\n"
            "  Analyst: analyst / breathe2024\n"
            f"  Records created: {EmissionRecord.objects.filter(org=org).count()}"
        ))

    def _ingest(self, org, user, source_type, rows, parser_module):
        file_obj = make_csv(rows)
        job = IngestionJob.objects.create(
            org=org, source_type=source_type, status="PROCESSING",
            uploaded_file=file_obj, original_filename=f"sample_{source_type.lower()}.csv",
            uploaded_by=user,
        )
        file_obj.seek(0)
        result = parser_module.parse(file_obj, job, org)
        from django.utils import timezone
        EmissionRecord.objects.bulk_create(result["records"], batch_size=500)
        from apps.ingestion.models import ParseError
        ParseError.objects.bulk_create([
            ParseError(job=job, row_ref=e.get("row", "?"),
                       raw_content=str(e.get("raw", "")), error_message=e.get("error", ""))
            for e in result["errors"]
        ], batch_size=500)
        job.status = "COMPLETE"
        job.row_count_total = len(result["records"]) + len(result["errors"])
        job.row_count_parsed = len(result["records"])
        job.row_count_failed = len(result["errors"])
        job.metadata = result.get("metadata", {})
        job.processed_at = timezone.now()
        job.save()
        self.stdout.write(f"  -> {source_type}: {len(result['records'])} records, {len(result['errors'])} errors")
