"""Small helpers shared by every app."""
import json

from django.utils import timezone

DT_FORMAT = "%Y-%m-%d %H:%M:%S"


def fmt_dt(value):
    """Aware datetime -> machine-readable Bangladesh-local 'YYYY-MM-DD HH:MM:SS'."""
    return timezone.localtime(value).strftime(DT_FORMAT) if value else ""


def fmt_dt_ampm(value):
    """Aware datetime -> human-readable Bangladesh-local date/time with AM/PM."""
    return timezone.localtime(value).strftime("%Y-%m-%d %I:%M:%S %p") if value else ""


def csv_safe(value):
    """A cell for a CSV file: text that a spreadsheet would run as a formula (=, +, -, @) is neutralised."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def parse_json(request):
    """JSON body of a request as a dict; anything invalid becomes {}."""
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
