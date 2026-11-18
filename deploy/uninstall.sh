#!/usr/bin/env bash
# =====================================================================================================
#  VAULT - remove EVERYTHING deploy/install.sh put on this server (Ubuntu / Debian)
#
#     sudo bash deploy/uninstall.sh          (asks you to type REMOVE first)
#     sudo bash deploy/uninstall.sh --yes    (no question)
#
#  Removes: the dbms service and program files (/opt/dbms), the dbms system user, MariaDB with ALL its
#  databases (dbms + radius), FreeRADIUS, nginx, certbot, the certificates, the sudo rules, the RADIUS
#  firewall helper, the backups in /var/backups/dbms, the install logs and the ufw rules.
#  Kept: python3, rsync, curl, openssl, git (the system needs them) and this downloaded code folder.
#  THIS CANNOT BE UNDONE. Copy anything you want to keep first.
# =====================================================================================================
set -uo pipefail

APP_DIR="${APP_DIR:-/opt/dbms}"; SVC_USER="${SVC_USER:-dbms}"
c_b='\033[1;34m'; c_g='\033[1;32m'; c_r='\033[1;31m'; c_0='\033[0m'
step() { printf "\n${c_b}==> %s${c_0}\n" "$*"; }
ok()   { printf "${c_g}  ✓${c_0} %s\n" "$*"; }

[ "$(id -u)" -eq 0 ] || { printf "${c_r}ERROR:${c_0} run it with sudo:  sudo bash %s\n" "$0" >&2; exit 1; }

if [ "${1:-}" != "--yes" ]; then
  printf "${c_r}This deletes VAULT, ALL its databases, FreeRADIUS, MariaDB, nginx and every backup.${c_0}\n"
  a=""; read -r -p "  Type REMOVE to continue: " a || true
  [ "$a" = "REMOVE" ] || { echo "  Nothing was changed."; exit 1; }
fi

step "Services"
for s in dbms freeradius nginx mariadb mysql; do systemctl disable --now "$s" >/dev/null 2>&1 || true; done
rm -f /etc/systemd/system/dbms.service; systemctl daemon-reload
ok "services stopped and disabled"

step "Packages"
PKGS=(freeradius freeradius-mysql freeradius-utils freeradius-common freeradius-config
      mariadb-server mariadb-client mariadb-common mysql-common
      nginx nginx-common nginx-core certbot python3-certbot-nginx python3-venv python3-pip)
have=(); for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 && have+=("$p"); done
if [ ${#have[@]} -gt 0 ]; then
  DEBIAN_FRONTEND=noninteractive apt-get purge -y -qq "${have[@]}" >/dev/null 2>&1 || true
  DEBIAN_FRONTEND=noninteractive apt-get autoremove --purge -y -qq >/dev/null 2>&1 || true
  ok "removed: ${have[*]}"
else ok "no VAULT packages installed"; fi

step "Files"
rm -rf "$APP_DIR" /etc/dbms \
       /etc/freeradius /etc/mysql /var/lib/mysql /var/log/mysql \
       /etc/nginx /var/log/nginx /etc/letsencrypt /var/lib/letsencrypt \
       /etc/ssl/dbms /etc/ssl/certs/dbms.crt /etc/ssl/private/dbms.key \
       /etc/sudoers.d/dbms-radius /etc/sudoers.d/dbms-firewall /usr/local/sbin/dbms-radius-firewall \
       /var/backups/dbms /var/log/freeradius
rm -f /var/log/dbms-install-*.log
ok "program files, databases, configuration, certificates, backups and logs deleted"

step "System user"
userdel -r "$SVC_USER" >/dev/null 2>&1 || true; groupdel "$SVC_USER" >/dev/null 2>&1 || true
ok "user $SVC_USER removed"

step "Firewall (ufw)"
if command -v ufw >/dev/null 2>&1; then ufw --force reset >/dev/null 2>&1 || true; ok "ufw rules cleared and ufw turned off (SSH stays reachable)"
else ok "ufw not installed"; fi

step "Check"
left="$(dpkg -l 2>/dev/null | awk '/^ii/{print $2}' | grep -E '^(freeradius|mariadb|nginx|certbot)' || true)"
for d in "$APP_DIR" /etc/freeradius /var/lib/mysql /etc/nginx /var/backups/dbms; do [ -e "$d" ] && left+=" $d"; done
if [ -z "${left// /}" ]; then ok "nothing of VAULT is left on this server"
else printf "${c_r}  still present:${c_0} %s\n" "$left"; fi

printf "\nDone. To install again:  sudo bash %s/install.sh\n" "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
