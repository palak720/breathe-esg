"""
SAP Flat File Parser
====================
Handles CSV/XLSX exports from SAP transaction SE16 (table browser) or
ALV Grid reports, specifically from:
  - Table EKPO / EKKO (purchasing documents) for procurement rows
  - Table MSEG / MKPF (material documents) for goods movements / fuel issues
  - FAGLL03 (G/L account line items) for fuel cost center postings

Why flat file over IDoc or OData?
  IDoc requires an active SAP WE20 partner profile pointing at our endpoint —
  not something a sustainability lead can configure in a week. OData (via
  SAP Gateway) requires the SAP BASIS team to expose the service and set up
  RFC destinations. In practice, the person who actually gets data out of SAP
  for a sustainability project runs SE16, hits Ctrl+Shift+F9 (Export → Local
  File → Spreadsheet), and sends you a .xlsx or .csv. That's what we handle.

Column mapping strategy:
  SAP installs vary. Column headers may be German (the SAP default) or English
  depending on the user's logon language. Material descriptions may be in the
  client language. We try both German and English column names and record which
  we found in job.metadata so analysts can see what we detected.

SAP unit codes → standard units:
  SAP uses its own unit codes (MEINS field), not SI or ISO. Key mappings:
    L  → liters
    KL → kiloliters (= 1000 L)
    M3 → cubic meters (≈ 1000 L for liquids, used for gas)
    KG → kilograms
    TO → metric ton (1000 kg)
    G  → grams
    KWH → kWh (SAP uses this for electricity ordered via procurement)
    GAL → US gallons
    GL  → gallons (some locales)
    LB  → pounds

Emission category detection:
  We infer category from the GL account (HKONT) or Material Group (MATKL).
  The mapping table below reflects common chart-of-accounts conventions;
  a real deployment would need the client's CoA. We flag rows we can't
  categorize so analysts can assign them manually.
"""

import csv
import io
import logging
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional

logger = logging.getLogger(__name__)

# SAP unit code → (standard_unit, conversion_factor_to_standard)
# Standard units: liters for fuel, kWh for electricity, kg for mass
SAP_UNIT_MAP = {
    "L":   ("L", Decimal("1")),
    "LTR": ("L", Decimal("1")),
    "KL":  ("L", Decimal("1000")),
    "M3":  ("L", Decimal("1000")),       # ≈ for liquids; approximate for gas
    "KG":  ("kg", Decimal("1")),
    "TO":  ("kg", Decimal("1000")),
    "G":   ("kg", Decimal("0.001")),
    "KWH": ("kWh", Decimal("1")),
    "MWH": ("kWh", Decimal("1000")),
    "GAL": ("L", Decimal("3.78541")),    # US gallon
    "GL":  ("L", Decimal("3.78541")),
    "LB":  ("kg", Decimal("0.453592")),
    "ST":  ("kg", Decimal("1")),         # SAP 'piece' — can't convert, flag it
}

# GL account prefix → emission category
# In a real deployment this comes from the client's chart of accounts.
# These are illustrative ranges used in German/European SAP landscapes.
GL_TO_CATEGORY = {
    # Fuel / energy accounts (range 4000-4299 common for operating costs)
    "4010": "FUEL_STATIONARY",
    "4011": "FUEL_STATIONARY",
    "4012": "FUEL_MOBILE",
    "4013": "FUEL_MOBILE",
    "4020": "FUEL_STATIONARY",  # heating oil
    "4021": "FUEL_STATIONARY",  # natural gas
    "4030": "FUEL_MOBILE",      # diesel fleet
    "4031": "FUEL_MOBILE",      # petrol fleet
    # Electricity — usually a utility invoice hits a different account
    "4040": "ELECTRICITY",
    "4041": "ELECTRICITY",
    # Procurement catch-all
    "5000": "PROCUREMENT",
    "5001": "PROCUREMENT",
    "5100": "PROCUREMENT",
}

# Material group (MATKL) → category — fallback if no GL match
MATKL_TO_CATEGORY = {
    "001": "FUEL_STATIONARY",   # heating fuels
    "002": "FUEL_MOBILE",       # motor fuels
    "003": "ELECTRICITY",
    "010": "PROCUREMENT",
    "011": "PROCUREMENT",
    "020": "PROCUREMENT",
}

