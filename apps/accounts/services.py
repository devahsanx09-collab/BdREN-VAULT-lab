"""Accounts - business layer: sign-in checks, lockout, password rules and every change to web users."""
import re

from django.contrib.auth.hashers import check_password as check_hash
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.core.api import ApiError

from . import selectors
from .models import ROLE_LEVEL, Role, User

MAX_FAILS, LOCK_SECONDS = 5, 300
_DUMMY_HASH = make_password("not-a-real-password")      # keeps timing equal for unknown usernames
MAX_FAILS_PER_IP = 20          # wrong passwords from ONE address across all usernames (password spraying)


def check_username(username):
    """Error text for an invalid username, or '' when it is fine."""
    ok = re.fullmatch(r"[A-Za-z0-9._-]{3,32}", username or "")
    return "" if ok else "Username must be 3-32 characters: letters, numbers, dot, dash or underscore"


def check_password(password, user=None):
    """Error text for a weak password, or '' when it is fine.

    Rules (config/settings.py AUTH_PASSWORD_VALIDATORS): at least 12 characters, not a commonly used
    password, not all digits, not similar to the username. Maximum 128 characters.
    """
    password = password or ""
    if len(password) > 128:
        return "Password is too long"
    try:
        validate_password(password, user=user)
    except ValidationError as e:
        return " ".join(e.messages)
    return ""


def create_user(username, password, role):
    """Create a user; raises ApiError(409) when the name is taken (ignoring case)."""
    if User.objects.filter(username__iexact=username).exists():
        raise ApiError(409, "That username already exists")
    try:
        return User.objects.create_user(username=username, password=password, role=role)
    except IntegrityError:
        raise ApiError(409, "That username already exists")


def check_credentials(username, password):
    """(user, password_ok) for a sign-in attempt. Unknown users take as long as known ones (no username probing)."""
    user = selectors.find_user(username)
    ok = check_hash(password, user.password if user else _DUMMY_HASH) and user is not None
    return user, ok


def create_validated_user(username, password, role):
    """Add a web user after checking the name, password strength and role."""
    error = check_username(username) or check_password(password) or ("" if role in ROLE_LEVEL else "Invalid role")
    if error:
        raise ApiError(400, error)
    return create_user(username, password, role)


def change_own_password(user, current, new):
    """Change the signed-in user's password (the view then keeps this session and drops the others)."""
    if not isinstance(current, str) or not isinstance(new, str):
        raise ApiError(400, "Enter the current and the new password")
    if not user.check_password(current):
        raise ApiError(400, "Current password is incorrect")
    error = check_password(new, user)
    if error:
        raise ApiError(400, error)
    user.set_password(new)
    user.save()


def update_user(target, acting_user, data):
    """Change role / active flag / password. You cannot demote yourself or remove the last administrator."""
    role = data.get("role", target.role)
    active = bool(data.get("active", target.is_active))
    if role not in ROLE_LEVEL:
        raise ApiError(400, "Invalid role")
    if target.pk == acting_user.pk and (role != target.role or not active):
        raise ApiError(400, "You cannot change your own role or disable your own account")
    if target.role == Role.ADMIN and target.is_active and (role != Role.ADMIN or not active) \
            and selectors.other_admins(target.pk) == 0:
        raise ApiError(400, "At least one active administrator is required")
    password = data.get("password") or ""
    if password and check_password(password):
        raise ApiError(400, check_password(password))
    target.role, target.is_active = role, active
    if password:
        target.set_password(password)
    target.save()


def delete_user(target, acting_user):
    if target.pk == acting_user.pk:
        raise ApiError(400, "You cannot delete your own account")
    if target.role == Role.ADMIN and target.is_active and selectors.other_admins(target.pk) == 0:
        raise ApiError(400, "At least one active administrator is required")
    target.delete()


# ---------- login lockout: 5 wrong passwords lock that client + username for 5 minutes ----------
def _lock_key(ip, username):
    # the name comes straight from the sign-in form: keep the cache key short and free of odd characters
    name = re.sub(r"[^a-z0-9._@-]", "_", username.lower())[:64]
    return f"login-fail:{ip}:{name}"


def is_locked(ip, username):
    return (cache.get(_lock_key(ip, username) + ":locked") is not None
            or cache.get(f"login-ip-locked:{ip}") is not None)


def register_failure(ip, username):
    ip_key = f"login-ip-fail:{ip}"
    ip_count = cache.get(ip_key, 0) + 1
    if ip_count >= MAX_FAILS_PER_IP:
        cache.set(f"login-ip-locked:{ip}", 1, LOCK_SECONDS)
        cache.delete(ip_key)
    else:
        cache.set(ip_key, ip_count, LOCK_SECONDS)
    key = _lock_key(ip, username)
    count = cache.get(key, 0) + 1
    if count >= MAX_FAILS:
        cache.set(key + ":locked", 1, LOCK_SECONDS)
        cache.delete(key)
    else:
        cache.set(key, count, LOCK_SECONDS)


def clear_failures(ip, username):
    cache.delete_many([_lock_key(ip, username), _lock_key(ip, username) + ":locked"])
