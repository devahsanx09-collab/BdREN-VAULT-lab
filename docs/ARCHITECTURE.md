# Architecture

How the VAULT is put together. For "which file does what", see
[FILE_GUIDE.md](FILE_GUIDE.md); to add or change something, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Components

```
 Browser ──HTTPS──> nginx :443 ──> waitress (manage.py serve, service "dbms") ──> Django app
                                                                                  │
            ┌──────────────────────────────┬──────────────────────────┬──────────┴─────────────┐
            │ MySQL "dbms"                  │ MySQL "radius"            │ data/ folder            │
            │ devices, jobs, logs, users,   │ FreeRADIUS tables: users, │ backups/ (snapshots)    │
            │ settings, audit               │ groups, NAS, login log    │ secret.key, known_hosts │
            └──────────────────────────────┴─────────────┬────────────┴────────────────────────┘
                                                         │ read on every login
 Switch / router ──RADIUS UDP 1812──> FreeRADIUS 3 ──────┘
 Backup engine ──SSH 22 / ICMP──> switches, routers, OLTs, firewalls
```

- **Django app** (one process): web pages, JSON API, the SSH backup engine, the scheduler and the ping monitor
  (background threads started by `apps/core/background.py`).
- **FreeRADIUS** never talks to the app. Both use the `radius` database, so a user, level, device limit or new
  switch saved in the panel is used on the next login, with no restart.

## Layered architecture (server)

Every app in `apps/` is built in the same layers, following the widely used Django "service layer" style.
A module may only depend on the layers **below** it:

```
 HTTP         views.py, urls.py         read the request → call a selector or service → answer (JSON / page)
     │                                  + record the audit entry (it needs the request: user and IP)
     ▼
 business     services.py               rules and every change: validation, writes, transactions
     │
     ▼
 read         selectors.py              every database read; never changes anything
     │
     ▼
 integration  engine.py (SSH)  storage.py (files)  jobs.py (background jobs)  reports.py
              monitoring ping (OS `ping`)  radius router.py (FreeRADIUS database)
     │
     ▼
 data         models.py                 tables only
```

| App | HTTP | Business | Read | Integration |
|---|---|---|---|---|
| `accounts` | sign-in pages, `/api/me`, `/api/users` | password rules, lockout, user changes | users, sign-in history | |
| `devices` | `/api/devices`, `/api/credentials` | validation, add / edit / delete, saved logins | inventory, saved login profiles | |
| `backups` | `/api/backup`, `/api/jobs`, `/api/logs`, `/api/backups` | back up one device, start / stop jobs, delete versions, log housekeeping | jobs, logs, versions, reports, alerts | `engine.py`, `storage.py`, `jobs.py`, `reports.py`, `audit.py` |
| `monitoring` | `/api/ping`, `/api/dashboard` | ping, background monitor | Dashboard numbers, server health | OS `ping` |
| `scheduling` | `/api/settings` | settings, the backup timer | | |
| `radius` | `/api/radius/*` | RADIUS users, levels, NAS, FreeRADIUS restart | users, NAS, logins, limit violations | `router.py` (second database) |
| `core` | pages, `/healthz` | | | shared kernel: `api.py`, `crypto.py`, `netguard.py`, `background.py`, `pages.py` |

**Between apps** only the public modules are used: another app's `selectors`, `services` (and `audit`,
`vendors`, `jobs`, `engine`). Example: the Dashboard reads backup numbers with
`apps.backups.selectors.results_per_day()`, never `BackupLog.objects`. `apps/core` is the shared kernel every
app may use; `core/background.py` is the composition root that starts the periodic services.
Maintenance commands (`management/commands/`) may use any app's models directly, like migrations.

**The rules are checked by a command**, so they cannot drift:

```bash
python manage.py check_architecture        # "Architecture OK" or the file, line and rule broken
```

The rules themselves are in `apps/core/architecture.py`; the test suite runs the same check.

## Pages: one URL per screen

Every screen is its own page. The list lives in one place, **`apps/core/pages.py`**:

| Key | URL | Template | Role |
|---|---|---|---|
| `dashboard` | `/dashboard` | `dashboard/index.html` | Viewer |
| `devices` | `/devices` | `devices/index.html` | Viewer |
| `device` | `/devices/<id>` | `devices/detail.html` | Viewer |
| `backups` | `/backups` | `backups/index.html` | Viewer |
| `reports` | `/reports` | `reports/index.html` | Viewer |
| `jobs` | `/jobs` | `jobs/index.html` | Viewer |
| `logs` | `/logs` | `logs/index.html` | Viewer |
| `radius-users` | `/radius/users` | `radius/users.html` | Administrator |
| `radius-nas` | `/radius/nas` | `radius/nas.html` | Administrator |
| `radius-audit` | `/radius/audit` | `radius/audit.html` | Administrator |
| `users` | `/users` | `accounts/users.html` | Administrator |
| `settings` | `/settings` | `settings/index.html` | Administrator |

