import uuid
from django.db import models
from apps.core.models import Organization, User
from apps.ingestion.models import IngestionJob


class EmissionRecord(models.Model):
    """
    One normalized activity row. This is the canonical unit of work.

    Design choices defended in MODEL.md:

    1. We store both the original quantity+unit AND the normalized quantity+unit.
       The original is immutable (audit trail). The normalized is what we compute on.
       If an emission factor changes, we can recompute co2e_kg without touching the raw.

    2. co2e_kg is stored, not just derivable. Emission factors change between
       reporting frameworks (DEFRA vs EPA vs GHG Protocol). We record which factor
       was used at parse time. Analysts can override.

    3. period_start/period_end, not a single date. Utility bills and some SAP
       postings cover date ranges. Forcing a single date loses information.

    4. flag_reasons is a JSON list of strings, not a boolean. Multiple things can
       be suspicious about one row simultaneously (unit looks wrong AND value is
       outlier). Each auto-detected flag is a distinct string the UI can render.

    5. edit_history is append-only JSON. We deliberately did not build a separate
       AuditLog table for this prototype — the JSON array is sufficient for the
       analyst review use case. A production system would want a proper audit table
       with FK to User and indexed timestamps.
    """

    # -- Scope / Category taxonomy ------------------------------------------
    # GHG Protocol scope
    SCOPE_CHOICES = [(1, "Scope 1"), (2, "Scope 2"), (3, "Scope 3")]

    # Emission category — drives which emission factor column we look up
    CATEGORY_CHOICES = [
        # Scope 1
        ("FUEL_STATIONARY", "Stationary Combustion"),   # boilers, generators
        ("FUEL_MOBILE", "Mobile Combustion"),            # company vehicles
        # Scope 2
        ("ELECTRICITY", "Purchased Electricity"),
        # Scope 3
        ("TRAVEL_AIR", "Air Travel"),
        ("TRAVEL_HOTEL", "Hotel Stay"),
        ("TRAVEL_GROUND", "Ground Transport"),
        ("PROCUREMENT", "Purchased Goods & Services"),  # Scope 3 Cat 1
    ]

    # -- Review lifecycle ---------------------------------------------------
    STATUS_CHOICES = [
        ("PENDING", "Pending Review"),
        ("APPROVED", "Approved"),
        ("FLAGGED", "Flagged"),    # analyst has flagged; blocks locking
        ("REJECTED", "Rejected"), # excluded from totals
        ("LOCKED", "Locked for Audit"),  # immutable after this point
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="records")
    job = models.ForeignKey(IngestionJob, on_delete=models.CASCADE, related_name="records")

    # -- Classification -----------------------------------------------------
    scope = models.IntegerField(choices=SCOPE_CHOICES)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)

    # -- Activity period ----------------------------------------------------
    # Not a single date — billing periods and SAP posting ranges don't map to one day.
    period_start = models.DateField()
    period_end = models.DateField()

    # -- Entity / Location reference ----------------------------------------
    # We keep these as plain strings. A production system would FK to a
    # Facility table with coordinate data. For this prototype, the raw codes
    # are sufficient — analysts can see them.
    facility_code = models.CharField(max_length=100, blank=True)
    facility_name = models.CharField(max_length=255, blank=True)
    country_code = models.CharField(max_length=3, blank=True)  # ISO 3166-1 alpha-3
    department = models.CharField(max_length=255, blank=True)

    # -- Raw activity (source units, immutable) ----------------------------
    activity_quantity_source = models.DecimalField(max_digits=20, decimal_places=6)
    activity_unit_source = models.CharField(max_length=50)

    # -- Normalized activity (standard units per category) -----------------
    # Standard units by category:
    #   FUEL_*          → liters (L)
    #   ELECTRICITY     → kilowatt-hours (kWh)
    #   TRAVEL_AIR      → passenger-kilometers (pkm)
    #   TRAVEL_HOTEL    → room-nights (nights)
    #   TRAVEL_GROUND   → kilometers (km)
    #   PROCUREMENT     → USD (spend-based, until physical data available)
    activity_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    activity_unit = models.CharField(max_length=50)

    # -- Computed emissions ------------------------------------------------
    # kg CO2-equivalent. Null if we don't have an emission factor (e.g. novel
    # material group from SAP with no mapping yet).
    co2e_kg = models.DecimalField(max_digits=20, decimal_places=6, null=True, blank=True)
    emission_factor = models.DecimalField(
        max_digits=20, decimal_places=10, null=True, blank=True,
        help_text="kg CO2e per activity_unit"
    )
    emission_factor_source = models.CharField(
        max_length=255, blank=True,
        help_text="e.g. 'DEFRA 2023 v1.1', 'EPA eGRID 2022'"
    )

    # -- Source-of-truth tracking ------------------------------------------
    raw_data = models.JSONField(
        help_text="Exact original row from the source file. Never modified."
    )
    source_row_ref = models.CharField(
        max_length=255, blank=True,
        help_text="Row number or document ID in the source file"
    )
    # Vendor / counterparty name — relevant for travel and procurement
    vendor = models.CharField(max_length=255, blank=True)
    # Free-text description from source
    description = models.CharField(max_length=500, blank=True)

    # -- Auto-detected data quality flags ----------------------------------
    # Each string is a short flag code the UI can render with an explanation.
    # Examples: "UNIT_UNUSUAL", "VALUE_OUTLIER", "PERIOD_GAP", "MISSING_FACTOR"
    flag_reasons = models.JSONField(default=list)

    # -- Review ------------------------------------------------------------
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_records"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    # -- Edit tracking -----------------------------------------------------
    # Analysts can correct normalized_quantity or co2e_kg if a unit was mis-parsed.
    # We track every change here. JSON is append-only; nothing is ever removed.
    # Format: [{field, old_value, new_value, edited_by_username, edited_at}]
    is_manually_edited = models.BooleanField(default=False)
    edit_history = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start"]
        indexes = [
            models.Index(fields=["org", "status"]),
            models.Index(fields=["org", "scope"]),
            models.Index(fields=["org", "category"]),
            models.Index(fields=["job"]),
        ]

    def __str__(self):
        return f"{self.category} | {self.period_start} | {self.activity_quantity} {self.activity_unit}"
