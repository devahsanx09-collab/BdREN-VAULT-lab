"""The page registry: every screen of the web application, in menu order.

One entry here gives a page its URL, its place in the side menu, its title and breadcrumb, the template that
holds its content and the minimum role that may open it. Adding a page:

  1. add a Page(...) below
  2. create its template: {% extends "base.html" %} {% block content %} ... {% endblock %}
  3. add its loader to PAGE_INIT in static/js/core/start.js (the function that fills the page with data)

The JSON API keeps its own role checks (apps/core/api.py); the role here only decides who sees the menu item
and who may open the page.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    key: str            # used by JS (body[data-page]) and by the menu
    path: str           # URL without the leading slash
    title: str          # menu label, browser tab title and breadcrumb
    group: str          # menu section heading and first breadcrumb part
    template: str       # template that extends base.html
    icon: str           # templates/components/icons/<icon>.svg
    role: str = "viewer"   # viewer < operator < admin
    submenu: str = ""   # pages with the same submenu are shown in one drop-down (RADIUS / AAA)


PAGES = [
    Page("dashboard", "dashboard", "Dashboard", "Overview", "dashboard/index.html", "dashboard"),
    Page("devices", "devices", "Device Inventory", "Inventory", "devices/index.html", "devices"),
    Page("backups", "backups", "Configuration Backups", "Configuration", "backups/index.html", "backups"),
    Page("reports", "reports", "Change Reports", "Configuration", "reports/index.html", "reports"),
    Page("jobs", "jobs", "Backup Jobs", "Operations", "jobs/index.html", "jobs"),
    Page("logs", "logs", "Activity Logs", "Operations", "logs/index.html", "logs"),
    Page("radius-users", "radius/users", "AAA Users", "Access Control", "radius/users.html", "aaa-users",
         role="admin", submenu="RADIUS / AAA"),
    Page("radius-nas", "radius/nas", "NAS Clients", "Access Control", "radius/nas.html", "nas",
         role="admin", submenu="RADIUS / AAA"),
    Page("radius-audit", "radius/audit", "Authentication Audit", "Access Control", "radius/audit.html", "audit",
         role="admin", submenu="RADIUS / AAA"),
    Page("radius-setup", "radius/setup", "Device Setup", "Access Control", "radius/setup.html", "setup",
         role="admin", submenu="RADIUS / AAA"),
    Page("users", "users", "User Management", "Administration", "accounts/users.html", "users", role="admin"),
    Page("settings", "settings", "System Settings", "Administration", "settings/index.html", "settings",
         role="admin"),
]
BY_KEY = {p.key: p for p in PAGES}

# Not in the menu: one device's own backup page (/devices/<id>), shown under "Device Inventory".
DEVICE_PAGE = Page("device", "devices/<id>", "Device details", "Inventory", "devices/detail.html", "devices")

HOME = "dashboard"


def url_of(page):
    return "/" + page.path


def menu_for(user):
    """The side menu for this user: [{"group": str, "items": [page | {"submenu": str, "pages": [...]}]}]."""
    groups = []
    for page in PAGES:
        if not user.has_role(page.role):
            continue
        if not groups or groups[-1]["group"] != page.group:
            groups.append({"group": page.group, "items": []})
        items = groups[-1]["items"]
        if page.submenu:
            if not items or not isinstance(items[-1], dict) or items[-1].get("submenu") != page.submenu:
                items.append({"submenu": page.submenu, "icon": "shield", "pages": []})
            items[-1]["pages"].append(page)
        else:
            items.append(page)
    return groups


def page_urls():
    """{key: url} for every page, handed to JavaScript so links are never hard-coded twice."""
    return {p.key: url_of(p) for p in PAGES}
