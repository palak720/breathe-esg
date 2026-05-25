"""
Utility Portal CSV Parser
==========================
Handles electricity data CSV exports from utility company portals.
We chose CSV portal export over PDF or direct API for these reasons:

1. PDF: requires OCR or table extraction. Bill formats vary enormously by
   utility and change without notice. Brittle for a prototype.

2. Direct API: Most US utilities offer Green Button Connect (ESPI standard)
   or a vendor API (Urjanet, Arcadia). These require OAuth2 setup with each
   utility individually and often a formal data-sharing agreement. Not
   feasible in a 4-day window, and not how facilities teams actually work.

3. CSV portal export: The practical reality. Every major US utility (PG&E,
   Con Edison, ComEd, National Grid, etc.) offers a "Download Usage Data"
   button in the account portal that produces a CSV. The facilities team
   logs in monthly and downloads it. This matches how clients actually get
   the data.

Complication we handle: billing periods ≠ calendar months.
  A utility reads your meter on e.g. the 17th of each month. So a "March"
  bill covers Feb 17 – Mar 17. We record period_start and period_end exactly
  as given, and flag any record where the period is >35 days (might be an
  estimated or combined bill) or <25 days (short read).

Column naming across utilities is not standardized. We handle the two most
common formats:

Format A — PG&E / National Grid style:
  Account Number, Meter ID, Service Address, Billing Start Date,
  Billing End Date, Usage (kWh), Peak Demand (kW), Amount ($), Rate Schedule

Format B — Con Edison / ComEd style:
  Account, Service Location, Read Date From, Read Date To,
  Net Usage kWh, Reactive Demand kVAR, Charges ($), Tariff

We try format A first, then format B.

Emission factor: EPA eGRID 2022 US average (0.3857 lb CO2e/kWh = 0.1749 kg).
In production, you'd use the grid subregion (from service address or meter
NERC code) for a more accurate factor.
"""

import csv
import io
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger(__name__)

# EPA eGRID 2022 US annual average emission rate
# A real deployment would use the correct NERC subregion rate.
ELECTRICITY_FACTOR_KG_PER_KWH = Decimal("0.1749")
ELECTRICITY_FACTOR_SOURCE = "EPA eGRID 2022 — US annual average"

# Column aliases — ordered by specificity (more specific first)
COLUMN_ALIASES = {
    "account":     ["Account Number", "Account", "Acct Number", "Account #"],
    "meter_id":    ["Meter ID", "Meter Number", "Meter Serial", "Meter"],
    "address":     ["Service Address", "Service Location", "Address"],
    "period_start":["Billing Start Date", "Read Date From", "Start Date", "From Date", "Period Start"],
    "period_end":  ["Billing End Date", "Read Date To", "End Date", "To Date", "Period End"],
    "usage_kwh":   ["Usage (kWh)", "Net Usage kWh", "kWh Used", "Usage kWh", "Consumption (kWh)", "kWh"],
    "demand_kw":   ["Peak Demand (kW)", "Demand kW", "Peak kW", "Demand (kW)"],
    "amount":      ["Amount ($)", "Charges ($)", "Total Charges", "Bill Amount", "Amount"],
    "rate":        ["Rate Schedule", "Tariff", "Rate", "Rate Code"],
}


