# Contributing

How to make the common changes without breaking anything. Background: [ARCHITECTURE.md](ARCHITECTURE.md).

## Run it on your computer

VAULT needs MySQL 8 / MariaDB 10.6+. Create a database as in the README
("Database"), put `DBMS_DB_*` in `.env`, then:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip
python manage.py migrate
python manage.py createsuperuser
python manage.py serve --port 8000
```

Open http://127.0.0.1:8000. RADIUS pages need a FreeRADIUS MySQL database (`RADIUS_DB_*` in `.env`); without
one they show "RADIUS database is not reachable", and everything else works.

## Add a page

1. **Registry**: add a `Page(...)` to `PAGES` in `apps/core/pages.py` (key, URL path, title, menu group,
   template, icon, role). The URL, menu item, breadcrumb and access check come from this one line.
2. **Template**: create it, for example `templates/inventory/racks.html`:

   ```django
   {% extends "base.html" %}
   {# Racks (/racks): what this page shows. Data: pages/racks.js #}
   {% block content %}
   <section id="racks">
     <div class="title"><div>{% include "components/_page_heading.html" with title=page.title subtitle="One sentence on what this page is for." %}</div></div>
     <div id="rackList"></div>
   </section>
   {% endblock %}
   ```
3. **Icon**: `templates/components/icons/<icon>.svg` (18 × 18, `stroke="currentColor"`).
4. **Script**: `static/js/pages/racks.js` with a loader `async function loadRacks(){...}`. Bind buttons with
   `$o("#id")` so the file is harmless on other pages. Add the `<script>` to `templates/base.html` before
   `core/search.js`, and `racks:loadRacks` to `PAGE_INIT` in `static/js/core/start.js`.
5. **API**: reads in the app's `selectors.py`, changes in `services.py`, and the endpoint in `views.py` with
   `@api(GET="viewer", ...)` plus its `urls.py` (see "Add a JSON endpoint").

## Where does my code go?

| You are writing... | Put it in | Never in |
|---|---|---|
| reading the request, the answer, the audit entry | `views.py` | |
| a rule, a validation, anything that changes data | `services.py` | `views.py` |
| a database query that only reads | `selectors.py` | `views.py`, another app |
| talking to a device, files, the OS, FreeRADIUS | an integration module (`engine.py`, `storage.py` ...) | `views.py` |
| data from another app | that app's `selectors` / `services` | that app's `models` |

`python manage.py check_architecture` tells you at once when something is in the wrong place.

## Add a JSON endpoint

```python
# apps/inventory/selectors.py  - reads
def racks():
    return [{"id": r.id, "name": r.name} for r in Rack.objects.order_by("name")]

# apps/inventory/services.py   - rules and changes
def create_rack(name):
    if not name:
        raise ApiError(400, "Enter a name for the rack.")      # shown to the user as a clear message
    return Rack.objects.create(name=name)

# apps/inventory/views.py      - HTTP only
@api(GET="viewer", POST="operator")          # method -> lowest role allowed
def racks(request):
    if request.method == "GET":
        return JsonResponse({"racks": selectors.racks()})
    rack = services.create_rack((parse_json(request).get("name") or "").strip())
    record_audit(request, "rack.create", rack.name)
    return JsonResponse({"id": rack.id}, status=201)
```

Error messages are shown to users as notifications: write them as a full sentence that says what to do.

## Add a device vendor

One entry in `VENDORS` in `apps/devices/vendors.py` (login driver and backup command). Optional: a logo in
`static/img/vendors/` and its name in `VENDOR_LOGO` in `static/js/pages/devices.js`.

## Notifications and texts

- `toast("The device was added.", {title:"Device added"})`: success. Types: `success`, `info`, `warning`,
  `error`. Errors stay until closed. Add `action:{label:"Open", run:()=>showTab("logs")}` for a next step.
- `confirmAction({...})` before anything destructive; `errorState(what, err)` when a section cannot load.
- Write titles in Title Case ("Device added"), messages as sentences that say what happened and what to do.
  Never show stack traces, paths or database errors: log them on the server instead.

## Before you ship

- `python manage.py check_architecture`, `python manage.py check --deploy` and `python -m pyflakes apps config`
  must be clean.
- Open every page in the browser (desktop and phone width) with an Administrator and a Viewer account; the
  browser console must show no errors.
- Raise the `?v=` numbers in `templates/base.html` if CSS or JS changed.
- Add a line to `CHANGES.md`.
- Build the release zip with `python deploy/build_release.py` (it leaves out `.env`, the runtime `data/` and
  `logs/` folders, caches and tests, and stops if any template, static file or module is missing).
  Do not zip by hand: excluding a folder name such as `logs` by hand also drops `templates/logs/`.
  Deploy it with [DEPLOY.md](DEPLOY.md).
