# MODEL.md — Data Model

## Overview

The model is built around one core insight: **an emission record has two separate lives** — what the source gave us (immutable, for audit) and what we computed from it (normalized, reviewable, correctable). Conflating these is the most common mistake in ESG data pipelines.

---

## Entity Map

```
Organization (tenant)
    │
    ├── User (role: ANALYST | ADMIN | AUDITOR)
    │
    ├── IngestionJob  ──────────────────────────────────────────┐
    │       │                                                   │
    │       └── ParseError (rows that failed to parse)         │
    │                                                           │
    └── EmissionRecord ◄─────────────────────────────────────┘
```

---

## Multi-Tenancy

Every table that contains business data has a FK to `Organization`. Queries are always filtered by `request.user.org` before anything else — there is no path in the API to reach another tenant's data.

`User.org` is a single FK. One user belongs to one org. This is a deliberate simplification: in the real product, Breathe staff accounts would span orgs. We noted this in TRADEOFFS.md.

We use UUID primary keys everywhere. This prevents enumeration attacks (e.g. `/api/records/43/` leaking that record 42 exists) and makes multi-region sharding easier later.

---

## IngestionJob

Represents one import run. Key decisions:

**Why track row counts?**
A file with 500 rows that produces 420 records and 80 errors is a red flag — the analyst needs to know that 16% of the source was dropped. Without explicit counts, this gap is invisible.

**Why store the raw file permanently?**
Audit requirement. If an auditor asks "what exactly did your SAP system say about this transaction in January", the answer has to be the actual file, not a reconstructed summary. In production this would be S3 with versioning. For the prototype, Django's MEDIA_ROOT.

**Why `metadata` as JSON?**
Each parser discovers different things about its file (encoding, detected language, column mapping). Forcing a fixed schema for this would mean three separate tables or a lot of nullable columns. JSON is honest about the uncertainty here.

---

## EmissionRecord

The canonical unit of work. Every field choice is justified below.

### Scope / Category

```python
scope = IntegerField(choices=[1, 2, 3])          # GHG Protocol scope
category = CharField(choices=CATEGORY_CHOICES)    # drives emission factor lookup
```

Scope and category are stored separately because they serve different purposes:
- **Scope** is for regulatory reporting (CDP, TCFD)
- **Category** is operational — it determines which emission factor column to use

They are redundant (scope is determinable from category) but storing both prevents a join on every report query.

### Period

```python
period_start = DateField()
period_end   = DateField()
```

**Not a single date.** Utility bills run meter-read to meter-read (e.g. Feb 17 to Mar 17). SAP postings cover a fiscal period, not a calendar day. Forcing a single date means either losing information or making an arbitrary choice about which date to use. We keep both.

### Activity — Two Representations

```python
# Source (immutable — exactly what the file said)
activity_quantity_source = DecimalField()
activity_unit_source     = CharField()   # e.g. "TO", "GAL", "GAL"

# Normalized (computed by parser, correctable by analyst)
activity_quantity = DecimalField()
activity_unit     = CharField()   # standard unit for category: L, kWh, pkm, nights, km
```

The source values never change. The normalized values can be corrected by an analyst if the parser guessed wrong (e.g. misidentified gallons as liters). Every correction is appended to `edit_history`.

Standard units by category:
| Category | Standard Unit | Rationale |
|---|---|---|
| FUEL_STATIONARY | L (liters) | Most fuel emission factors are per-liter |
| FUEL_MOBILE | L (liters) | Same |
| ELECTRICITY | kWh | Universal electricity unit |
| TRAVEL_AIR | pkm (passenger-km) | DEFRA/GHG Protocol standard |
| TRAVEL_HOTEL | nights | DEFRA hotel factor is per room-night |
| TRAVEL_GROUND | km | Ground transport factors are per-km |
| PROCUREMENT | USD | Spend-based method — no physical unit available |

### Emissions

```python
co2e_kg              = DecimalField(null=True)   # null if no factor available
emission_factor      = DecimalField(null=True)   # kg CO2e per activity_unit
emission_factor_source = CharField()             # "DEFRA 2023 v1.1"
```

