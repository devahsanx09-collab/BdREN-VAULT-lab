from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


class Role(models.TextChoices):
    VIEWER = "viewer", "Viewer"          # reads everything
    OPERATOR = "operator", "Operator"    # + adds/edits devices and runs backups
    ADMIN = "admin", "Administrator"     # + deletes, manages users and settings


ROLE_LEVEL = {Role.VIEWER: 1, Role.OPERATOR: 2, Role.ADMIN: 3}


class User(AbstractUser):
    """Django's user plus a role. User names are unique ignoring upper/lower case."""
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        constraints = [models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique")]

    def has_role(self, minimum):
        """True when this user's role is at least `minimum` ('viewer', 'operator' or 'admin')."""
        return ROLE_LEVEL[self.role] >= ROLE_LEVEL[minimum]

    def save(self, *args, **kwargs):
        if self.is_superuser:                # users made with `createsuperuser` are administrators
            self.role = Role.ADMIN
        super().save(*args, **kwargs)
