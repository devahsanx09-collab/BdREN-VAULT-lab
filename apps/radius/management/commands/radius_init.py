from django.core.management.base import BaseCommand
from django.db import connections, models

from apps.radius.models import AuditLog, NasRole, UserDevice, UserGrant
from apps.radius.router import DB
from apps.radius.services import convert_legacy_limits, normalize_roles, seed_groups


class Command(BaseCommand):
    help = ("Prepare an existing FreeRADIUS database for the RADIUS Admin pages: create the panel's "
            "tables when they are missing (audit log, per-switch login limits, device types), convert "
            "old per-switch limits and seed the access-level groups. Safe to run again.")

    def handle(self, *args, **opts):
        connection = connections[DB]
        existing = connection.introspection.table_names()
        for model in (AuditLog, UserDevice, NasRole, UserGrant):
            table = model._meta.db_table
            if table in existing:
                self.stdout.write(f"{table}: already there.")
            else:
                with connection.schema_editor() as editor:
                    editor.create_model(model)
                self.stdout.write(self.style.SUCCESS(f"{table}: created."))
        self.widen_role_column(connection)
        fixed = normalize_roles()
        if fixed:
            self.stdout.write(self.style.SUCCESS(f"Device types: {fixed} row(s) set to one spelling."))
        converted = convert_legacy_limits()
        if converted:
            self.stdout.write(self.style.SUCCESS(
                "Per-switch limits moved out of radcheck for: " + ", ".join(sorted(set(converted)))))
        seed_groups()
        self.stdout.write(self.style.SUCCESS("Access-level groups seeded."))

    def widen_role_column(self, connection):
        """dbms_nas_role.role was created 30 characters wide by the first build that had it; it is 50 now."""
        field = NasRole._meta.get_field("role")
        with connection.cursor() as cursor:
            columns = connection.introspection.get_table_description(cursor, NasRole._meta.db_table)
        size = next((c.internal_size for c in columns if c.name == "role"), None)
        if size and size < field.max_length:
            old = models.CharField(max_length=size, default="Other")
            old.set_attributes_from_name("role")
            old.model = NasRole
            with connection.schema_editor() as editor:
                editor.alter_field(NasRole, old, field)
            self.stdout.write(self.style.SUCCESS(f"dbms_nas_role.role: widened from {size} to {field.max_length}."))
