#!/usr/bin/env bash
# Switches added on RADIUS / AAA -> NAS Clients work IMMEDIATELY, without restarting FreeRADIUS.
#
# Why: FreeRADIUS reads the switch list only when it starts, so the app used to restart it after every
# switch added. During that second the switches get no answer, and many then ignore the RADIUS server
# for minutes ("dead time"). With this, an unknown switch is looked up in the database the moment its
# first request arrives (deploy/radius/dbms_dynamic_clients), and the app no longer restarts FreeRADIUS
# when a switch is added. Switches FreeRADIUS already knows keep working exactly as before.
#
# Usage:  sudo bash /opt/vault/deploy/radius/enable_dynamic_clients.sh      (safe to run again)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vault}"; ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
R=/etc/freeradius/3.0
ok()   { printf '\033[1;32m OK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo:  sudo bash $0"
[ -d "$R" ] || die "FreeRADIUS configuration folder $R not found"
[ -e "$R/mods-enabled/sql" ] || die "The FreeRADIUS sql module is not enabled; the switch list cannot be read from the database"
SRC="$APP_DIR/deploy/radius/dbms_dynamic_clients"; [ -f "$SRC" ] || die "$SRC not found (install the new package first)"

B="/var/backups/vault/freeradius-before-dynamic-$(date +%Y%m%d-%H%M%S).tar.gz"
mkdir -p /var/backups/vault; chmod 700 /var/backups/vault
tar -czf "$B" -C /etc freeradius; ok "FreeRADIUS configuration saved: $B"
restore() { rm -rf /etc/freeradius && tar -xzf "$B" -C /etc; systemctl restart freeradius || true; warn "previous FreeRADIUS configuration restored"; }

install -m 640 -o root -g freerad "$SRC" "$R/sites-available/dbms_dynamic_clients"
ln -sf ../sites-available/dbms_dynamic_clients "$R/sites-enabled/dbms_dynamic_clients"
if ! grep -q "dynamic_clients = dbms_dynamic_clients" "$R/clients.conf"; then
  cat >> "$R/clients.conf" <<'CONF'

# BdREN VAULT: any address not listed above is looked up in the "nas" table
# (RADIUS / AAA -> NAS Clients) when its first request arrives. Unknown addresses are ignored.
client dbms_dynamic {
	ipaddr = 0.0.0.0/0
	dynamic_clients = dbms_dynamic_clients
	lifetime = 60
}
CONF
fi
ok "new switches are looked up in NAS Clients on their first request"

if ! freeradius -C >/tmp/dbms-dynamic-check.log 2>&1; then
  restore; die "FreeRADIUS rejected the configuration (see /tmp/dbms-dynamic-check.log). Nothing was changed."
fi
systemctl restart freeradius
sleep 2
systemctl is-active --quiet freeradius || { restore; die "FreeRADIUS did not start; previous configuration restored."; }
ok "FreeRADIUS restarted (the last restart needed for adding switches)"

# tell the app: adding a switch needs no restart any more
if [ -f "$ENV_FILE" ]; then
  if grep -qE '^RADIUS_DYNAMIC_CLIENTS=' "$ENV_FILE"; then sed -i 's/^RADIUS_DYNAMIC_CLIENTS=.*/RADIUS_DYNAMIC_CLIENTS=1/' "$ENV_FILE"
  else printf 'RADIUS_DYNAMIC_CLIENTS=1\n' >> "$ENV_FILE"; fi
  systemctl is-active --quiet vault && systemctl restart vault
  ok "the application no longer restarts FreeRADIUS when a switch is added"
fi

# a "cache" in authorize would make new users / changes appear only after it expires
if awk '/^authorize[ \t]*\{/{a=1} a&&/^[ \t]*-?cache([_a-z]*)?[ \t]*$/{f=1} a&&/^\}/{a=0} END{exit !f}' "$(readlink -f "$R/sites-enabled/default")"; then
  warn "a 'cache' module is used in authorize { } of sites-enabled/default: new users may need until it expires"
fi
printf '\nDone. Add a switch on NAS Clients: it can log users in at once.\n'
