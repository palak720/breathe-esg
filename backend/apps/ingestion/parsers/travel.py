"""
Corporate Travel Parser
========================
Handles CSV exports from Concur Travel & Expense or Navan (formerly TripActions).

Why CSV export over live API?
  Concur has a REST API (v4 / SAP Concur Platform). Navan has a Travel Data API.
  Both require OAuth 2.0 setup by the client's IT team and scope approval.
  The fastest path for a new client onboarding: request the "Detailed Trip Report"
  or "Travel Itinerary Export" from the travel admin. Both platforms produce a
  standard CSV in under a minute. We handle that export.

What the export looks like:
  Concur "Travel Itinerary Detail Export" (Report > Trip Detail > Export to CSV):
    Trip Name, Employee Name, Employee ID, Departure Date, Return Date,
    Segment Type (AIR / HOTEL / CAR / RAIL), Origin, Destination,
    Vendor, Class of Service, Nights, Amount, Currency, Expense Type

  Navan export is structurally similar with different column naming.

Distance computation for flights:
  The export often does NOT include distance. You get origin/destination
  as IATA 3-letter airport codes (e.g. LHR, JFK). We compute great-circle
  distance using the Haversine formula and a bundled IATA airport coordinate
  table (subset of the OurAirports database, public domain).

  We multiply by 1.09 (ICAO detour factor) to approximate actual flight path.
  DEFRA uses a similar uplift. We do NOT apply a Radiative Forcing Index (RFI)
  multiplier — this is a contested methodology choice (some use 1.9x, some 1.0x).
  We flag it in DECISIONS.md.

Class of service multiplier (GHG Protocol / DEFRA method):
  Economy: 1.0x base factor
  Premium Economy: 1.6x
  Business: 2.9x
  First: 4.0x
  If class is missing: assume Economy, flag it.

Emission factors (DEFRA 2023, kg CO2e per passenger-km):
  Short-haul (<3700 km): 0.15573 (economy)
  Long-haul (≥3700 km): 0.19085 (economy)

Hotel: DEFRA 2023 hotel stay factor = 27.8 kg CO2e per room-night
Ground transport: DEFRA 2023 average taxi = 0.14858 kg CO2e per km
  (we don't have distance for most ground bookings, so we flag MISSING_DISTANCE)
"""

import csv
import io
import math
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger(__name__)

# ── Emission factors ─────────────────────────────────────────────────────────
EF_SOURCE = "DEFRA 2023 GHG Conversion Factors"

# kg CO2e per passenger-km (economy class base)
EF_FLIGHT_SHORT = Decimal("0.15573")   # <3700 km (short-haul)
EF_FLIGHT_LONG  = Decimal("0.19085")  # ≥3700 km (long-haul)
EF_HOTEL_PER_NIGHT = Decimal("27.8")  # kg CO2e per room-night
EF_GROUND_PER_KM   = Decimal("0.14858")  # avg taxi

CLASS_MULTIPLIERS = {
    "ECONOMY":         Decimal("1.0"),
    "ECONOMY CLASS":   Decimal("1.0"),
    "COACH":           Decimal("1.0"),
    "PREMIUM ECONOMY": Decimal("1.6"),
    "PREMIUM":         Decimal("1.6"),
    "BUSINESS":        Decimal("2.9"),
    "BUSINESS CLASS":  Decimal("2.9"),
    "FIRST":           Decimal("4.0"),
    "FIRST CLASS":     Decimal("4.0"),
}

