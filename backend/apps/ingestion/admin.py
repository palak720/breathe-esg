from django.contrib import admin
from .models import IngestionJob, ParseError


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display = ["id", "org", "source_type", "status", "uploaded_at", "row_count_parsed", "row_count_failed"]
    list_filter = ["source_type", "status", "org"]
    readonly_fields = ["id", "uploaded_at", "processed_at", "metadata"]


@admin.register(ParseError)
class ParseErrorAdmin(admin.ModelAdmin):
    list_display = ["job", "row_ref", "error_message", "created_at"]
    list_filter = ["job__source_type"]
