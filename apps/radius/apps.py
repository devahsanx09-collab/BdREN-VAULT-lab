from django.apps import AppConfig


class RadiusConfig(AppConfig):
    name = "apps.radius"
    label = "radius"            # keeps the original table name radius_auditlog and migration history
    verbose_name = "RADIUS Admin (FreeRADIUS users, devices, audit)"
