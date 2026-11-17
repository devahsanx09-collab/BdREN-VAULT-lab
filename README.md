# BdREN VAULT

A web application for backing up the running configuration of network devices (switches, routers and OLTs) over SSH, keeping every version, monitoring device reachability, and managing users with role-based access.

## Install or update: one command

On Ubuntu / Debian, get the code and run its installer. The same command installs a new server and
updates an existing one. From a GitHub clone:

```bash
git clone <your-repo-url> dbms
```
```bash
sudo bash dbms/deploy/install.sh
```

Or from a release package:

```bash
unzip -o BdREN-VAULT.zip -d /tmp/dbms
```
```bash
sudo bash /tmp/dbms-new/dbms/deploy/install.sh
```

The code in Git holds **no secrets**: `.env` (database password, server address) and `data/` (the encryption
key, session key, saved backups) are git-ignored, so a clone starts clean. The installer creates them on the
first run from the few answers you give.

- **New server**: asks only what it needs - the address people use in the browser, the **database password**
  (press Enter and it generates a strong one), an administrator account, and whether to install FreeRADIUS and
  HTTPS (both default to yes) - and does the rest: Python packages, MariaDB and the application database,
  **FreeRADIUS** with its MySQL database and tables, the "where a user may log in" policy, login logging with
  the device, the FreeRADIUS restart permission, **nginx on HTTPS** with a self-signed certificate (replace it
  any time), firewall ports when ufw is on, the service, and a final check. Everything is stored only in `.env`;
  nothing is edited by hand.
- **Update**: keeps `.env`, the database, the backups (`data/`) and logs; replaces the program files exactly
  (old leftover files are removed), migrates the database and restarts. The previous version is saved in
  `/var/backups/dbms/` and is put back automatically if the update fails.
- When they apply: RADIUS tables and device logging for logins, the FreeRADIUS restart permission, and the
  nginx lines that pass the real visitor IP (HTTPS cookie settings are switched on when nginx serves HTTPS).

### Use a domain name (with a free Let's Encrypt certificate)

1. Create a DNS **A record**, e.g. `backup.example.com` -> the server's public IP.
2. Make sure ports **80 and 443** reach the server from the internet.
3. Run:

```bash
sudo bash /opt/dbms/deploy/set-domain.sh backup.example.com you@example.com
```

The domain is added to the app and to nginx (the IP keeps working), a Let's Encrypt certificate is issued
and renewed automatically, and secure cookies / HTTPS redirect are switched on. If Let's Encrypt is not
possible yet (DNS not ready, port 80 closed) a self-signed certificate for the domain is used; run the same
command again later. A fresh installation asks for the domain directly.

## Documentation

| Read | For |
|---|---|
| [docs/DEPLOY.md](docs/DEPLOY.md) | Install, update in 3 commands, domain, checks, server backup |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it fits together: pages, browser code, backups, RADIUS, security |
| [docs/FILE_GUIDE.md](docs/FILE_GUIDE.md) | Which file does what |
| [docs/BACKUP_RELIABILITY.md](docs/BACKUP_RELIABILITY.md) | Patient SSH backups, the automatic second try and the retry queue |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Run it locally, add a page / API / vendor, notifications and texts, release checklist |
| [CHANGES.md](CHANGES.md) | What changed in each build |

## Screens

Every screen has its own address; bookmarks and the browser Back button work as usual.

| Menu | Screen | Address | Who |
|---|---|---|---|
| Overview | Dashboard | `/dashboard` | everyone |
| Inventory | Device Inventory, one device's backups | `/devices`, `/devices/<id>` | everyone |
| Configuration | Configuration Backups, Change Reports | `/backups`, `/reports` | everyone |
| Operations | Backup Jobs, Activity Logs | `/jobs`, `/logs` | everyone |
| Access Control | RADIUS / AAA: AAA Users, NAS Clients, Authentication Audit | `/radius/users`, `/radius/nas`, `/radius/audit` | Administrator |
| Administration | User Management, System Settings | `/users`, `/settings` | Administrator |

Viewers can look; Operators can also run backups and manage devices; Administrators can do everything.

## Features

- Scheduled and on-demand configuration backups with version history
- Integrity check (SHA-256) for every stored backup
- Continuous ICMP reachability monitoring with a dashboard
- Device inventory with encrypted credential storage (Fernet)
- Role-based user accounts, login lockout and audit log
- Download, compare and delete backups; export inventory and compliance reports as CSV
- Responsive interface for desktop, tablet and mobile

