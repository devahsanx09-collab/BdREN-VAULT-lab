<div align="center">

# BdREN VAULT

### Network Configuration Backup &amp; RADIUS / AAA Access Control — in one secure web portal

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5.2_LTS-092E20?logo=django&logoColor=white)
![MariaDB](https://img.shields.io/badge/MariaDB%20%2F%20MySQL-database-003545?logo=mariadb&logoColor=white)
![FreeRADIUS](https://img.shields.io/badge/FreeRADIUS-3-D22128)
![Platform](https://img.shields.io/badge/Platform-Ubuntu%20%2F%20Debian-E95420?logo=ubuntu&logoColor=white)
![License](https://img.shields.io/badge/Use-Internal%20(BdREN)-blue)

</div>

---

**BdREN VAULT** gives a network team one place to do two jobs that usually need separate tools:

1. **Configuration backup** — connect to switches, routers and OLTs over SSH, save their running
   configuration on a schedule or on demand, keep every version, and show exactly what changed.
2. **RADIUS / AAA access control** — decide who may log in to those devices, at what level, and on which
   devices. FreeRADIUS answers every device login against these rules.

It also watches device reachability, keeps a full audit trail, and works on desktop, tablet and phone.
The web app **manages** the data; **FreeRADIUS** answers the logins separately, so device logins keep
working even while the web app restarts.

> VAULT only **reads** device configuration — it never sends a command that changes a device.

---

## Table of contents

- [Features](#features)
- [Technology stack](#technology-stack)
- [Quick start (one command)](#quick-start-one-command)
- [Screens &amp; roles](#screens--roles)
- [RADIUS / AAA](#radius--aaa)
- [Security](#security)
- [Documentation](#documentation)
- [Requirements](#requirements)

---

## Features

**Configuration backup**
- Scheduled and on-demand backups with full version history
- Line-by-line change reports between versions
- SHA-256 integrity fingerprint for every stored backup
- Automatic retry with a self-healing queue when a backup fails
- Supports Cisco, Huawei (incl. SmartAX OLTs), MikroTik, Fortinet, Juniper, HP Comware, TP-Link, BDCOM and V-SOL

**RADIUS / AAA**
- Device login accounts with three access levels: `super-admin`, `read-write`, `read-only`
- Limit a user to specific devices or to a device type (new devices of that type are covered automatically)
- A new device works instantly — no FreeRADIUS restart
- Copy-ready setup commands per vendor (**Device Setup** page)
- The firewall opens RADIUS (UDP 1812/1813) only for the devices on your NAS Clients list

**Operations &amp; security**
- Continuous ICMP reachability monitoring with a dashboard
- Encrypted device credentials (Fernet); role-based accounts; sign-in lockout; full audit log
- Notification bell that surfaces failed backups and other problems
- Responsive interface, light and dark themes

---

## Technology stack

| Layer | Technology |
|---|---|
| Language | **Python 3.10+** |
| Web framework | **Django 5.2** (LTS) |
| App server | **Waitress** (systemd service) |
| Web server / TLS | **nginx** on HTTPS |
| Static files | **WhiteNoise** + GZip |
| Database | **MariaDB / MySQL** (driver: PyMySQL) |
| AAA server | **FreeRADIUS 3** |
| SSH to devices | **Netmiko** + **Paramiko** |
| Encryption / integrity | **cryptography** (Fernet), SHA-256 |
| Front end | Django templates, plain JavaScript, custom CSS (no framework, no external CDN) |

Everything in the stack is free and open source. The code is organised in seven modules
(`accounts`, `devices`, `backups`, `scheduling`, `monitoring`, `radius`, `core`) following strict
layers — **models → selectors → services → views** — enforced by `manage.py check_architecture`.

---

## Quick start (one command)

On a fresh **Ubuntu / Debian** server, get the code and run the installer. The same command installs a new
server and updates an existing one.

**From a release package**
```bash
unzip -o BdREN-VAULT.zip -d /tmp/bdren-vault
sudo bash /tmp/bdren-vault/deploy/install.sh
```

**From a Git clone**
```bash
git clone <your-repo-url> bdren-vault
sudo bash bdren-vault/deploy/install.sh
```

On a **new install** the installer asks its few questions once — browser address, database password
(press Enter to generate one), the first administrator, and whether to install FreeRADIUS, HTTPS and the
firewall — then does the rest on its own: system packages, **MariaDB** and the application database,
**FreeRADIUS** with its own database and tables, login logging, the per-device RADIUS firewall,
**nginx on HTTPS** with a self-signed certificate, the systemd service and a final health check.

An **update** keeps `.env`, the database, the backups and the logs, replaces the program files exactly,
migrates the database and restarts — and rolls back automatically if a migration fails.

> **No secrets in Git.** `.env` (passwords, server address) and `data/` (encryption key, session key,
> saved backups) are git-ignored, so a clone starts clean. The installer creates them on first run.

📘 A full step-by-step **[Setup &amp; Installation Guide (PDF)](docs/VAULT-Setup-and-Install-Guide.pdf)** is in `docs/`.

### Use a domain name with a free HTTPS certificate
```bash
sudo bash /opt/bdren-vault/deploy/set-domain.sh backup.example.com you@example.com
```
Point a DNS **A record** at the server and make sure ports **80 and 443** are reachable. A Let's Encrypt
certificate is issued and renewed automatically (a self-signed one is used until that is possible).

---

## Screens &amp; roles

| Menu | Screens | Who |
|---|---|---|
| Overview | Dashboard | Everyone |
| Inventory | Device Inventory, per-device backups | Everyone |
| Configuration | Configuration Backups, Change Reports | Everyone |
| Operations | Backup Jobs, Activity Logs | Everyone |
| Access Control | AAA Users, NAS Clients, Authentication Audit, Device Setup | Administrator |
| Administration | User Management, System Settings | Administrator |

| Role | Can do |
|---|---|
| **Viewer** | Look at everything except administration pages |
| **Operator** | Viewer rights, plus run backups and manage devices |
| **Administrator** | Everything, including RADIUS / AAA and user management |

Every screen has its own address; bookmarks and the browser Back button work as usual.

---

## RADIUS / AAA

When someone logs in to a switch, the switch asks FreeRADIUS, which checks the user, the password, and
whether that user may log in **to that specific device**, then answers **Accept** (with an access level)
or **Reject**. Every attempt appears under **Authentication Audit**.

- The pages read and write the FreeRADIUS database (`radcheck`, `radusergroup`, `radgroupreply`, `nas`,
  `radpostauth`) over a second connection named `radius` (`RADIUS_DB_*` in `.env`).
- Shared secrets are hidden — an administrator sees one only after pressing Show or Copy, and that is logged.
- Per-device limits are stored in `bdren-vault_user_nas` and enforced by a small FreeRADIUS policy
  (`deploy/radius/bdren-vault_device_limit`).
- **Firewall:** `sudo bash deploy/radius/enable_firewall_sync.sh` (the installer runs it too) keeps
  UDP 1812/1813 open only for the devices on NAS Clients — adding a device opens its address within
  seconds, removing it closes it. The app runs a root-owned script that takes no arguments and reads the
  list from the database itself, so the website can never choose a firewall rule.
- Check the whole chain with `sudo bash deploy/radius/check_levels.sh` (read-only).

> **Keep one local admin account on every device.** If RADIUS is ever unreachable, the device falls back
> to its local accounts, so you are never locked out. Keep RADIUS usernames different from local ones.

---

## Security

- **HTTPS only**, with secure cookies and modern security headers (CSP, no-sniff, clickjacking protection)
- Portal passwords are hashed; **12+ characters**; sign-in pauses after 5 wrong attempts; idle sign-out
- Device SSH passwords are **encrypted** (Fernet); the key stays on the server, never in the code
- RADIUS shared secrets are shown only on request, and logged
- Role-based access; RADIUS and user management are for Administrators only
- Every portal sign-in, every change and every device login is recorded with time, user and IP
- SHA-256 integrity for every backup; CSRF protection on every form
- No secrets in Git; RADIUS ports open only to NAS Clients devices

---

## Documentation

| Read | For |
|---|---|
| [docs/VAULT-Setup-and-Install-Guide.pdf](docs/VAULT-Setup-and-Install-Guide.pdf) | Full setup &amp; installation guide (PDF) |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Install, update, domain, checks, server backup |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it fits together: pages, backups, RADIUS, security |
| [docs/FILE_GUIDE.md](docs/FILE_GUIDE.md) | Which file does what |
| [docs/BACKUP_RELIABILITY.md](docs/BACKUP_RELIABILITY.md) | Patient SSH backups, the retry queue |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Run it locally, add a page / API / vendor, release checklist |
| [CHANGES.md](CHANGES.md) | What changed in each build |

---

## Requirements

- A server running **Ubuntu or Debian Linux** with internet access for the initial install
- Network reach from the server to the managed devices: **SSH (TCP 22)** and **ICMP**
- For RADIUS: devices reach the server on **UDP 1812 / 1813**

Everything else (Python packages, MariaDB, FreeRADIUS, nginx) is installed automatically by the installer.

---

<div align="center">

**BdREN** · Network Infrastructure Management · *Backup Today… Ensure Tomorrow…*

</div>
