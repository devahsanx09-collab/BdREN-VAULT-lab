from django.db import models


class RadCheck(models.Model):
    username = models.CharField(max_length=64, db_index=True)
    attribute = models.CharField(max_length=64)
    op = models.CharField(max_length=2, default=":=")
    value = models.CharField(max_length=253)

    class Meta:
        managed = False
        db_table = "radcheck"


class RadUserGroup(models.Model):
    username = models.CharField(max_length=64, db_index=True)
    groupname = models.CharField(max_length=64)
    priority = models.IntegerField(default=1)

    class Meta:
        managed = False
        db_table = "radusergroup"


class RadGroupReply(models.Model):
    groupname = models.CharField(max_length=64, db_index=True)
    attribute = models.CharField(max_length=64)
    op = models.CharField(max_length=2, default="=")
    value = models.CharField(max_length=253)

    class Meta:
        managed = False
        db_table = "radgroupreply"


class Nas(models.Model):
    nasname = models.CharField(max_length=128)
    shortname = models.CharField(max_length=32)
    type = models.CharField(max_length=30, default="other")
    secret = models.CharField(max_length=60)
    description = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        managed = False
        db_table = "nas"


class RadPostAuth(models.Model):
    username = models.CharField(max_length=64)
    reply = models.CharField(max_length=32)
    authdate = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "radpostauth"


# A dbms_user_nas row FreeRADIUS can never match (Packet-Src-IP-Address is always an address). Written when a
# user is limited to device types that have no device yet: without it the user would have NO rows, which the
# dbms_device_limit policy reads as "every device".
NO_DEVICE = "none"

# Starting suggestions for a NAS client's network role (free text, not a fixed list - see NasRole below).
ROLE_SUGGESTIONS = ["Core router", "Distribution router", "Core switch", "Access switch", "Other"]
ROLE_MAX_LEN = 50


def clean_role(role):
    """A device type is free text: trimmed, capped, "" falls back to "Other"."""
    role = (role or "").strip()[:ROLE_MAX_LEN]
    return role or "Other"


class NasRole(models.Model):
    """The network role of one NAS client ("Core router", "Distribution router", ...), keyed by its
    address. FreeRADIUS never reads this: it only groups devices in the admin panel so a RADIUS user
    can be given access to a whole role (every core router, say) instead of picking switches one by one."""
    nasname = models.CharField(max_length=128, unique=True)
    role = models.CharField(max_length=ROLE_MAX_LEN, default="Other")

    class Meta:
        db_table = "dbms_nas_role"


class UserGrant(models.Model):
    """What an administrator chose under "Where this user can log in": a device type ("Access switch")
    or one device address. The source of truth for the user's access; dbms_user_nas (UserDevice) is the
    list of addresses FreeRADIUS checks, recalculated from these rows whenever a user or a device changes,
    so a type grant also covers devices of that type added later."""
    TYPE, DEVICE = "type", "device"
    username = models.CharField(max_length=64, db_index=True)
    kind = models.CharField(max_length=10)
    value = models.CharField(max_length=128)

    class Meta:
        db_table = "dbms_user_grant"
        unique_together = [("username", "kind", "value")]


class UserDevice(models.Model):
    """"This RADIUS user may log in on this switch only". No rows for a user = every switch.

    FreeRADIUS reads it through the dbms_device_limit policy (deploy/radius/dbms_device_limit),
    which compares `nasname` with the address the request came from (Packet-Src-IP-Address).
    """
    username = models.CharField(max_length=64, db_index=True)
    nasname = models.CharField(max_length=128)

    class Meta:
        db_table = "dbms_user_nas"
        unique_together = [("username", "nasname")]


class AuditLog(models.Model):
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=40)
    target = models.CharField(max_length=200, blank=True)
    detail = models.CharField(max_length=300, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
