#!/usr/bin/env bash
# Point FreeRADIUS at its MySQL / MariaDB database.
#
# It writes the FreeRADIUS "sql" module from the RADIUS_DB_* settings in .env (so the password is filled
# in automatically), enables it, and - unless the caller handles the restart - restarts FreeRADIUS.
#
# Why this file exists: the FreeRADIUS package ships an "sql" module with a mysql TLS block
# (tls_required = yes) that blocks a plain local connection, so FreeRADIUS cannot reach its database and
# device logins fail. This writes VAULT's own module (no TLS block, read_clients from the "nas" table).
#
# deploy/install.sh runs this automatically. You can also run it on its own at any time:
#     sudo bash /opt/dbms/deploy/radius/setup_sql.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/dbms}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
R="${RAD_DIR:-/etc/freeradius/3.0}"
ok()   { printf '\033[1;32m OK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo:  sudo bash $0"
[ -f "$ENV_FILE" ] || die "$ENV_FILE not found"
[ -d "$R" ] || die "FreeRADIUS folder $R not found (is FreeRADIUS installed?)"

# read a value from .env the same way the app does (strip CR, strip surrounding quotes)
envv() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '\r' | sed -E "s/^[\"'](.*)[\"']\$/\1/"; }
RDB="$(envv RADIUS_DB_NAME)";   RDB="${RDB:-radius}"
RUSER="$(envv RADIUS_DB_USER)"; RUSER="${RUSER:-radius}"
RPASS="$(envv RADIUS_DB_PASSWORD)"
RHOST="$(envv RADIUS_DB_HOST)"; RHOST="${RHOST:-localhost}"
RPORT="$(envv RADIUS_DB_PORT)"; RPORT="${RPORT:-3306}"
[ -n "$RPASS" ] && [ "$RPASS" != "change-me" ] || die "RADIUS_DB_PASSWORD is not set in $ENV_FILE"
case "$RPASS" in *\"*|*\\*) die "RADIUS_DB_PASSWORD has a \" or \\ that a FreeRADIUS config cannot hold; change it";; esac

STAMP="$(date +%Y%m%d-%H%M%S)"
[ -f "$R/mods-available/sql" ] && cp -p "$R/mods-available/sql" "$R/mods-available/sql.bak-$STAMP"
cat > "$R/mods-available/sql" <<CONF
# Written by VAULT deploy/radius/setup_sql.sh ($STAMP)
sql {
	dialect = "mysql"
	driver = "rlm_sql_mysql"
	mysql {
		warnings = auto
	}
	server = "$RHOST"
	port = $RPORT
	login = "$RUSER"
	password = "$RPASS"
	radius_db = "$RDB"
	acct_table1 = "radacct"
	acct_table2 = "radacct"
	postauth_table = "radpostauth"
	authcheck_table = "radcheck"
	groupcheck_table = "radgroupcheck"
	authreply_table = "radreply"
	groupreply_table = "radgroupreply"
	usergroup_table = "radusergroup"
	delete_stale_sessions = yes
	pool {
		start = \${thread[pool].start_servers}
		min = \${thread[pool].min_spare_servers}
		max = \${thread[pool].max_servers}
		spare = \${thread[pool].max_spare_servers}
		uses = 0
		retry_delay = 30
		lifetime = 0
		idle_timeout = 60
	}
	# NAS clients come from the "nas" table (RADIUS / AAA -> NAS Clients)
	read_clients = yes
	client_table = "nas"
	group_attribute = "\${.:instance}-SQL-Group"
	\$INCLUDE \${modconfdir}/\${.:name}/main/\${dialect}/queries.conf
}
CONF
chown root:freerad "$R/mods-available/sql" 2>/dev/null || true
chmod 640 "$R/mods-available/sql"
ln -sf ../mods-available/sql "$R/mods-enabled/sql"
ok "sql module written for database '$RDB' as '$RUSER' on $RHOST:$RPORT (TLS block removed)"

# The caller (install.sh) restarts FreeRADIUS itself; set SETUP_SQL_NO_RESTART=1 to skip it here.
if [ "${SETUP_SQL_NO_RESTART:-0}" = 1 ]; then
  exit 0
fi
CHK=radiusd; command -v freeradius >/dev/null 2>&1 && CHK=freeradius
if "$CHK" -C >/dev/null 2>&1; then
  systemctl restart freeradius 2>/dev/null || systemctl restart radiusd 2>/dev/null || true
  ok "FreeRADIUS restarted and connected to its database"
else
  warn "FreeRADIUS did not accept the configuration. See the details with:  sudo $CHK -XC"
  warn "Common causes: the radius database or its tables are missing, or RADIUS_DB_PASSWORD in .env does not match the MySQL user."
  exit 1
fi
