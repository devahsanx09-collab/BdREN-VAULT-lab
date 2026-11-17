from django.urls import path

from . import views

urlpatterns = [
    path("api/devices", views.devices, name="api-devices"),
    path("api/devices/delete", views.bulk_delete, name="api-devices-delete"),
    path("api/devices/import", views.import_devices, name="api-devices-import"),
    path("api/devices/export.csv", views.export_inventory, name="api-devices-export"),
    path("api/devices/<int:pk>", views.device_detail, name="api-device-detail"),
    path("api/credentials", views.credentials, name="api-credentials"),
    path("api/credentials/password", views.credential_password, name="api-credential-password"),
    path("api/credentials/apply", views.apply_credentials, name="api-credentials-apply"),
]