The registry drives the URL table (`config/urls.py`), the side menu, the breadcrumb, the browser-tab title and
access. A role below the page's role gets `templates/errors/forbidden.html` (HTTP 403). `/` opens the Dashboard;
after signing in the user returns to the page they asked for (`/login?next=/devices`).

### Request flow of a page

1. `apps/core/views.py: page_view()` looks the key up in the registry and renders the page's template.
2. Every page template does `{% extends "base.html" %}` and fills `{% block content %}`.
3. `templates/base.html` draws the side menu (for this role), top bar, shared pop-ups, and sets
   `<body data-page="devices" class="r-admin">`.
4. The browser loads the scripts (below); `core/start.js` calls the page's loader, which fetches its data
   from the JSON API and draws it.

## Browser code

All scripts load on every page, in a fixed order, and share one global scope: one cached set, no build step,
and a function from an earlier file can be used directly.

```
static/js/core/    shared by every page
  early.js          side-menu state before the page is drawn
  helpers.js        $, $o, esc, toast, api(), dates, confirm pop-up, pager, PAGE / showTab / openDevice
  menu.js           phone drawer, minimise, RADIUS drop-down, account menu
  account.js        signed-in user (ME), sign out, change own password
  backup-jobs.js    start / follow / stop a backup (top-bar chip on every page)
  search.js         global search (Ctrl+K)
  start.js          PAGE_INIT: runs the open page's loader; idle sign-out
  responsive.js     tables become cards on phones
static/js/pages/   one file per screen (dashboard, devices, backups, reports, jobs, logs, users, settings, radius)
static/js/pages/auth.js   sign-in page only
```

Rules that keep this safe:

- **Only the open screen loads data.** `PAGE` (from `body[data-page]`) selects the loader in `PAGE_INIT`.
- **Page bindings never break other pages.** A page script binds its buttons with `$o("#id")`, which returns a
  detached placeholder when the element is not on this page. Code that runs on a timer checks `PAGE`.
- **Live updates in place.** `morph(el, html)` changes only what differs, so tables and charts do not flicker.
- **Navigation is plain links.** `showTab("devices")` and `openDevice(id)` change `location`; links saved from the
  old one-page version (`/#devices`, `/#device/12`) are redirected by `start.js`.

Styles: `static/css/app.css` for the application (sections: tokens, base, shell, components, pages, motion,
responsive) and `static/css/auth.css` for the sign-in page.

## Backups

`apps/backups/jobs.py` runs one job at a time: ping every device in parallel, then up to N SSH sessions
(Settings → Performance). For each device `apps/backups/services.py`:

1. reads the configuration over SSH (`engine.py`, vendor command from `apps/devices/vendors.py`)
2. compares it with the latest saved version, ignoring lines that change on every read (clock, timestamps)
3. unchanged → records the check only; changed → writes a hidden `.part` file, then renames it **inside the same
   database transaction** that records the result (`storage.py`), then writes a SHA-256 checksum

A failure or Stop at any point leaves no partial file and does not change the last good backup.

Slow devices, login bursts and offline devices are handled as described in
[BACKUP_RELIABILITY.md](BACKUP_RELIABILITY.md): VAULT waits while a device sends data and gives up only when it
goes silent; logins are paced; temporary failures get an automatic second try in the same job; offline and
still-failing devices wait in a retry queue. A device's failure is written to the database only when final.

## RADIUS / AAA

The panel writes the standard FreeRADIUS tables (`radcheck`, `radusergroup`, `radgroupreply`, `nas`) and one
extra table, `dbms_user_nas` (where a user may log in). FreeRADIUS uses three policies from `deploy/radius/`:

- `dbms_dynamic_clients`: a switch added on NAS Clients works without a restart
- `dbms_device_limit`: refuses a login on a device outside the user's list
- `dbms_huawei_levels`: caps the level at 3 on "Huawei (levels 0-3 only)" switches

Access levels send each vendor's attribute with `:=`, so nothing else can override the level chosen in the
panel. `deploy/radius/check_levels.sh` verifies the whole chain on a server.

## Security

- Every JSON endpoint goes through `apps/core/api.py` (`@api(GET="viewer", POST="operator", ...)`): method and
  role are checked on the server, never only in the browser.
- Device passwords are encrypted with Fernet (`data/secret.key`); they reach the browser only when an
  administrator presses Show, which is audited.
- Strict Content-Security-Policy (no inline or eval scripts), HSTS on HTTPS, no search-engine indexing,
  generic error messages (`apps/core/middleware.py`).
- Sign-in lockout after 5 wrong passwords, idle sign-out, sign-in history with the real client IP.