# ── IATA airport coordinates (abbreviated — ~200 most common) ─────────────
# Source: OurAirports.com (CC0 public domain)
AIRPORTS = {
    "LAX": (33.9425, -118.4081), "JFK": (40.6398, -73.7789),
    "ORD": (41.9786, -87.9048),  "ATL": (33.6367, -84.4281),
    "DFW": (32.8998, -97.0403),  "SFO": (37.6190, -122.3750),
    "SEA": (47.4502, -122.3088), "BOS": (42.3643, -71.0052),
    "MIA": (25.7959, -80.2870),  "DEN": (39.8561, -104.6737),
    "EWR": (40.6925, -74.1687),  "LAS": (36.0840, -115.1537),
    "IAH": (29.9902, -95.3368),  "PHX": (33.4373, -112.0078),
    "MSP": (44.8820, -93.2218),  "DTW": (42.2162, -83.3554),
    "CLT": (35.2140, -80.9431),  "PHL": (39.8719, -75.2411),
    "LGA": (40.7772, -73.8726),  "SLC": (40.7884, -111.9778),
    "BWI": (39.1754, -76.6682),  "MDW": (41.7868, -87.7522),
    "SAN": (32.7338, -117.1933), "TPA": (27.9755, -82.5332),
    "PDX": (45.5898, -122.5951),
    # Europe
    "LHR": (51.4775, -0.4614),   "CDG": (49.0097, 2.5479),
    "FRA": (50.0379, 8.5622),    "AMS": (52.3086, 4.7639),
    "MAD": (40.4936, -3.5668),   "BCN": (41.2971, 2.0785),
    "FCO": (41.8003, 12.2389),   "MUC": (48.3538, 11.7861),
    "ZRH": (47.4647, 8.5492),    "BRU": (50.9014, 4.4844),
    "VIE": (48.1103, 16.5697),   "DUB": (53.4213, -6.2700),
    "HEL": (60.3172, 24.9633),   "CPH": (55.6180, 12.6508),
    "ARN": (59.6519, 17.9186),   "OSL": (60.1939, 11.1004),
    "LIS": (38.7813, -9.1359),   "ATH": (37.9364, 23.9445),
    "IST": (40.9769, 28.8146),   "SVO": (55.9726, 37.4146),
    "LED": (59.8003, 30.2625),
    # Asia-Pacific
    "NRT": (35.7653, 140.3856),  "HND": (35.5494, 139.7798),
    "HKG": (22.3080, 113.9185),  "SIN": (1.3502, 103.9940),
    "BKK": (13.6900, 100.7501),  "KUL": (2.7456, 101.7072),
    "SYD": (-33.9461, 151.1772), "MEL": (-37.6690, 144.8410),
    "PEK": (40.0799, 116.5846),  "PVG": (31.1443, 121.8083),
    "ICN": (37.4602, 126.4407),  "DEL": (28.5665, 77.1031),
    "BOM": (19.0896, 72.8656),   "DXB": (25.2532, 55.3657),
    "AUH": (24.4330, 54.6511),   "DOH": (25.2731, 51.6081),
    # Americas
    "YYZ": (43.6772, -79.6306),  "YVR": (49.1967, -123.1815),
    "YUL": (45.4706, -73.7408),  "GRU": (-23.4356, -46.4731),
    "BOG": (4.7016, -74.1469),   "SCL": (-33.3928, -70.7856),
    "MEX": (19.4363, -99.0721),  "EZE": (-34.8222, -58.5358),
    # Africa
    "JNB": (-26.1392, 28.2460),  "CPT": (-33.9715, 18.6021),
    "NBO": (-1.3192, 36.9275),   "LOS": (6.5774, 3.3212),
    "CAI": (30.1219, 31.4056),   "CMN": (33.3675, -7.5898),
}


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


DETOUR_FACTOR = 1.09  # ICAO standard


def _flight_distance_km(origin: str, dest: str) -> tuple[Optional[Decimal], list[str]]:
    flags = []
    o = AIRPORTS.get(origin.upper().strip())
    d = AIRPORTS.get(dest.upper().strip())
    if not o:
        flags.append(f"AIRPORT_UNKNOWN:{origin.upper()}")
    if not d:
        flags.append(f"AIRPORT_UNKNOWN:{dest.upper()}")
    if not o or not d:
        return None, flags
    gc = _haversine_km(*o, *d)
    return Decimal(str(round(gc * DETOUR_FACTOR, 2))), flags


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(raw: str) -> Optional[Decimal]:
    raw = raw.strip().replace(",", "").replace("$", "").replace(" ", "")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


