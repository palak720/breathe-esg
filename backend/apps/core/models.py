import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser


class Organization(models.Model):
    """
    Top-level tenant. Every row in the system belongs to exactly one org.
    slug is used in API paths so URLs are human-readable without exposing UUID.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    Extends Django's user with org membership and role.
    Role drives what the UI exposes: analysts can approve/flag,
    admins can lock records and manage ingestion.
    We keep this simple — a user belongs to one org.
    In a real product, some users (Breathe staff) span orgs.
    """
    ROLES = [
        ("ANALYST", "Analyst"),       # review, approve, flag
        ("ADMIN", "Admin"),           # all of the above + lock for audit, manage ingestion
        ("AUDITOR", "Auditor"),       # read-only, sees locked records only
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True,
        related_name="members"
    )
    role = models.CharField(max_length=20, choices=ROLES, default="ANALYST")

    def __str__(self):
        return f"{self.username} ({self.org})"
