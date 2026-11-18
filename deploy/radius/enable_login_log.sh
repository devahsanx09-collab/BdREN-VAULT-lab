#!/usr/bin/env bash
# Record WHICH DEVICE every RADIUS login came from, so the Authentication Audit page can show
# "user X logged in on device Y".
#
# FreeRADIUS's standard radpostauth table stores only username, result and time. This script:
#   1. adds two columns to radpostauth: nasipaddress (device IP) and nasidentifier (device name it sends)
#   2. changes ONLY the "post-auth" query of FreeRADIUS's SQL module so it fills those two columns
#      (device IP = NAS-IP-Address, or the packet's source address when the device does not send it)
#   3. checks the FreeRADIUS configuration; if the check fails the original file is put back
#   4. restarts FreeRADIUS
#
# Safe to run more than once (it does nothing when already done). Logins recorded BEFORE this script
# ran have no device; every login after it does.
#
# Usage:   sudo bash /opt/vault/deploy/radius/enable_login_log.sh
#          (reads RADIUS_DB_* from /opt/vault/.env; set ENV_FILE=/path/.env to use another file)
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/vault/.env}"
say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m OK\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo:  sudo bash $0"
[ -r "$ENV_FILE" ] || die "Cannot read $ENV_FILE (set ENV_FILE=/path/to/.env)"
command -v mysql >/dev/null || die "The mysql client is not installed (apt install mariadb-client or mysql-client)"
command -v perl  >/dev/null || die "perl is required"

env_get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+|[[:space:]]+$//g' -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }
DB_NAME="$(env_get RADIUS_DB_NAME)"; DB_NAME="${DB_NAME:-radius}"
DB_USER="$(env_get RADIUS_DB_USER)"; DB_USER="${DB_USER:-radius}"
DB_PASS="$(env_get RADIUS_DB_PASSWORD)"
DB_HOST="$(env_get RADIUS_DB_HOST)"; DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="$(env_get RADIUS_DB_PORT)"; DB_PORT="${DB_PORT:-3306}"
[ -n "$DB_PASS" ] || die "RADIUS_DB_PASSWORD is empty in $ENV_FILE"

# password in a private temp file, never on the command line
MYCNF="$(mktemp)"; chmod 600 "$MYCNF"; trap 'rm -f "$MYCNF"' EXIT
printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' "$DB_USER" "$DB_PASS" "$DB_HOST" "$DB_PORT" > "$MYCNF"
sql() { mysql --defaults-extra-file="$MYCNF" -N -B "$DB_NAME" -e "$1"; }

# ---- 1. database columns ----------------------------------------------------------------------
say "Checking the radpostauth table in database '$DB_NAME'"
sql "SELECT 1 FROM radpostauth LIMIT 1" >/dev/null || die "Cannot read radpostauth (wrong database or permissions?)"
has_col() { [ "$(sql "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='radpostauth' AND column_name='$1'")" = "1" ]; }
if has_col nasipaddress; then ok "column nasipaddress already exists"
else sql "ALTER TABLE radpostauth ADD COLUMN nasipaddress VARCHAR(45) NOT NULL DEFAULT ''"; ok "added column nasipaddress"; fi
if has_col nasidentifier; then ok "column nasidentifier already exists"
else sql "ALTER TABLE radpostauth ADD COLUMN nasidentifier VARCHAR(64) NOT NULL DEFAULT ''"; ok "added column nasidentifier"; fi
if [ "$(sql "SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='radpostauth' AND index_name='dbms_nasip'")" = "0" ]; then
  sql "CREATE INDEX dbms_nasip ON radpostauth (nasipaddress)"; ok "added an index for searching by device"
fi

# ---- 2. FreeRADIUS post-auth query --------------------------------------------------------------
QUERIES=""
for f in /etc/freeradius/3.0/mods-config/sql/main/mysql/queries.conf \
         /etc/freeradius/mods-config/sql/main/mysql/queries.conf \
         /etc/raddb/mods-config/sql/main/mysql/queries.conf; do
  [ -f "$f" ] && { QUERIES="$f"; break; }
done
[ -n "$QUERIES" ] || die "FreeRADIUS mysql queries.conf not found"
say "FreeRADIUS query file: $QUERIES"

if grep -q "nasipaddress" "$QUERIES"; then
  ok "post-auth query already records the device"
  CHANGED=0
else
  BACKUP="$QUERIES.dbms-backup-$(date +%Y%m%d-%H%M%S)"
  cp -p "$QUERIES" "$BACKUP"; ok "backup saved: $BACKUP"
  # Only inside the post-auth { ... } block: add the two columns after "authdate", and their values
  # right after the authdate value ('%S' or '%S.%M'), so they stay in the same order (class comes last).
  perl -0pi -e '
    s{(\npost-auth\s*\{.*?\n\})}{
      my $b = $1;
      my $c = ($b =~ s/(\(\s*username\s*,\s*pass\s*,\s*reply\s*,\s*authdate)/$1, nasipaddress, nasidentifier/);
      my $v = ($b =~ s/(\x27%S(?:\.%M)?\x27)/$1, \x27%{%{NAS-IP-Address}:-%{Packet-Src-IP-Address}}\x27, \x27%{NAS-Identifier}\x27/);
      $b .= "\n# DBMS_PATCH_INCOMPLETE" unless $c && $v;
      $b;
    }se;
  ' "$QUERIES"
  if grep -q "DBMS_PATCH_INCOMPLETE" "$QUERIES" || ! grep -q "nasipaddress" "$QUERIES"; then
    cp -p "$BACKUP" "$QUERIES"
    die "This FreeRADIUS version's post-auth query has an unexpected format; nothing was changed.
       Edit $QUERIES by hand: add 'nasipaddress, nasidentifier' after 'authdate' in the column list of
       the post-auth query, and add  , '%{%{NAS-IP-Address}:-%{Packet-Src-IP-Address}}', '%{NAS-Identifier}'
       right after the authdate value ('%S' or '%S.%M')."
  fi
  ok "post-auth query now records the device IP and identifier"
  CHANGED=1
fi

# ---- 3. check the configuration, then restart ---------------------------------------------------
RADIUSD="$(command -v freeradius || command -v radiusd || true)"
[ -n "$RADIUSD" ] || die "freeradius binary not found"
say "Checking the FreeRADIUS configuration"
if ! "$RADIUSD" -C >/tmp/dbms-radius-check.log 2>&1; then
  if [ "${CHANGED}" = "1" ]; then cp -p "$BACKUP" "$QUERIES"; fi
  die "FreeRADIUS configuration check failed (see /tmp/dbms-radius-check.log). The original file was restored."
fi
ok "configuration is valid"
if [ "${CHANGED}" = "1" ]; then
  say "Restarting FreeRADIUS"
  systemctl restart freeradius 2>/dev/null || systemctl restart radiusd
  ok "FreeRADIUS restarted"
fi
echo
ok "Done. New logins are recorded with their device. Open RADIUS / AAA -> Authentication Audit."
