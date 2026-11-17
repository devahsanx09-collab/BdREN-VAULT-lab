from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class DeviceBackupUserAdmin(UserAdmin):
    list_display = ("username", "role", "is_active", "last_login")
    fieldsets = UserAdmin.fieldsets + (("VAULT", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("VAULT", {"fields": ("role",)}),)