**Why store `co2e_kg` rather than always computing it?**
Emission factors get updated annually. If we only store the factor and always derive CO2e at query time, a factor update silently changes historical figures — which breaks audit. We store the CO2e as computed at ingestion time. If a factor is corrected, the analyst can trigger a recompute and the change is recorded in `edit_history`.

**Why `null=True` on `co2e_kg`?**
Some rows genuinely cannot be computed: procurement rows with no spend-based factor mapped, ground transport with no distance, flights with unknown airport codes. Making CO2e nullable is honest. The alternative — imputing zeros — is worse than missing data for audit purposes.

### Source-of-Truth Tracking

```python
raw_data       = JSONField()    # exact original row, never modified
source_row_ref = CharField()    # "row 47" or document ID in source file
job            = ForeignKey(IngestionJob)
```

Together these give a complete answer to "where did this number come from":
- Which upload run → `job`
- Which row in that file → `source_row_ref`
- What that row said → `raw_data`

### Flag System

```python
flag_reasons = JSONField(default=list)  # ["UNIT_UNKNOWN", "VALUE_OUTLIER_HIGH"]
```

**Why a list of strings, not a boolean?**
Multiple things can be wrong with one row simultaneously. A row might have an unusual unit AND an outlier value. A boolean `is_flagged` collapses this to one bit. The list lets the UI explain each issue separately.

Auto-detected flags (set by parsers at ingestion time):
- `UNIT_UNKNOWN` — SAP unit code not in mapping table
- `UNIT_PIECE_UNCONVERTIBLE` — unit is pieces, can't convert to mass/volume
- `VALUE_ZERO_OR_NEGATIVE` — quantity ≤ 0
- `VALUE_OUTLIER_HIGH` — quantity above threshold for category
- `CATEGORY_UNMAPPED` — GL account and material group both unknown
- `MISSING_FACTOR` — no emission factor for this category/unit combination
- `PERIOD_LONG_ESTIMATED_OR_COMBINED` — billing period > 35 days
- `PERIOD_SHORT_CHECK_READ` — billing period < 25 days
- `CLASS_ASSUMED_ECONOMY` — no cabin class in travel data, assumed Economy
- `AIRPORT_UNKNOWN:<code>` — IATA code not in lookup table
- `MISSING_DISTANCE` — ground transport with no distance field

### Review Lifecycle

```
PENDING → APPROVED → LOCKED
        → FLAGGED  → APPROVED → LOCKED
        → REJECTED  (excluded from totals)
```

```python
status       = CharField(choices=STATUS_CHOICES, default="PENDING")
reviewed_by  = ForeignKey(User, null=True)
reviewed_at  = DateTimeField(null=True)
locked_at    = DateTimeField(null=True)
```

LOCKED is terminal. Once a record is locked for audit, the API rejects all modifications. The lock timestamp is separate from `reviewed_at` because they're different events: an analyst approves, an admin locks a batch later.

### Edit / Audit Trail

```python
is_manually_edited = BooleanField(default=False)
edit_history       = JSONField(default=list)
```

Every field change is appended as:
```json
{
  "field": "activity_quantity",
  "old_value": "8500.000000",
  "new_value": "8.500000",
  "edited_by": "sarah.analyst",
  "edited_at": "2024-03-15T14:22:01Z"
}
```

The list is append-only. Nothing is ever removed. This is sufficient for the analyst review use case. A production system with regulatory requirements would use a proper audit table with FK constraints and database-level immutability.

---

## Database Indexes

```python
indexes = [
    Index(fields=["org", "status"]),    # dashboard filter
    Index(fields=["org", "scope"]),     # scope breakdown
    Index(fields=["org", "category"]),  # category breakdown
    Index(fields=["job"]),              # job detail view
]
```

The most common query is `WHERE org_id = X AND status = Y`. The compound index on `(org, status)` covers this without a full table scan.

---

## What This Model Deliberately Does Not Handle

1. **Facility master data** — `facility_code` is a plain string (e.g. "DE01" from SAP). A production model would FK to a `Facility` table with coordinates, grid region, and country for location-based emission factors.

2. **Currency normalization** — `net_value` from SAP is stored in raw_data only. Spend-based procurement emission factors would need USD normalization at a specific exchange rate date.

3. **Supplier-specific factors** — Scope 3 Category 1 procurement ideally uses supplier-disclosed factors. We fall back to spend-based, which is noted in TRADEOFFS.md.
