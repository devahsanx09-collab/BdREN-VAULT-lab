# File guide

Which file does what. Read [ARCHITECTURE.md](ARCHITECTURE.md) first for the big picture and the layer rules.

Every app has the same files: `views.py` + `urls.py` (HTTP), `services.py` (rules and changes),
`selectors.py` (reads), `models.py` (tables), plus its integrations (SSH, files, jobs ...).

## Where to start

| I want to change... | Open this file |
|---|---|
| The menu, a page's URL, title or who may open it | `apps/core/pages.py` |
| A page's layout or text | `templates/<area>/<page>.html` (for example `templates/devices/index.html`) |
| The side menu, top bar or a shared pop-up | `templates/base.html`, `templates/components/` |
| What a page does (buttons, tables) | `static/js/pages/<page>.js` |
| Notifications, API calls, dates, pager | `static/js/core/helpers.js` |
| Colours, spacing, the look | `static/css/app.css` (tokens at the top); sign-in page: `static/css/auth.css` |
| Sign-in page | `templates/accounts/auth.html`, `apps/accounts/views.py`, `static/js/pages/auth.js` |
| Supported device types (Cisco, Huawei, Fortinet ...) | `apps/devices/vendors.py` |
| A list or number shown on a page (database read) | `apps/<app>/selectors.py` |
| A rule or a change (add, edit, delete, start) | `apps/<app>/services.py` |
| The layer rules and their check | `apps/core/architecture.py`, `python manage.py check_architecture` |
| How a backup is taken from a device (SSH) | `apps/backups/engine.py` |
| When a backup is saved or skipped | `apps/backups/services.py` |
| Where backup files are stored on disk | `apps/backups/storage.py` |
| Background backup jobs (parallel, progress) | `apps/backups/jobs.py` |
| Ping and the background ping monitor | `apps/monitoring/services.py` |
| Settings page, automatic backup timer | `apps/scheduling/services.py` |
| Web users, roles, sign-in lockout | `apps/accounts/` |
| RADIUS users, levels, NAS, audit | `apps/radius/services.py`, `apps/radius/views.py` |
| FreeRADIUS policies and setup scripts | `deploy/radius/` |
| Server settings (environment) | `config/settings.py` and `.env` |

## Project layout

