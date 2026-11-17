#!/usr/bin/env bash
# RADIUS ports (UDP 1812, 1813) open in the firewall ONLY for the devices on RADIUS / AAA -> NAS Clients.
# After this, adding a device on NAS Clients opens RADIUS for its address at once, and removing it closes
# it again. Everything else on the internet can no longer reach FreeRADIUS at all.
#
# Usage:  sudo bash /opt/dbms/deploy/radius/enable_firewall_sync.sh      (safe to run again)
#
# Security: the sync script is installed root-owned in /usr/local/sbin (outside the application folder,
# which the app's own user can write), and sudo lets the app run exactly that file with NO arguments.
# The script reads the addresses itself from the database, so the web application can never pick a rule.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/dbms}"; ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
SRC="$APP_DIR/deploy/radius/dbms-radius-firewall"
DEST=/usr/local/sbin/dbms-radius-firewall
SUDOERS=/etc/sudoers.d/dbms-firewall
ok()   { printf '\033[1;32m OK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo:  sudo bash $0"
[ -f "$SRC" ] || die "$SRC not found (install the new package first)"
[ -f "$ENV_FILE" ] || die "$ENV_FILE not found"
command -v python3 >/dev/null || die "python3 is needed"
SVC_USER="${SVC_USER:-$(stat -c %U "$ENV_FILE")}"
id "$SVC_USER" >/dev/null 2>&1 || die "user $SVC_USER not found"

# RADIUS database login from .env (read as text, never executed), copied into a root-only file so the
# sync script never depends on a file the app's own user can change
envv() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r' | sed -E "s/^[\"'](.*)[\"']$/\1/"; }
RDB="$(envv RADIUS_DB_NAME)";      RDB="${RDB:-radius}"
RUSER="$(envv RADIUS_DB_USER)";    RUSER="${RUSER:-radius}"
RPASS="$(envv RADIUS_DB_PASSWORD)"
RHOST="$(envv RADIUS_DB_HOST)";    RHOST="${RHOST:-localhost}"
RPORT="$(envv RADIUS_DB_PORT)";    RPORT="${RPORT:-3306}"
[[ "$RDB" =~ ^[A-Za-z0-9_]+$ ]]       || die "RADIUS_DB_NAME in $ENV_FILE is not a plain database name"
[[ "$RUSER" =~ ^[A-Za-z0-9_.@-]+$ ]]  || die "RADIUS_DB_USER in $ENV_FILE has unexpected characters"
[[ "$RHOST" =~ ^[A-Za-z0-9_.:-]+$ ]]  || die "RADIUS_DB_HOST in $ENV_FILE has unexpected characters"
[[ "$RPORT" =~ ^[0-9]+$ ]]            || die "RADIUS_DB_PORT in $ENV_FILE is not a number"
case "$RPASS" in *\"*|*\\*) die "RADIUS_DB_PASSWORD contains \" or \\, which a MySQL option file cannot hold";; esac

CNF_DIR=/etc/dbms; CNF="$CNF_DIR/radius-firewall.cnf"
install -d -m 700 -o root -g root "$CNF_DIR"
tmp="$(mktemp)"; chmod 600 "$tmp"
printf '[client]\nuser="%s"\npassword="%s"\nhost="%s"\nport=%s\n' "$RUSER" "$RPASS" "$RHOST" "$RPORT" > "$tmp"
install -m 600 -o root -g root "$tmp" "$CNF"; rm -f "$tmp"
if mysql --defaults-extra-file="$CNF" -N -B -e "SELECT COUNT(*) FROM \`$RDB\`.nas" >/dev/null 2>&1; then
  ok "the sync can read NAS Clients (database '$RDB' as '$RUSER')"
elif mysql -u root -N -B -e "SELECT COUNT(*) FROM \`$RDB\`.nas" >/dev/null 2>&1; then
  rm -f "$CNF"; ok "the sync can read NAS Clients (database '$RDB' as the MariaDB root user)"
else
  rm -f "$CNF"
  die "cannot read the nas table of database '$RDB' with the RADIUS_DB_* settings in $ENV_FILE (nothing was changed)"
fi

# 1. the sync script, root-owned
tmp="$(mktemp)"; sed "s/@RADIUS_DB@/$RDB/" "$SRC" > "$tmp"
install -m 755 -o root -g root "$tmp" "$DEST"; rm -f "$tmp"
ok "installed $DEST"

# 2. sudo permission for exactly that file, without arguments ("" = no arguments allowed)
tmp="$(mktemp)"; printf '# BdREN VAULT: keep RADIUS open in ufw only for NAS Clients (deploy/radius/enable_firewall_sync.sh)\n%s ALL=(root) NOPASSWD: %s ""\n' "$SVC_USER" "$DEST" > "$tmp"
visudo -cf "$tmp" >/dev/null || { rm -f "$tmp"; die "sudoers check failed; nothing changed"; }
install -m 440 -o root -g root "$tmp" "$SUDOERS"; rm -f "$tmp"
ok "the app ($SVC_USER) may run the sync after NAS changes"

# 3. tell the app to run it
if grep -qE '^RADIUS_FIREWALL_CMD=' "$ENV_FILE"; then
  sed -i "s|^RADIUS_FIREWALL_CMD=.*|RADIUS_FIREWALL_CMD=sudo -n $DEST|" "$ENV_FILE"
else
  printf 'RADIUS_FIREWALL_CMD=sudo -n %s\n' "$DEST" >> "$ENV_FILE"
fi
ok "the app keeps the firewall in step with NAS Clients"

# 4. first sync now
if ufw status 2>/dev/null | grep -q "Status: active"; then
  "$DEST"
  echo; ufw status | grep -E '1812|1813' || true
else
  warn "ufw is not active, so nothing is filtered yet. Rules are added automatically once you run: sudo ufw enable"
  warn "(allow SSH first so you do not lock yourself out:  sudo ufw allow OpenSSH)"
fi
systemctl is-active --quiet dbms && systemctl restart dbms && ok "application restarted"
printf '\nDone. Add or remove a device on NAS Clients: its RADIUS access in the firewall follows within seconds.\n'
