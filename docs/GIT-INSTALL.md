# Git Install Guide — BdREN VAULT

How to install, update, and restore **BdREN VAULT** from the Git repo on an
Ubuntu/Debian server. Written for a real deployment (user `bdren`, server at
`/opt/vault`).

> **One rule to remember:** you never copy files *straight into* `/opt/vault`
> over SSH — the login user has no write permission there. Always land files in
> your **home** (`~/`) first, then move them with `sudo`/root. The installer does
> this correctly for you.

---

## 0. Where everything lives (file map)

| Path | What it is | Who owns it |
|---|---|---|
| `~/BdREN-VAULT` (`/home/bdren/BdREN-VAULT`) | **Source code** — your `git clone`. You run `git pull` here. | `bdren` |
| `/opt/vault` | **The running app** — built by `install.sh`. Don't clone here. | `vault:vault` |
| `/opt/vault/.venv` | Python virtual environment (packages) | `vault` |
| `/opt/vault/.env` | Settings & passwords (DB, host). **Never in Git.** | `vault` |
| `/opt/vault/data/` | Encryption key, session key, known_hosts | `vault` |
| `/opt/vault/data/backups/` | **Saved device configs** (`.txt` files) | `vault` |
| `/etc/systemd/system/vault.service` | The service that runs the app | root |
| MySQL/MariaDB `dbms` database | Users, devices, logs, settings | — |
| MySQL/MariaDB `radius` database | FreeRADIUS users/devices | — |

**Two things live OUTSIDE the database** and must be carried separately when you
migrate a server:
1. `data/backups/` — the saved configuration `.txt` files (on disk, not in DB).
2. `data/secret.key` — the key that decrypts device SSH passwords. Without the
   *same* key, saved device passwords can't be read.

---

## 1. First install (fresh server)

### a) Install git and clone the repo

```bash
sudo apt update && sudo apt install -y git
cd ~
git clone https://github.com/devahsanx09-collab/BdREN-VAULT.git
```

The repo is **private**, so Git asks to sign in:
- **Username:** `devahsanx09-collab`
- **Password:** not your GitHub password — a **Personal Access Token**.
  GitHub.com → your avatar → **Settings → Developer settings → Personal access
  tokens → Tokens (classic) → Generate new token** → tick **`repo`** → copy the
  token → paste it as the password. (Nothing shows while you paste — that's
  normal. Press Enter.)

### b) Run the installer

```bash
cd ~/BdREN-VAULT
sudo bash deploy/install.sh
```

`install.sh` does **everything** on its own and puts files where they belong:
- creates the `vault` system user and the `/opt/vault` folder,
- copies the code into `/opt/vault`, builds the Python **venv**,
- installs & configures **MariaDB** + the `dbms` and `radius` databases,
- installs **FreeRADIUS**, **nginx (HTTPS)**, the firewall, the `vault` service,
- runs database migrations and a final health check.

On a fresh install it asks a few questions once (browser address, DB password —
press Enter to auto-generate, the first admin, and whether to add FreeRADIUS /
HTTPS / firewall). Answer, then wait.

### c) Check it's up

```bash
systemctl status vault --no-pager
```

`active (running)` → open `https://<server-ip>/` in a browser.

---

## 2. Update an existing server (new version from Git)

This is the normal "get the latest code" flow. It **keeps** your database,
`.env`, and `data/` (backups + secret.key).

```bash
cd ~/BdREN-VAULT
git pull
sudo bash deploy/install.sh
```

- `git pull` → updates the **source** in your home folder.
- `install.sh` → redeploys that code into `/opt/vault`, migrates the DB, and
  restarts the service. It never touches `/opt/vault/data`.

> If `git pull` says **`detected dubious ownership`** (because you're root in a
> folder owned by `bdren`):
> ```bash
> git config --global --add safe.directory /home/bdren/BdREN-VAULT
> ```
> then run `git pull` again.