## RADIUS / AAA

Administrators see a **RADIUS / AAA** drop-down in the side menu with three pages:

- **AAA Users** - device login accounts, their access level (`super-admin`, `read-write`, `read-only`) and the devices each may log in to
- **NAS Clients** - network devices allowed to use the RADIUS server, with their shared secret and type (incl. Huawei levels 0-3 / 0-15)
- **Authentication Audit** - every device login answered by FreeRADIUS and every change made on these pages

How it fits together:

- The pages read and write the FreeRADIUS database (`radcheck`, `radusergroup`, `radgroupreply`, `nas`, `radpostauth`) through a second connection named `radius`. Set `RADIUS_DB_NAME`, `RADIUS_DB_USER`, `RADIUS_DB_PASSWORD`, `RADIUS_DB_HOST` and `RADIUS_DB_PORT` in `.env`.
- Sign-in is the normal sign-in of this application. Only the **Administrator** role can open the RADIUS pages; the separate logins of the old panel are no longer used.
- A new device works immediately (FreeRADIUS dynamic clients). Removing a device restarts FreeRADIUS once with `RADIUS_RELOAD_CMD`. The Linux user that runs this application needs permission for that command: see `deploy/radius/sudoers-dbms.example`. Inside Docker the default command cannot reach the host's FreeRADIUS; run the application directly on the RADIUS server or set `RADIUS_RELOAD_CMD` to something that can.
- The FreeRADIUS tables are reused as they are. Run `python manage.py radius_init` once: it creates the panel's audit and per-switch tables when they are missing and seeds the access-level groups. (A new, empty database needs the FreeRADIUS `schema.sql` loaded first.)
- Shared secrets are not sent with the device list; an administrator sees one only after pressing Show or Copy, and that is written to the audit log.
- `RADIUS_PASSWORD_MODE=ssha2` stores new RADIUS passwords as salted SHA-256 instead of clear text (PAP logins only). Test one user with `radtest` before relying on it.
- After changing `PROFILES` in `apps/radius/services.py`, run `python manage.py seed_groups` again.
- Firewall: `sudo bash /opt/dbms/deploy/radius/enable_firewall_sync.sh` (run once; the installer does it too) keeps UDP 1812/1813 open in ufw only for the devices on NAS Clients. Adding a device opens RADIUS for its address within seconds, removing it closes it, and the old "open to everyone" rules are removed once every device has its own rule. The app runs a root-owned script (`/usr/local/sbin/dbms-radius-firewall`) that takes no arguments and reads the list from the database itself.
- Check the whole RADIUS chain on a server with `sudo bash /opt/dbms/deploy/radius/check_levels.sh` (read-only; ends with ALL CHECKS PASSED or the fixes).
- A user can be limited to selected switches (AAA Users -> Edit -> "Where this user can log in"). The choice is stored in the `dbms_user_nas` table (created by `radius_init`) and enforced by a small FreeRADIUS policy that must be installed once: see the steps at the top of `deploy/radius/dbms_device_limit`. FreeRADIUS compares the list with the address the RADIUS request comes from, which is the address registered under Devices (NAS). Until the policy is installed the limit is saved but not enforced (the user can log in everywhere).

## Requirements

