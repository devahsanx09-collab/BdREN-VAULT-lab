# Deploy

The same installer sets up a new Ubuntu / Debian server and updates an existing one.

## New server

```bash
unzip -q BdREN-VAULT.zip -d /tmp/dbms-new
sudo bash /tmp/dbms-new/vault/deploy/install.sh
```

It asks for the address people will use, the first administrator, and whether to install FreeRADIUS and HTTPS
(both default to yes), then installs everything: Python packages, MariaDB and both databases, FreeRADIUS with
the DBMS policies, nginx on HTTPS, the `dbms` service and a final health check. Passwords it generates are
stored only in `/opt/vault/.env`.

## Update (3 commands)

```bash
rm -rf /tmp/dbms-new && unzip -q -o ~/BdREN-VAULT.zip -d /tmp/dbms-new
sudo SVC_USER="$(systemctl show -p User --value vault || echo vault)" bash /tmp/dbms-new/vault/deploy/install.sh
sudo bash /opt/vault/deploy/radius/check_levels.sh
```

The update keeps `.env`, `data/` (backups, `secret.key`) and the databases; replaces the program files exactly
(removes files that no longer exist), migrates the database, refreshes the RADIUS level attributes and restarts.
The previous version is saved in `/var/backups/vault/` and restored automatically if anything fails. Then open
the site and press **Ctrl+F5** once.

## Domain name

```bash
sudo bash /opt/vault/deploy/set-domain.sh backup.example.com you@example.com
```

Needs a DNS A record to the server and ports 80 / 443 open. Issues a Let's Encrypt certificate (renewed
automatically) and keeps the IP address working.

## Checks

| What | Command |
|---|---|
| Service running | `systemctl status vault freeradius nginx --no-pager` |
| Application log | `sudo journalctl -u vault -n 100 --no-pager` |
| Health check | `curl -k https://127.0.0.1/healthz` → `{"status": "ok"}` |
| RADIUS users get the right level | `sudo bash /opt/vault/deploy/radius/check_levels.sh` |
| FreeRADIUS has room for a big backup run | `sudo bash /opt/vault/deploy/radius/check_capacity.sh` |
| FreeRADIUS configuration | `sudo freeradius -XC` |

## Back up the server (disaster recovery)

```bash
sudo bash /opt/vault/deploy/backup_vault.sh
```

Dumps both databases (`dbms`, `radius`) and copies `secret.key` / `session.key` / the SSH host-key files into
`/var/backups/vault-dr/` (add `--with-configs` to also include the saved device configuration backups). Keeps the
newest 14 days there and prints what to do next. **This alone is not enough**: that directory is on the same
disk as everything else, so copy it to another machine or off-site storage too (the script's own output shows
an `rsync` example), and add it to root's crontab for a backup every night without having to remember. Without
`secret.key`, every saved device password becomes permanently unreadable - there is no way to "reset" it.
