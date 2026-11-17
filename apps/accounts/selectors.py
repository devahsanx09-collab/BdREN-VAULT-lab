"""Accounts - read layer: web users and the sign-in history."""
from apps.backups import audit
from apps.core.api import ApiError
from apps.core.utils import fmt_dt

from .models import Role, User


def any_user_exists():
    """False only before the first administrator is created (first-run setup)."""
    return User.objects.exists()


def find_user(username):
    """The user with this name, ignoring upper / lower case, or None."""
    return User.objects.filter(username__iexact=username).first()


def get_user(pk):
    user = User.objects.filter(pk=pk).first()
    if not user:
        raise ApiError(404, "User not found")
    return user


def other_admins(user_id):
    """Number of OTHER active administrators (at least one must always remain)."""
    return User.objects.filter(role=Role.ADMIN, is_active=True).exclude(pk=user_id).count()


ONLINE_SECONDS = 5 * 60      # a signed-in browser asks the server more often than this (live refresh)


def online_user_ids():
    """Ids of the users who are signed in right now: they have a session that has not been signed out or
    expired AND was used in the last few minutes. (A closed browser stops asking, so its user drops out
    after ONLINE_SECONDS although the session itself lives until the idle time-out.)"""
    from datetime import timedelta

    from django.conf import settings
    from django.contrib.sessions.models import Session
    from django.utils import timezone
    now, online = timezone.now(), set()
    # every request moves expire_date to "now + session age", so it tells when the session was last used
    used_after = now + timedelta(seconds=settings.SESSION_COOKIE_AGE - ONLINE_SECONDS)
    for session in Session.objects.filter(expire_date__gt=used_after):
        try:
            user_id = session.get_decoded().get("_auth_user_id")
        except Exception:
            continue
        if user_id:
            online.add(str(user_id))
    return online


def user_row(user, online=None):
    """User as sent to the browser (never the password), including last sign-in metadata.
    `active` = the account is enabled; `online` = signed in right now."""
    last_event = audit.last_signin(user.username)
    online = online_user_ids() if online is None else online
    return {"id": user.id, "username": user.username, "role": user.role, "active": user.is_active,
            "online": user.is_active and str(user.pk) in online,
            "created": fmt_dt(user.date_joined), "last_login": fmt_dt(user.last_login),
            "last_login_ip": last_event.remote_addr if last_event else ""}


def user_rows():
    online = online_user_ids()
    return [user_row(u, online) for u in User.objects.order_by("username")]


def signin_history(account="", result="", q="", limit=500):
    """Rows for the Sign-in history table. result = "Signed in" | "Failed" | "Signed out" | ""."""
    wanted = {v: k for k, v in audit.SIGNIN_ACTIONS.items()}.get(result or "", "")
    out = []
    for e in audit.signin_events(account, wanted, q, limit):
        reason, _, browser = (e.detail or "").partition(" · ")
        out.append({"ts": fmt_dt(e.ts), "account": e.target or e.username, "result": audit.SIGNIN_ACTIONS[e.action],
                    "reason": reason if e.action == "login.failed" else ("Inactivity" if "inactivity" in reason else ""),
                    "ip": e.remote_addr or "", "browser": browser})
    return out