# Column aliases: (german_name, english_name) → internal key
COLUMN_ALIASES = {
    "plant":         ["Werk", "Plant", "WERKS"],
    "company_code":  ["Buchungskreis", "Company Code", "BUKRS"],
    "document_date": ["Belegdatum", "Document Date", "BLDAT"],
    "posting_date":  ["Buchungsdatum", "Posting Date", "BUDAT"],
    "document_no":   ["Belegnummer", "Document Number", "BELNR"],
    "quantity":      ["Menge", "Quantity", "MENGE"],
    "unit":          ["ME", "Unit", "MEINS", "Base Unit of Measure"],
    "net_value":     ["Nettobetrag", "Net Value", "DMBTR"],
    "currency":      ["Währung", "Currency", "WAERS"],
    "gl_account":    ["Sachkonto", "G/L Account", "HKONT"],
    "cost_center":   ["Kostenstelle", "Cost Center", "KOSTL"],
    "material":      ["Material", "Material Number", "MATNR"],
    "material_group":["Materialgruppe", "Material Group", "MATKL"],
    "description":   ["Kurztext", "Short Text", "SGTXT", "Description"],
    "vendor":        ["Lieferant", "Vendor", "LIFNR"],
}

# Emission factors: kg CO2e per liter or per kWh
# Source: DEFRA 2023 Conversion Factors (UK Gov)
EMISSION_FACTORS = {
    "FUEL_STATIONARY": {"factor": Decimal("2.3161"), "unit": "L", "source": "DEFRA 2023 — Gas oil"},
    "FUEL_MOBILE":     {"factor": Decimal("2.5920"), "unit": "L", "source": "DEFRA 2023 — Diesel"},
    "ELECTRICITY":     {"factor": Decimal("0.2328"), "unit": "kWh", "source": "DEFRA 2023 — UK grid avg"},
    "PROCUREMENT":     {"factor": None,               "unit": None, "source": "Spend-based — no factor"},
}


def _resolve_columns(headers: list[str]) -> dict[str, str]:
    """Map actual CSV headers to our internal keys."""
    resolved = {}
    for internal_key, aliases in COLUMN_ALIASES.items():
        for h in headers:
            if h.strip() in aliases or h.strip().upper() in [a.upper() for a in aliases]:
                resolved[internal_key] = h.strip()
                break
    return resolved


