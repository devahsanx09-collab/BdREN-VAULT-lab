"""Audit trail: the one place that writes and reads the AuditEvent table.

Every app records actions with record_audit(request, ...) and reads the history through the functions below;
no other module queries AuditEvent directly. Never pass passwords or raw device configurations here.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import AuditEvent

SIGNIN_ACTIONS = {"login.success": "Signed in", "login.failed": "Failed", "logout": "Signed out"}


def record_audit(request, action, target="", detail=""):
    user = getattr(request, "user", None)
    # Trust REMOTE_ADDR only; forwarded headers may be client-controlled unless proxy trust is configured.
    addr = request.META.get("REMOTE_ADDR") or None
    if addr and len(addr) > 45:
        addr = None
    AuditEvent.objects.create(
        username=(getattr(user, "username", "") or "")[:150],
        action=str(action)[:80], target=str(target)[:255], detail=str(detail)[:2000],
        remote_addr=addr,
    )


# ---------- reads ----------
def recent_events(limit):
    """Newest audit entries (Activity Logs -> administrative audit trail)."""
    return AuditEvent.objects.all()[:limit]


def last_signin(username):
    """The newest successful sign-in of this user, or None."""
    return AuditEvent.objects.filter(username=username, action="login.success").order_by("-id").first()


def signin_events(account="", result_action="", q="", limit=500):
    """Sign-ins, failed attempts and sign-outs, newest first, filtered like the Sign-in history panel."""
    rows = AuditEvent.objects.filter(action__in=SIGNIN_ACTIONS)
    if account:
        rows = rows.filter(target__iexact=account)
    if result_action:
        rows = rows.filter(action=result_action)
    if q:
        rows = rows.filter(Q(target__icontains=q) | Q(remote_addr__icontains=q) | Q(detail__icontains=q))
    return rows.order_by("-id")[:limit]


def signin_summary(hours=24):
    """{signins_24h, failed_24h, accounts_24h} for the Sign-in history cards."""
    recent = AuditEvent.objects.filter(action__in=SIGNIN_ACTIONS, ts__gte=timezone.now() - timedelta(hours=hours))
    return {"signins_24h": recent.filter(action="login.success").count(),
            "failed_24h": recent.filter(action="login.failed").count(),
            "accounts_24h": recent.filter(action="login.success").values("target").distinct().count()}