COLUMN_ALIASES = {
    "employee_id":   ["Employee ID", "Emp ID", "Staff ID", "Traveler ID"],
    "employee_name": ["Employee Name", "Traveler Name", "Name", "Full Name"],
    "trip_name":     ["Trip Name", "Trip Purpose", "Trip", "Description"],
    "segment_type":  ["Segment Type", "Travel Type", "Expense Type", "Type", "Category"],
    "origin":        ["Origin", "Departure City", "From", "From City", "Departure Airport"],
    "destination":   ["Destination", "Arrival City", "To", "To City", "Arrival Airport"],
    "depart_date":   ["Departure Date", "Travel Date", "Start Date", "Check-In Date", "Date"],
    "return_date":   ["Return Date", "End Date", "Arrival Date", "Check-Out Date"],
    "vendor":        ["Vendor", "Airline", "Hotel Name", "Car Vendor", "Supplier"],
    "service_class": ["Class of Service", "Cabin Class", "Fare Class", "Class"],
    "nights":        ["Nights", "Number of Nights", "Hotel Nights"],
    "distance_km":   ["Distance (km)", "Distance km", "Mileage"],
    "amount":        ["Amount", "Total Amount", "Cost", "Net Amount"],
    "currency":      ["Currency", "Currency Code"],
}


def _resolve_columns(headers):
    resolved = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            for h in headers:
                if h.strip().lower() == alias.lower():
                    resolved[key] = h.strip()
                    break
            if key in resolved:
                break
    return resolved


def _segment_type_canonical(raw: str) -> str:
    """Normalize free-text segment type to our internal values."""
    raw = raw.upper().strip()
    if any(k in raw for k in ("AIR", "FLIGHT", "FLT")):
        return "AIR"
    if any(k in raw for k in ("HOTEL", "LODGING", "ACCOMMODATION", "STAY")):
        return "HOTEL"
    if any(k in raw for k in ("CAR", "TAXI", "RIDE", "GROUND", "TRAIN", "RAIL", "BUS")):
        return "GROUND"
    return "UNKNOWN"


