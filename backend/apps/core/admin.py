from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Organization, User


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "created_at"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "org", "role", "is_staff"]
    list_filter = ["role", "org"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Breathe ESG", {"fields": ("org", "role")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Breathe ESG", {"fields": ("org", "role")}),
    )