def _parse_sap_date(raw: str) -> Optional[date]:
    """
    SAP dates come in several formats depending on the user's locale setting:
      YYYYMMDD  — SAP internal format (most common in exports)
      DD.MM.YYYY — German locale
      MM/DD/YYYY — US locale
    """
    raw = raw.strip()
    for fmt in ("%Y%m%d", "%d.%m.%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_quantity(raw: str) -> Optional[Decimal]:
    """SAP sometimes uses comma as decimal separator (German locale)."""
    raw = raw.strip().replace("\xa0", "").replace(" ", "")
    # If both . and , present, the last one is decimal separator
    if "." in raw and "," in raw:
        if raw.rfind(".") > raw.rfind(","):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _categorize(row: dict, col_map: dict) -> Optional[str]:
    """Try GL account first, then material group, else None."""
    gl = row.get(col_map.get("gl_account", ""), "").strip().lstrip("0")
    for prefix, cat in GL_TO_CATEGORY.items():
        if gl.startswith(prefix):
            return cat

    matkl = row.get(col_map.get("material_group", ""), "").strip()
    return MATKL_TO_CATEGORY.get(matkl)


def _normalize_unit(quantity: Decimal, sap_unit: str):
    """Convert SAP UoM to standard unit. Returns (normalized_qty, standard_unit, flags)."""
    sap_unit = sap_unit.strip().upper()
    if sap_unit not in SAP_UNIT_MAP:
        return quantity, sap_unit, ["UNIT_UNKNOWN"]
    std_unit, factor = SAP_UNIT_MAP[sap_unit]
    flags = []
    if sap_unit == "ST":
        flags.append("UNIT_PIECE_UNCONVERTIBLE")
    return (quantity * factor).quantize(Decimal("0.000001")), std_unit, flags


def _auto_flags(qty: Decimal, unit: str, category: Optional[str]) -> list[str]:
    flags = []
    if qty <= 0:
        flags.append("VALUE_ZERO_OR_NEGATIVE")
    # Rough outlier check — more than 1M liters in a single posting is suspicious
    if unit == "L" and qty > Decimal("1000000"):
        flags.append("VALUE_OUTLIER_HIGH")
    if category is None:
        flags.append("CATEGORY_UNMAPPED")
    return flags


def parse(file_obj, job, org) -> dict:
    """
    Main entry point. file_obj is a Django InMemoryUploadedFile or similar.
    Returns {"records": [...], "errors": [...], "metadata": {...}}
    """
    from apps.emissions.models import EmissionRecord

    content = file_obj.read()
    # Detect encoding — SAP exports are often Latin-1 from German installations
    for encoding in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            text = content.decode(encoding)
            detected_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    else:
        return {"records": [], "errors": [{"row": "file", "error": "Could not decode file"}], "metadata": {}}

    # Detect delimiter — SAP ALV exports use ; in German locale, , in English
    sample = text[:2000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    col_map = _resolve_columns(headers)

    metadata = {
        "encoding": detected_encoding,
        "delimiter": delimiter,
        "headers_found": headers,
        "columns_mapped": col_map,
        "language_detected": "de" if "Werk" in headers or "Menge" in headers else "en",
    }

    records = []
    errors = []

    for i, row in enumerate(reader, start=2):
        row_ref = f"row {i}"
        try:
            # Parse date — prefer posting date, fall back to document date
            raw_date = row.get(col_map.get("posting_date", ""), "") or \
                       row.get(col_map.get("document_date", ""), "")
            parsed_date = _parse_sap_date(raw_date)
            if not parsed_date:
                errors.append({"row": row_ref, "raw": dict(row), "error": f"Unparseable date: {raw_date!r}"})
                continue

            raw_qty_str = row.get(col_map.get("quantity", ""), "0")
            quantity_source = _parse_quantity(raw_qty_str)
            if quantity_source is None:
                errors.append({"row": row_ref, "raw": dict(row), "error": f"Unparseable quantity: {raw_qty_str!r}"})
                continue

            sap_unit = row.get(col_map.get("unit", ""), "").strip()
            quantity_norm, unit_norm, unit_flags = _normalize_unit(quantity_source, sap_unit)

            category = _categorize(row, col_map)
            auto_flags = _auto_flags(quantity_norm, unit_norm, category) + unit_flags

            # Emission factor
            ef_info = EMISSION_FACTORS.get(category or "", {})
            ef_value = ef_info.get("factor")
            ef_source = ef_info.get("source", "")
            co2e = (quantity_norm * ef_value).quantize(Decimal("0.000001")) if ef_value else None

            if ef_value is None:
                auto_flags.append("MISSING_FACTOR")

            plant = row.get(col_map.get("plant", ""), "").strip()

            records.append(EmissionRecord(
                org=org,
                job=job,
                scope=1 if category in ("FUEL_STATIONARY", "FUEL_MOBILE") else
                      2 if category == "ELECTRICITY" else 3,
                category=category or "PROCUREMENT",
                period_start=parsed_date,
                period_end=parsed_date,
                facility_code=plant,
                facility_name="",            # plant lookup table not in scope
                country_code="",
                department=row.get(col_map.get("cost_center", ""), "").strip(),
                activity_quantity_source=quantity_source,
                activity_unit_source=sap_unit,
                activity_quantity=quantity_norm,
                activity_unit=unit_norm,
                co2e_kg=co2e,
                emission_factor=ef_value,
                emission_factor_source=ef_source,
                raw_data=dict(row),
                source_row_ref=row_ref,
                vendor=row.get(col_map.get("vendor", ""), "").strip(),
                description=row.get(col_map.get("description", ""), "").strip(),
                flag_reasons=auto_flags,
                status="FLAGGED" if auto_flags else "PENDING",
            ))

        except Exception as e:
            logger.exception(f"SAP parser error at {row_ref}")
            errors.append({"row": row_ref, "raw": dict(row), "error": str(e)})

    return {"records": records, "errors": errors, "metadata": metadata}
