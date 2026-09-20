"""Django admin registration for the accounts app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Admin for the custom user model: Django's fields plus role/department."""

    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "role",
        "department",
        "is_active",
        "is_staff",
    )
    list_filter = ("role", "department", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email", "first_name", "last_name")
    list_select_related = ("department",)

    fieldsets = UserAdmin.fieldsets + (
        ("Application access", {"fields": ("role", "department")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Application access", {"fields": ("role", "department")}),
    )
