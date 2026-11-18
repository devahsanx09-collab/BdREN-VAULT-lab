#!/usr/bin/env bash
# Completely remove VAULT from this server: the app, its service, the nginx site, the two databases and the
# FreeRADIUS configuration VAULT added. Use it to decommission a server, or to start a clean install again.
#
#   sudo bash /opt/vault/deploy/uninstall.sh          # asks you to confirm
#   sudo bash /opt/vault/deploy/uninstall.sh --yes    # no prompt
#
# WARNING: this DELETES the databases (backups, users, RADIUS data) and the encryption key. It cannot be
# undone. Only run it when you do not need any of that data.
set -u
APP_DIR="${APP_DIR:-/opt/vault}"; SVC_USER="${SVC_USER:-vault}"
RAD_DIR=/etc/freeradius/3.0
YES=0; [ "${1:-}" = "--yes" ] && YES=1
c_r='\033[1;31m'; c_g='\033[1;32m'; c_0='\033[0m'
ok(){ printf "${c_g} OK${c_0} %s\n" "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo:  sudo bash $0"; exit 1; }

envv(){ [ -f "$APP_DIR/.env" ] && grep -E "^$1=" "$APP_DIR/.env" | tail -n1 | cut -d= -f2- | tr -d '\r' | sed -E "s/^[\"'](.*)[\"']\$/\1/"; }
DBN="$(envv DBMS_DB_NAME)";   DBN="${DBN:-dbms}";   DBU="$(envv DBMS_DB_USER)";   DBU="${DBU:-dbms}"
RDB="$(envv RADIUS_DB_NAME)"; RDB="${RDB:-radius}"; RUSER="$(envv RADIUS_DB_USER)"; RUSER="${RUSER:-radius}"

if [ "$YES" != 1 ]; then
  printf "${c_r}This permanently DELETES:${c_0}\n"
  printf "  - %s  (app, .env, data, backups, encryption key)\n" "$APP_DIR"
  printf "  - databases '%s' and '%s' (and their MySQL users)\n" "$DBN" "$RDB"
  printf "  - the dbms service, the nginx site, and VAULT's FreeRADIUS config\n"
  read -r -p "Type REMOVE to continue: " a
  [ "$a" = "REMOVE" ] || { echo "cancelled."; exit 0; }
fi

for s in vault dbms; do systemctl stop "$s" 2>/dev/null; systemctl disable "$s" 2>/dev/null; done
rm -f /etc/systemd/system/vault.service /etc/systemd/system/vault.service; systemctl daemon-reload 2>/dev/null; ok "service removed"

mysql -u root -e "DROP DATABASE IF EXISTS \`$DBN\`; DROP DATABASE IF EXISTS \`$RDB\`; DROP USER IF EXISTS '$DBU'@'localhost'; DROP USER IF EXISTS '$RUSER'@'localhost'; FLUSH PRIVILEGES;" 2>/dev/null \
  && ok "databases '$DBN' and '$RDB' dropped" || echo "  ! could not drop databases (try: sudo mysql)"

rm -f /etc/nginx/sites-enabled/dbms /etc/nginx/sites-available/dbms; rm -rf /etc/ssl/dbms
systemctl reload nginx 2>/dev/null || true; ok "nginx site removed"

# FreeRADIUS: remove the parts VAULT added (FreeRADIUS itself stays installed)
rm -f "$RAD_DIR/mods-enabled/sql"
rm -f "$RAD_DIR/policy.d/dbms_device_limit" "$RAD_DIR/policy.d/dbms_huawei_levels"
rm -f "$RAD_DIR/sites-enabled/dbms_dynamic_clients" "$RAD_DIR/sites-available/dbms_dynamic_clients"
rm -f /etc/sudoers.d/vault-radius /etc/sudoers.d/vault-firewall /usr/local/sbin/vault-radius-firewall
rm -rf /etc/vault
systemctl restart freeradius 2>/dev/null || true; ok "VAULT's FreeRADIUS config removed"

rm -rf "$APP_DIR"; userdel "$SVC_USER" 2>/dev/null || true; ok "application files and the $SVC_USER user removed"

printf "\n${c_g}Done.${c_0} VAULT is removed. For a clean install again:\n"
printf "  unzip -o ~/BdREN-VAULT.zip -d /tmp && sudo bash /tmp/vault/deploy/install.sh\n"