Then hard-refresh the site once: **Ctrl+F5**.

### Code-only update (without running install.sh)

If you only changed templates/static/python and don't want the full installer:

```bash
cd ~/BdREN-VAULT && git pull
sudo cp -r templates static apps config /opt/vault/
sudo chown -R vault:vault /opt/vault/templates /opt/vault/static /opt/vault/apps /opt/vault/config
sudo systemctl restart vault
```

---

## 3. Sending a file from Windows to the server

You **cannot** `scp` straight to `/opt/vault` (permission denied). Two steps:

**Windows (PowerShell) — send to home:**
```powershell
scp "D:\path\to\file.zip" bdren@203.96.190.80:~/
```

**Server (as root) — move it into place:**
```bash
mv /home/bdren/file.zip /opt/vault/
cd /opt/vault && unzip -o file.zip
chown -R vault:vault /opt/vault/data
```

---

## 4. Migrating data from an old server/PC

Three pieces move separately. Do all three or the app looks "empty".

### a) Database (`dbms`)

On the **source** (Windows MySQL), dump it:
```powershell
"C:\path\to\mysqldump.exe" -u root -p --single-transaction --routines --triggers dbms > dbms_backup.sql
```

Copy `dbms_backup.sql` to the server (`scp ... :~/`). If the source is **MySQL 8**
and the server is **MariaDB**, clean the dump first (removes MySQL-8-only
functional indexes that MariaDB rejects):

```bash
cd ~
python3 - <<'PY'
import re, pathlib
p = pathlib.Path('dbms_backup.sql')
t = p.read_text(encoding='utf-8', errors='replace')
out = [ln for ln in t.split('\n')
       if not re.match(r'(?i)^\s*(UNIQUE KEY|KEY|INDEX|FULLTEXT KEY|SPATIAL KEY)\b.*\(\(', ln)]
t = '\n'.join(out)
t = re.sub(r',(\s*\n\s*\)\s*ENGINE=)', r'\1', t)
t = t.replace('utf8mb4_0900_ai_ci', 'utf8mb4_unicode_ci')
pathlib.Path('dbms_fixed.sql').write_text(t, encoding='utf-8')
print('OK -> dbms_fixed.sql')
PY
```

Import into a clean `dbms`:
```bash
sudo systemctl stop vault
sudo mysql -e "DROP DATABASE IF EXISTS dbms; CREATE DATABASE dbms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql dbms < dbms_fixed.sql
sudo systemctl start vault
```

> On Ubuntu, MariaDB root logs in with **`sudo mysql`** (no `-u root -p`).

### b) Saved config files (`data/backups/`)

These are `.txt` files **on disk**, not in the database. Copy the old
`data/backups/` into `/opt/vault/data/backups/`:

```bash
sudo cp -r /home/bdren/BdREN-VAULT/data/backups/. /opt/vault/data/backups/
sudo chown -R vault:vault /opt/vault/data/backups
sudo systemctl restart vault
```

Check:
```bash
find /opt/vault/data/backups -name '*.txt' | wc -l
```

### c) Encryption key (`data/secret.key`)

Device SSH passwords are encrypted with this key. Bring the **old** one or the
passwords stay unreadable:

```bash
sudo cp /home/bdren/data/secret.key /opt/vault/data/secret.key
sudo chown vault:vault /opt/vault/data/secret.key
sudo chmod 600 /opt/vault/data/secret.key
sudo systemctl restart vault
```

If you don't have the old key, re-enter each device's password in the app.

---

## 5. Quick checks

```bash
systemctl status vault freeradius nginx --no-pager     # services up?
sudo journalctl -u vault -n 50 --no-pager              # app log
find /opt/vault/data/backups -name '*.txt' | wc -l     # how many saved configs
sudo mysql dbms -e "SELECT COUNT(*) FROM devices_device;"   # devices in DB
```

After any change, open the site and press **Ctrl+F5** once.
