import uuid
from django.db import models
from apps.core.models import Organization, User


class IngestionJob(models.Model):
    """
    Represents one import run. Immutable once created — we never modify
    what was ingested, only the EmissionRecords derived from it.

    source_type maps to which parser runs. We track row counts so analysts
    can spot if a file was partially parsed without digging into errors.
    """
    SOURCE_TYPES = [
        ("SAP_FLAT_FILE", "SAP Flat File (SE16/ALV CSV)"),
        ("UTILITY_CSV", "Utility Portal CSV"),
        ("TRAVEL_CSV", "Travel Platform CSV (Concur/Navan)"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("COMPLETE", "Complete"),
        ("FAILED", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="jobs")
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    # The raw file. We keep it forever — critical for audit.
    # In production this would be S3; for the prototype, local MEDIA_ROOT.
    uploaded_file = models.FileField(upload_to="ingestion/%Y/%m/")
    original_filename = models.CharField(max_length=500, blank=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="jobs_uploaded"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    # Parse stats
    row_count_total = models.IntegerField(default=0)
    row_count_parsed = models.IntegerField(default=0)
    row_count_failed = models.IntegerField(default=0)

    # Parser-detected metadata: encoding guesses, detected column map, warnings
    metadata = models.JSONField(default=dict)
    error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.source_type} @ {self.uploaded_at:%Y-%m-%d} ({self.org})"


class ParseError(models.Model):
    """
    A row in the source file that failed to parse. Surfaced in the UI so
    analysts can decide whether to fix the source and re-ingest or note the gap.
    """
    job = models.ForeignKey(IngestionJob, on_delete=models.CASCADE, related_name="parse_errors")
    row_ref = models.CharField(max_length=100)    # e.g. "row 47" or source doc ID
    raw_content = models.TextField()              # the raw row as a string — for debugging
    error_message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["row_ref"]