- Python 3.10 or newer (Ubuntu 22.04's Python works), **or** Docker with Docker Compose
- Network access from the server to the managed devices (SSH, port 22 by default)

## Quick start with Docker (recommended)

```bash
cp .env.example .env          # then edit DJANGO_ALLOWED_HOSTS and other settings
docker compose up -d --build
```

Open `http://<server-ip>:8000`. Create the first administrator with:

```bash
docker compose exec dbms python manage.py createsuperuser
```

Data (database, backups, keys) is stored in the `dbms-data` Docker volume.

## Installation on Ubuntu 22.04 / 24.04

```bash
sudo apt install -y python3-venv python3-pip unzip iputils-ping
sudo unzip -q -o dbms-radius-merged.zip -d /opt          # gives /opt/dbms
sudo useradd --system --home /opt/dbms --shell /usr/sbin/nologin dbms
sudo mkdir -p /opt/dbms/data && sudo chown -R dbms:dbms /opt/dbms
sudo -u dbms python3 -m venv /opt/dbms/.venv
sudo -u dbms /opt/dbms/.venv/bin/pip install -r /opt/dbms/requirements.txt
sudo -u dbms cp /opt/dbms/.env.example /opt/dbms/.env   # then edit it; keep it mode 640
cd /opt/dbms
sudo -u dbms .venv/bin/python manage.py migrate
sudo -u dbms .venv/bin/python manage.py radius_init      # RADIUS tables + access-level groups (run again after every update)
sudo -u dbms .venv/bin/python manage.py createsuperuser
sudo cp deploy/dbms.service /etc/systemd/system/ && sudo systemctl enable --now dbms
```

Always run `manage.py` as the `dbms` user with the virtualenv's Python, as above. Put nginx with HTTPS in front
using `deploy/nginx-dbms.conf`. To update later, unzip the new version over `/opt/dbms` with `-o`
(`.env`, `.venv` and `data/` are not part of the zip), run `migrate`, then `sudo systemctl restart dbms`.

## Production checklist

1. Serve the application over HTTPS through a reverse proxy (`deploy/nginx-dbms.conf`).
2. Set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to your exact domain or IP.
3. Set `DBMS_BEHIND_PROXY=1`, `DBMS_SECURE_COOKIES=1` and `DBMS_FORCE_HTTPS=1` when HTTPS is in use.
4. Keep `DJANGO_DEBUG` unset or `0`.
5. Back up the data folder (or the `dbms-data` volume). It contains `secret.key`; without it, saved device passwords cannot be decrypted.
6. Restrict access to the management network with a firewall or VPN where possible.

## Configuration

All settings are environment variables documented in `.env.example`. Variables named `NETBACKUP_*` from earlier versions are still accepted.

## Database

VAULT keeps **every table in MySQL 8.0 / MariaDB 10.6+** (configured in `config/settings.py`, credentials in `.env`): devices, backup jobs and logs, settings and the retry queue, users, sessions and the audit trail. The Dashboard "Database size" card reads the size from MySQL (`information_schema`). The "Backups per day" chart groups days in Python, so it does not need the MySQL time-zone tables.

Create the database with the correct character set first:

```sql
CREATE DATABASE dbms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'dbms'@'%' IDENTIFIED BY 'strong-password';
GRANT ALL PRIVILEGES ON dbms.* TO 'dbms'@'%';
```

Then set in `.env`:

```
DBMS_DB_ENGINE=mysql
DBMS_DB_NAME=dbms
DBMS_DB_USER=dbms
DBMS_DB_PASSWORD=strong-password
DBMS_DB_HOST=127.0.0.1
DBMS_DB_PORT=3306
```

Create the tables with `python manage.py migrate`. The MySQL driver is PyMySQL, which is pure Python, so no C build tools are needed.

With Docker, `docker compose up -d --build` starts MySQL together with the app. Set `DBMS_DB_PASSWORD` and `DBMS_DB_ROOT_PASSWORD` in `.env`.

Keep `secret.key` in the data folder. Without it, saved device passwords cannot be decrypted. Backup files in `data/backups` stay where they are.

## Session and sign-out behaviour

- Login cookies are browser-session cookies and are removed when the browser is fully closed.
- Sessions expire after 30 minutes of inactivity by default; active requests refresh the idle timeout.
- Set `DBMS_SESSION_MINUTES` in `.env` to change the idle timeout (minimum 5 minutes, maximum 24 hours).
- The Sign out action sends a POST to `/logout`, clears the Django session, and returns the browser to the login page.

## Performance (500 - 1000 devices)
- Parallel SSH sessions: 1 to 50 (System Settings -> Performance). The capacity planner there shows how long a
  full backup of all devices takes, measured from recent jobs, and the number of sessions needed for 30 minutes.
- Every device is pinged first; only devices that answer get an SSH session. Ping and backup run as a pipeline.
- The ping monitor scales up to 64 parallel pings for large inventories; a device is shown offline only after two
  failed sweeps in a row (one lost burst of replies is ignored).
- Job progress is written about 50 times per job; finished jobs keep a small summary for the Backup Jobs page.
- Activity Logs search and filters run in the database, so all history stays reachable.
- Do not delete the migrations: they describe the database structure. Deployment archives need no
  `__pycache__`, `.pyc`, virtual environment, local `.env` or runtime `data/`.