def _resolve_columns(headers: list[str]) -> dict[str, str]:
    resolved = {}
    headers_upper = {h.strip(): h.strip() for h in headers}
    for internal_key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            for h in headers:
                if h.strip().lower() == alias.lower():
                    resolved[internal_key] = h.strip()
                    break
            if internal_key in resolved:
                break
    return resolved


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(raw: str) -> Optional[Decimal]:
    """Strip currency symbols and commas."""
    raw = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _period_flags(start: date, end: date) -> list[str]:
    flags = []
    days = (end - start).days
    if days > 35:
        flags.append("PERIOD_LONG_ESTIMATED_OR_COMBINED")
    if days < 20:
        flags.append("PERIOD_SHORT_CHECK_READ")
    return flags


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
        return {"records": [], "errors": [{"row": "file", "error": "Could not decode"}], "metadata": {}}

    # Some utility exports prepend account info lines before the CSV data
    # Strip non-CSV header lines (lines that don't contain a comma)
    lines = text.splitlines()
    data_start = 0
    for idx, line in enumerate(lines):
        if "," in line and any(
            alias.lower() in line.lower()
            for aliases in COLUMN_ALIASES.values() for alias in aliases
        ):
            data_start = idx
            break

    clean_text = "\n".join(lines[data_start:])
    reader = csv.DictReader(io.StringIO(clean_text))
    headers = reader.fieldnames or []
    col_map = _resolve_columns(headers)

    # Require at minimum: period dates and usage
    required = ["period_start", "period_end", "usage_kwh"]
    missing = [k for k in required if k not in col_map]
    if missing:
        return {
            "records": [],
            "errors": [{"row": "header", "error": f"Required columns not found: {missing}. Headers seen: {headers}"}],
            "metadata": {"headers_found": headers},
        }

    metadata = {
        "encoding": detected_encoding,
        "headers_found": headers,
        "columns_mapped": col_map,
        "data_start_row": data_start,
    }

    records = []
    errors = []

    for i, row in enumerate(reader, start=data_start + 2):
        row_ref = f"row {i}"
        try:
            raw_start = row.get(col_map["period_start"], "").strip()
            raw_end = row.get(col_map["period_end"], "").strip()
            if not raw_start and not raw_end:
                continue  # blank row, skip silently

            period_start = _parse_date(raw_start)
            period_end = _parse_date(raw_end)
            if not period_start or not period_end:
                errors.append({"row": row_ref, "raw": dict(row), "error": f"Bad dates: {raw_start!r} / {raw_end!r}"})
                continue

            raw_kwh = row.get(col_map["usage_kwh"], "")
            usage_kwh = _parse_decimal(raw_kwh)
            if usage_kwh is None:
                errors.append({"row": row_ref, "raw": dict(row), "error": f"Unparseable kWh: {raw_kwh!r}"})
                continue

            auto_flags = _period_flags(period_start, period_end)
            if usage_kwh < 0:
                auto_flags.append("VALUE_NEGATIVE_CHECK_CREDIT")
            if usage_kwh > Decimal("1000000"):
                auto_flags.append("VALUE_OUTLIER_HIGH")
            if usage_kwh == 0:
                auto_flags.append("VALUE_ZERO")

            co2e = (usage_kwh * ELECTRICITY_FACTOR_KG_PER_KWH).quantize(Decimal("0.000001"))

            account = row.get(col_map.get("account", ""), "").strip()
            meter_id = row.get(col_map.get("meter_id", ""), "").strip()
            address = row.get(col_map.get("address", ""), "").strip()
            rate = row.get(col_map.get("rate", ""), "").strip()

            # facility_code: prefer meter_id (most stable identifier), fallback account
            facility_code = meter_id or account

            records.append(EmissionRecord(
                org=org,
                job=job,
                scope=2,
                category="ELECTRICITY",
                period_start=period_start,
                period_end=period_end,
                facility_code=facility_code,
                facility_name=address,
                country_code="USA",  # utility portal implies US; override if client is non-US
                department="",
                activity_quantity_source=usage_kwh,
                activity_unit_source="kWh",
                activity_quantity=usage_kwh,
                activity_unit="kWh",
                co2e_kg=co2e,
                emission_factor=ELECTRICITY_FACTOR_KG_PER_KWH,
                emission_factor_source=ELECTRICITY_FACTOR_SOURCE,
                raw_data=dict(row),
                source_row_ref=row_ref,
                vendor=row.get(col_map.get("rate", ""), "").strip() or "Utility",
                description=f"Meter {meter_id} | Rate: {rate}" if meter_id else rate,
                flag_reasons=auto_flags,
                status="FLAGGED" if auto_flags else "PENDING",
            ))

        except Exception as e:
            logger.exception(f"Utility parser error at {row_ref}")
            errors.append({"row": row_ref, "raw": dict(row), "error": str(e)})

    return {"records": records, "errors": errors, "metadata": metadata}