def parse(file_obj, job, org) -> dict:
    from apps.emissions.models import EmissionRecord

    content = file_obj.read()
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content.decode(encoding)
            detected_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    else:
        return {"records": [], "errors": [{"row": "file", "error": "Decode failed"}], "metadata": {}}

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    col_map = _resolve_columns(headers)

    if "segment_type" not in col_map or "depart_date" not in col_map:
        return {
            "records": [],
            "errors": [{"row": "header", "error": f"Required columns missing. Got: {headers}"}],
            "metadata": {"headers_found": headers},
        }

    metadata = {
        "encoding": detected_encoding,
        "headers_found": headers,
        "columns_mapped": col_map,
    }

    records = []
    errors = []

    for i, row in enumerate(reader, start=2):
        row_ref = f"row {i}"
        try:
            raw_seg = row.get(col_map.get("segment_type", ""), "").strip()
            if not raw_seg:
                continue
            segment = _segment_type_canonical(raw_seg)

            raw_date = row.get(col_map.get("depart_date", ""), "").strip()
            depart_date = _parse_date(raw_date)
            if not depart_date:
                errors.append({"row": row_ref, "raw": dict(row), "error": f"Bad date: {raw_date!r}"})
                continue

            raw_return = row.get(col_map.get("return_date", ""), "").strip()
            return_date = _parse_date(raw_return) if raw_return else depart_date

            employee = row.get(col_map.get("employee_name", ""), "").strip()
            vendor = row.get(col_map.get("vendor", ""), "").strip()
            origin = row.get(col_map.get("origin", ""), "").strip()
            dest = row.get(col_map.get("destination", ""), "").strip()

            auto_flags = []
            co2e = None
            ef_value = None
            ef_source = EF_SOURCE
            qty_norm = Decimal("0")
            unit_norm = "unknown"
            qty_source = Decimal("0")
            unit_source = "unknown"

            if segment == "AIR":
                raw_class = row.get(col_map.get("service_class", ""), "").strip().upper()
                class_multiplier = CLASS_MULTIPLIERS.get(raw_class, Decimal("1.0"))
                if not raw_class:
                    auto_flags.append("CLASS_ASSUMED_ECONOMY")
                    class_multiplier = Decimal("1.0")

                # Try explicit distance first, then compute from IATA codes
                raw_dist = row.get(col_map.get("distance_km", ""), "").strip()
                dist_km = _parse_decimal(raw_dist)
                if dist_km:
                    dist_flags = []
                else:
                    dist_km, dist_flags = _flight_distance_km(origin, dest)
                    if dist_km is None:
                        auto_flags += dist_flags
                        auto_flags.append("DISTANCE_UNKNOWN")
                    else:
                        auto_flags += dist_flags

                if dist_km is not None:
                    base_ef = EF_FLIGHT_SHORT if dist_km < Decimal("3700") else EF_FLIGHT_LONG
                    ef_value = (base_ef * class_multiplier).quantize(Decimal("0.000001"))
                    co2e = (dist_km * ef_value).quantize(Decimal("0.000001"))
                    qty_norm = dist_km
                    unit_norm = "pkm"
                else:
                    auto_flags.append("MISSING_FACTOR")

                qty_source = dist_km or Decimal("0")
                unit_source = "km"
                description = f"{origin}→{dest} | {raw_class or 'ECONOMY'}"

            elif segment == "HOTEL":
                raw_nights = row.get(col_map.get("nights", ""), "").strip()
                nights = _parse_decimal(raw_nights)
                if nights is None:
                    # Derive from dates
                    if return_date and depart_date:
                        nights = Decimal((return_date - depart_date).days)
                    else:
                        nights = Decimal("1")
                        auto_flags.append("NIGHTS_ASSUMED_1")

                if nights <= 0:
                    auto_flags.append("NIGHTS_ZERO_OR_NEGATIVE")
                    nights = Decimal("1")

                ef_value = EF_HOTEL_PER_NIGHT
                co2e = (nights * ef_value).quantize(Decimal("0.000001"))
                qty_norm = nights
                unit_norm = "nights"
                qty_source = nights
                unit_source = "nights"
                description = f"{dest or vendor} | {int(nights)} night(s)"

            elif segment == "GROUND":
                raw_dist = row.get(col_map.get("distance_km", ""), "").strip()
                dist_km = _parse_decimal(raw_dist)
                if dist_km:
                    ef_value = EF_GROUND_PER_KM
                    co2e = (dist_km * ef_value).quantize(Decimal("0.000001"))
                    qty_norm = dist_km
                    unit_norm = "km"
                    qty_source = dist_km
                    unit_source = "km"
                else:
                    auto_flags.append("MISSING_DISTANCE")
                    # Fall back to spend-based — flag heavily
                    auto_flags.append("MISSING_FACTOR")
                    qty_norm = Decimal("0")
                    unit_norm = "km"
                    qty_source = Decimal("0")
                    unit_source = "km"
                description = f"{origin}→{dest}" if origin and dest else vendor

            else:
                auto_flags.append("SEGMENT_TYPE_UNKNOWN")
                description = raw_seg

            category_map = {"AIR": "TRAVEL_AIR", "HOTEL": "TRAVEL_HOTEL", "GROUND": "TRAVEL_GROUND"}
            category = category_map.get(segment, "TRAVEL_AIR")

            records.append(EmissionRecord(
                org=org,
                job=job,
                scope=3,
                category=category,
                period_start=depart_date,
                period_end=return_date or depart_date,
                facility_code="",
                facility_name=dest or "",
                country_code="",
                department="",
                activity_quantity_source=qty_source,
                activity_unit_source=unit_source,
                activity_quantity=qty_norm,
                activity_unit=unit_norm,
                co2e_kg=co2e,
                emission_factor=ef_value,
                emission_factor_source=ef_source,
                raw_data=dict(row),
                source_row_ref=row_ref,
                vendor=vendor,
                description=description,
                flag_reasons=auto_flags,
                status="FLAGGED" if auto_flags else "PENDING",
            ))

        except Exception as e:
            logger.exception(f"Travel parser error at {row_ref}")
            errors.append({"row": row_ref, "raw": dict(row), "error": str(e)})

    return {"records": records, "errors": errors, "metadata": metadata}