```
config/                  Django project
  settings.py            All settings, read from environment variables / .env
  urls.py                URL table: one URL per page (from apps/core/pages.py) + each app's /api/ URLs
  wsgi.py                Entry point for waitress

apps/                    Django apps, one folder per area
  core/                  Shared code
    pages.py             THE PAGE REGISTRY: every screen, its URL, menu group, template, icon and role
    views.py             Renders a page (base.html + the page's template), /healthz, /robots.txt
    architecture.py      The layer rules (python manage.py check_architecture)
    api.py               @api(...) decorator: method and role check for every JSON endpoint
    background.py        Composition root: starts the scheduler, ping monitor and log retention threads
    crypto.py, keys.py   Device-password encryption (Fernet) and key files
    middleware.py        Security headers on every response
    netguard.py          Checks SSH target addresses
    alerts.py            Optional e-mail / Telegram alerts for failed backups
    management/commands/ serve, check_architecture, backup_retention, verify_backups, system_health, ...
  accounts/              Sign-in, first-run setup, web users and roles
    views.py  services.py  selectors.py  models.py  urls.py
  devices/               Device inventory
    views.py  services.py  selectors.py  models.py  urls.py
    vendors.py           Vendor table: login driver, backup command, name parser
  backups/               Configuration backups
    views.py  services.py  selectors.py  models.py  urls.py
    engine.py            SSH login to ONE device and read its configuration
    storage.py           Snapshot files: data/backups/<device>/<YYYY>/<Mon>/<DD>/ (all-or-nothing saves)
    jobs.py              Parallel backup jobs in a background thread
    reports.py           Change report (diff of versions per month range)
    audit.py             The audit trail: record_audit() and every audit read
  monitoring/            Ping and the Dashboard numbers
    views.py  services.py (ping, monitor)  selectors.py (Dashboard, health)  models.py
  scheduling/            Settings and the automatic backup timer
    views.py  services.py  models.py
  radius/                RADIUS / AAA (FreeRADIUS database)
    views.py  services.py  selectors.py  models.py  urls.py
    router.py            Sends these tables to the second database (`radius`)

templates/
  base.html              Frame of every page: side menu, top bar, shared pop-ups, scripts
  components/            _page_heading.html, dialogs.html (shared pop-ups), icons/*.svg (menu icons)
  errors/forbidden.html  "You do not have access" page (HTTP 403)
  dashboard/index.html   /dashboard
  devices/index.html     /devices          detail.html  /devices/<id>   _device_fields.html  Add / Edit form
  backups/index.html     /backups
  reports/index.html     /reports
  jobs/index.html        /jobs
  logs/index.html        /logs
  accounts/users.html    /users            auth.html  sign-in and first-run setup
  settings/index.html    /settings
  radius/users.html      /radius/users     nas.html  /radius/nas   audit.html  /radius/audit
  radius/_dialogs.html   RADIUS pop-ups (Add / Edit user, Add device)

static/
  css/app.css            Application styles (design tokens first, then layout, components, pages, responsive)
  css/auth.css           Sign-in page styles
  js/core/               Shared by every page (see ARCHITECTURE.md, "Browser code")
  js/pages/              One file per page
  img/vendors/           Vendor logos

deploy/
  install.sh             One command: install a new server or update an existing one
  set-domain.sh          Add a domain name with a Let's Encrypt certificate
  vault.service          systemd unit
  nginx-dbms.conf        nginx site (HTTPS)
  radius/                FreeRADIUS policies, enable_*.sh helpers, check_levels.sh (RADIUS health check)

docs/                    ARCHITECTURE, FILE_GUIDE (this file), CONTRIBUTING, DEPLOY
```

## Scripts and their order

`templates/base.html` loads, in this order: `core/helpers.js`, `core/menu.js`, `core/account.js`,
`pages/dashboard.js`, `pages/devices.js`, `core/backup-jobs.js`, `pages/backups.js`, `pages/logs.js`,
`pages/users.js`, `pages/settings.js`, `pages/radius.js`, `pages/reports.js`, `pages/jobs.js`, `core/search.js`,
`core/start.js` (must come after every page loader), `core/responsive.js`.

| Page script | Page | Loader in `PAGE_INIT` |
|---|---|---|
| `dashboard.js` | Dashboard | `loadDashboard` |
| `devices.js` | Device Inventory (table, filters, ping, Add / Edit pop-ups, saved logins) | `loadDevices` |
| `backups.js` | Configuration Backups, one device's page, the viewer / compare pop-up | `loadBackups`, `loadDevicePage` |
| `reports.js` | Change Reports (month range, PDF / CSV) | `loadReport` |
| `jobs.js` | Backup Jobs | `loadJobs` |
| `logs.js` | Activity Logs and the audit trail | `loadLogs` |
| `users.js` | User Management and sign-in history | `loadUsers` |
| `settings.js` | System Settings and the capacity planner | `loadSettings` |
| `radius.js` | AAA Users, NAS Clients, Authentication Audit | `loadRadUsers`, `loadRadNas`, `loadRadAudit` |

## Things to know

- Migrations (`apps/*/migrations/`) are generated by Django; do not edit or delete them.
- `logs/`, `data/`, `staticfiles/` and `__pycache__/` are created at run time; they are not source code.
- After changing a CSS or JS file, raise every `?v=` number in `templates/base.html` (and in
  `templates/accounts/auth.html` for the sign-in files) so browsers load the new version.
- Templates are cached in production: restart the service (`sudo systemctl restart vault`) after changing one.
