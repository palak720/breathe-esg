from django.contrib import admin
from .models import EmissionRecord


@admin.register(EmissionRecord)
class EmissionRecordAdmin(admin.ModelAdmin):
    list_display = ["id", "org", "scope", "category", "period_start", "activity_quantity", "activity_unit", "co2e_kg", "status"]
    list_filter = ["scope", "category", "status", "org"]
    readonly_fields = ["id", "org", "job", "raw_data", "edit_history", "created_at", "updated_at"]
    search_fields = ["vendor", "description", "facility_code"]
