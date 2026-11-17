from django.contrib import admin

from .models import Device


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("ip", "name", "device_type", "last_status", "last_run")
    search_fields = ("ip", "name")
    exclude = ("password", "secret")          # encrypted values are never shown in the admin
