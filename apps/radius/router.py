"""Sends every RADIUS table to the second database that FreeRADIUS also reads.

    default  -> VAULT tables (devices, backups, users, sessions ...)
    radius   -> radcheck, radusergroup, radgroupreply, nas, radpostauth, radius_auditlog
"""
APP = "radius"
DB = "radius"


class RadiusRouter:
    def db_for_read(self, model, **hints):
        return DB if model._meta.app_label == APP else None

    def db_for_write(self, model, **hints):
        return DB if model._meta.app_label == APP else None

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, **hints):
        if app_label == APP:
            return db == DB          # RADIUS tables never go into the backup database
        if db == DB:
            return False             # and nothing else goes into the RADIUS database
        return None
