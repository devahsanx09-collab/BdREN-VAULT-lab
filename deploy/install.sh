#!/usr/bin/env bash
# =====================================================================================================
#  VAULT - ONE command to install or update (Ubuntu / Debian)
#
#     1. get the code:  git clone <your-repo> dbms      (or unzip the release package)
#     2. sudo bash dbms/deploy/install.sh
#
#  A fresh clone has NO secrets in it (.env and data/ are git-ignored). This script asks for the few
#  things it needs - the browser address, the database password (press Enter to generate one) and the
#  first administrator - then installs Python packages, MariaDB and the application database, FreeRADIUS
#  with its MySQL database, the service and everything else. Nothing to edit by hand.
#  Existing server: keeps .env, the database, the backups (data/) and the logs; replaces the program
#  files exactly (old leftover files are removed, so no stale migrations), migrates the database and
#  restarts. If the database migration fails, the previous version is put back automatically.
#
#  Also done automatically when it applies: RADIUS tables + "which device" login logging, the sudo rule
#  that lets the app restart FreeRADIUS, and the nginx lines that pass the real visitor IP.
#  One command, one click: on a fresh install it asks its few questions once, all together at the
#  start, then installs the whole project without stopping again.
#  Safe to run again at any time.  Options:  --yes  (no questions; defaults everywhere)
# =====================================================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/dbms}"; export APP_DIR      # also used by the helper scripts in deploy/radius
SVC_USER="${SVC_USER:-dbms}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSUME_YES=0; [ "${1:-}" = "--yes" ] && ASSUME_YES=1
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_ROOT="/var/backups/dbms"
LOG="/var/log/dbms-install-$STAMP.log"

c_b='\033[1;34m'; c_g='\033[1;32m'; c_y='\033[1;33m'; c_r='\033[1;31m'; c_0='\033[0m'
step() { printf "\n${c_b}==> %s${c_0}\n" "$*"; }
ok()   { printf "${c_g}  ✓${c_0} %s\n" "$*"; }
warn() { printf "${c_y}  !${c_0} %s\n" "$*"; }
die()  { printf "\n${c_r}ERROR:${c_0} %s\n(full log: %s)\n" "$*" "$LOG" >&2; exit 1; }
ask()  { # ask "Question" "default" -> echo answer
  local q="$1" d="${2:-}" a=""
  if [ "$ASSUME_YES" = 1 ] || [ ! -t 0 ]; then echo "$d"; return; fi
  read -r -p "  $q${d:+ [$d]}: " a || true; echo "${a:-$d}"; }
ask_secret() {
  local q="$1" a="" b=""
  while :; do
    read -r -s -p "  $q: " a; echo >&2
    [ "${#a}" -ge 12 ] || { echo "  Use at least 12 characters." >&2; continue; }
    read -r -s -p "  Type it again: " b; echo >&2
    [ "$a" = "$b" ] && { echo "$a"; return; } || echo "  The two entries are different." >&2
  done; }
gen_password() { head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32; }
ask_db_password() { # the password the user chooses for the database, or a strong generated one when left empty
  local a="" b=""
  if [ "$ASSUME_YES" = 1 ] || [ ! -t 0 ]; then gen_password; return; fi
  while :; do
    read -r -s -p "  Database password (press Enter to generate a strong one): " a; echo >&2
    [ -z "$a" ] && { gen_password; return; }
    if ! printf '%s' "$a" | grep -qE '^[A-Za-z0-9._@%+=-]{8,}$'; then
      echo "  Use at least 8 of: letters, digits and . _ @ % + = -  (or press Enter to generate one)." >&2; continue
    fi
    read -r -s -p "  Type it again: " b; echo >&2
    [ "$a" = "$b" ] && { printf '%s' "$a"; return; } || echo "  The two entries are different." >&2
  done; }
# same rules as the app's .env loader (config/settings.py): quotes removed, " #..." is a comment
env_get() { [ -f "$APP_DIR/.env" ] && grep -E "^$1=" "$APP_DIR/.env" | tail -n1 | cut -d= -f2- | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+|[[:space:]]+$//g' -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }
env_set() { # env_set KEY VALUE  (replace the line, or append it)
  if grep -qE "^$1=" "$APP_DIR/.env"; then sed -i "s|^$1=.*|$1=$2|" "$APP_DIR/.env"
  else printf '%s=%s\n' "$1" "$2" >> "$APP_DIR/.env"; fi; }
as_app() { sudo -u "$SVC_USER" -H "$@"; }
py() { as_app "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" "$@"; }

[ "$(id -u)" -eq 0 ] || { echo "Run it with sudo:  sudo bash $0"; exit 1; }
[ -f "$SRC/manage.py" ] || die "Run this script from inside the unpacked package (manage.py not found next to deploy/)."
mkdir -p "$(dirname "$LOG")"; : > "$LOG"; chmod 600 "$LOG"
exec > >(tee -a "$LOG") 2>&1

MODE=install; [ -f "$APP_DIR/manage.py" ] && MODE=update
printf "${c_b}VAULT - %s${c_0}\n" "$([ $MODE = install ] && echo "new installation in $APP_DIR" || echo "update of $APP_DIR")"

# ---- 0. one-command install: ask everything once, up front, then install without stopping ----------
# For a brand-new install on a real terminal we collect every answer here. After this, the whole
# project (database, Python, FreeRADIUS, nginx/HTTPS, service) installs on its own, no more prompts.
# Each answer falls back to its old inline question when this block is skipped (update, --yes, no TTY,
# or an existing .env), so nothing else changes.
PRE_ADDR=""; PRE_DB_PASS=""; PRE_ADMIN_USER=""; PRE_ADMIN_PASS=""
PRE_WANT_RADIUS=""; PRE_WANT_HTTPS=""; PRE_DOMAIN=""; PRE_DOMAIN_EMAIL=""; PRE_WANT_UFW=""
if [ "$MODE" = install ] && [ "$ASSUME_YES" != 1 ] && [ -t 0 ] && [ ! -f "$APP_DIR/.env" ]; then
  step "A few questions (asked once; then the whole install runs on its own)"
  ip_guess="$(hostname -I 2>/dev/null | awk '{print $1}')"
  PRE_ADDR="$(ask "Address people type in the browser (IP or domain)" "${ip_guess:-127.0.0.1}")"
  PRE_DB_PASS="$(ask_db_password)"
  PRE_ADMIN_USER="$(ask "Administrator username" "admin")"
  PRE_ADMIN_PASS="$(ask_secret "Administrator password (12+ characters)")"
  if [ "$(ask "Install FreeRADIUS (RADIUS / AAA logins for your network devices)? (y/n)" "y")" = y ]; then PRE_WANT_RADIUS=y; else PRE_WANT_RADIUS=n; fi
  if [ "$(ask "Publish the website on HTTPS with nginx (self-signed certificate)? (y/n)" "y")" = y ]; then
    PRE_WANT_HTTPS=y
    PRE_DOMAIN="$(ask "Domain name, e.g. backup.example.com (press Enter to use the IP only)" "")"
    [ -n "$PRE_DOMAIN" ] && PRE_DOMAIN_EMAIL="$(ask "Email for certificate expiry notices (Enter = none)" "")"
  else PRE_WANT_HTTPS=n; fi
  if [ "$(ask "Turn on the ufw firewall? SSH, the web and RADIUS stay open; everything else is blocked (y/n)" "y")" = y ]; then PRE_WANT_UFW=y; else PRE_WANT_UFW=n; fi
  ok "Thank you. Installing the whole project now - no more questions."
fi

# ---- 1. system packages --------------------------------------------------------------------------
step "System packages"
need=()
for p in python3 python3-venv python3-pip rsync curl; do dpkg -s "$p" >/dev/null 2>&1 || need+=("$p"); done
if [ ${#need[@]} -gt 0 ]; then
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need[@]}" >/dev/null
  ok "installed: ${need[*]}"
else ok "already installed"; fi
id "$SVC_USER" >/dev/null 2>&1 || { useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SVC_USER"; ok "created system user $SVC_USER"; }

# ---- 2. program files -----------------------------------------------------------------------------
step "Program files"
mkdir -p "$APP_DIR" "$BACKUP_ROOT"; chmod 700 "$BACKUP_ROOT"
# the data folder (backups, secret.key, sessions, SSH host keys) is never touched, also when .env moves it
# somewhere else inside the program folder with DBMS_DATA
KEEP=(--exclude='/data/'); TAR_KEEP=(--exclude=./data)
DATA_PATH="$(env_get DBMS_DATA)"
if [ -n "$DATA_PATH" ] && [[ "$DATA_PATH" == "$APP_DIR"/* ]]; then
  rel="${DATA_PATH#"$APP_DIR"/}"; rel="${rel%/}"
  KEEP+=(--exclude="/$rel/"); TAR_KEEP+=(--exclude="./$rel"); KEEP_TOP="${rel%%/*}"
  ok "data folder $DATA_PATH is kept as it is"
fi
CODE_BACKUP=""
if [ "$MODE" = update ]; then
  CODE_BACKUP="$BACKUP_ROOT/code-$STAMP.tar.gz"
  tar -C "$APP_DIR" --exclude=./.venv "${TAR_KEEP[@]}" --exclude=./logs --exclude=./staticfiles \
      --exclude='*/__pycache__' -czf "$CODE_BACKUP" . && ok "previous version saved: $CODE_BACKUP"
fi
if [ "$SRC" != "$APP_DIR" ]; then
  # exact copy of the program: files that no longer exist in the package are removed (no stale migrations);
  # .env, data/ (database, backups, keys), logs/ and the Python environment are never touched.
  rsync -a --delete \
    --exclude='/.env' "${KEEP[@]}" --exclude='/logs/' --exclude='/.venv/' --exclude='/staticfiles/' \
    --exclude='__pycache__/' --exclude='/.git/' \
    "$SRC/" "$APP_DIR/"
  ok "program files updated from $SRC"
else warn "running from $APP_DIR itself: files left as they are"; fi
mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
rollback() {
  [ -n "$CODE_BACKUP" ] || return 0
  warn "putting the previous version back"
  find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name .env ! -name data ! -name "${KEEP_TOP:-data}" ! -name logs ! -name .venv -exec rm -rf {} +
  tar -C "$APP_DIR" -xzf "$CODE_BACKUP"; chown -R "$SVC_USER:$SVC_USER" "$APP_DIR"
  systemctl restart dbms 2>/dev/null || true
  warn "previous version restored and restarted"
}

# ---- 3. settings (.env) ---------------------------------------------------------------------------
step "Settings (.env)"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  ip_guess="$(hostname -I 2>/dev/null | awk '{print $1}')"
  addr="${PRE_ADDR}"; [ -n "$addr" ] || addr="$(ask "Address people type in the browser (IP or domain)" "${ip_guess:-127.0.0.1}")"
  env_set DJANGO_ALLOWED_HOSTS "localhost,127.0.0.1,$addr"
  env_set DJANGO_CSRF_TRUSTED_ORIGINS "https://$addr,http://$addr"
  ok "created .env for $addr"
else ok "kept the existing .env"; fi
# a .env edited on Windows carries CR line endings that break shell reads of its values; strip them
sed -i 's/\r$//' "$APP_DIR/.env" 2>/dev/null || true

# database (MariaDB / MySQL on this server) for a new installation
env_set DBMS_DB_ENGINE mysql                      # VAULT uses MySQL / MariaDB only
  DB_PASS="$(env_get DBMS_DB_PASSWORD)"
  if [ -z "$DB_PASS" ] || [ "$DB_PASS" = "change-me" ]; then
    if ! command -v mysql >/dev/null 2>&1 || ! systemctl list-unit-files 2>/dev/null | grep -qE '^(mariadb|mysql)\.service'; then
      if [ -z "$PRE_ADDR" ] && [ "$(ask "No database server found. Install MariaDB on this server? (y/n)" "y")" != y ]; then die "Set DBMS_DB_* in $APP_DIR/.env for your database server, then run this script again."; fi
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq mariadb-server >/dev/null; systemctl enable --now mariadb >/dev/null
      ok "MariaDB installed"
    fi
    DB_NAME="$(env_get DBMS_DB_NAME)"; DB_NAME="${DB_NAME:-dbms}"; DB_USER="$(env_get DBMS_DB_USER)"; DB_USER="${DB_USER:-dbms}"
    DB_PASS="${PRE_DB_PASS:-$(ask_db_password)}"
    mysql -u root <<SQL || die "Could not create the database as the MariaDB root user (run: sudo mysql)."
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL
    env_set DBMS_DB_ENGINE mysql; env_set DBMS_DB_NAME "$DB_NAME"; env_set DBMS_DB_USER "$DB_USER"
    env_set DBMS_DB_PASSWORD "$DB_PASS"; env_set DBMS_DB_HOST 127.0.0.1
    ok "database '$DB_NAME' ready (password stored in .env)"
  fi
chown "$SVC_USER:$SVC_USER" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"

# ---- 4. Python environment ------------------------------------------------------------------------
step "Python environment"
[ -x "$APP_DIR/.venv/bin/python" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip >/dev/null
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" || { rollback; die "Installing the Python packages failed."; }
ok "packages installed"
chown -R "$SVC_USER:$SVC_USER" "$APP_DIR"
# program files unpacked from a zip made on Windows can arrive writable by every account: take that away
chmod -R go-w "$APP_DIR"
chmod 700 "$APP_DIR/data"

# ---- 5. database tables ---------------------------------------------------------------------------
step "Database"
# leftovers of other builds are reported, never deleted silently (rsync above already removed them from the code)
if ! py migrate --noinput; then
  rollback; die "The database update failed, so the previous version was restored. Send the log above to support."
fi
ok "database is up to date"
if [ "$(py shell -c 'from apps.accounts.models import User; print(User.objects.exists())' 2>/dev/null | tail -n1)" != "True" ]; then
  if [ "$ASSUME_YES" = 1 ] || [ ! -t 0 ]; then
    warn "no administrator yet: open http://127.0.0.1/setup on the server, or run this script again without --yes"
  else
    admin="${PRE_ADMIN_USER:-$(ask "Administrator username" "admin")}"; pass="${PRE_ADMIN_PASS:-$(ask_secret "Administrator password (12+ characters)")}"
    DJANGO_SUPERUSER_USERNAME="$admin" DJANGO_SUPERUSER_PASSWORD="$pass" DJANGO_SUPERUSER_EMAIL="$admin@localhost" \
      as_app --preserve-env=DJANGO_SUPERUSER_USERNAME,DJANGO_SUPERUSER_PASSWORD,DJANGO_SUPERUSER_EMAIL \
      "$APP_DIR/.venv/bin/python" "$APP_DIR/manage.py" createsuperuser --noinput >/dev/null
    ok "administrator '$admin' created"
  fi
fi

# ---- 5b. FreeRADIUS: install and connect it to its MySQL database (fresh servers) ----------------------
RAD_DIR=/etc/freeradius/3.0
WANT_RADIUS=0
if command -v freeradius >/dev/null 2>&1; then WANT_RADIUS=1
elif [ "$MODE" = install ]; then
  if [ -n "$PRE_WANT_RADIUS" ]; then [ "$PRE_WANT_RADIUS" = y ] && WANT_RADIUS=1
  elif [ "$(ask "Install FreeRADIUS (RADIUS / AAA logins for your network devices) too? (y/n)" "y")" = y ]; then WANT_RADIUS=1; fi
fi
if [ "$WANT_RADIUS" = 1 ]; then
  step "FreeRADIUS"
  need=(); for p in freeradius freeradius-mysql freeradius-utils; do dpkg -s "$p" >/dev/null 2>&1 || need+=("$p"); done
  command -v mysql >/dev/null 2>&1 || need+=(mariadb-server)
  if [ ${#need[@]} -gt 0 ]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need[@]}" >/dev/null || die "Could not install ${need[*]}"
    systemctl enable --now mariadb >/dev/null 2>&1 || true
    ok "installed: ${need[*]}"
  fi
  [ -d "$RAD_DIR" ] || die "FreeRADIUS configuration folder $RAD_DIR not found"
  RAD_BACKUP="$BACKUP_ROOT/freeradius-config-$STAMP.tar.gz"
  tar -czf "$RAD_BACKUP" -C /etc freeradius && ok "FreeRADIUS configuration saved: $RAD_BACKUP"
  rad_restore() { rm -rf /etc/freeradius && tar -xzf "$RAD_BACKUP" -C /etc; warn "FreeRADIUS configuration restored"; }

  RPASS="$(env_get RADIUS_DB_PASSWORD)"
  if [ -z "$RPASS" ] || [ "$RPASS" = "change-me" ]; then
    # new RADIUS database + user, the FreeRADIUS tables, and the sql module pointing at it
    RDB="$(env_get RADIUS_DB_NAME)"; RDB="${RDB:-radius}"; RUSER="$(env_get RADIUS_DB_USER)"; RUSER="${RUSER:-radius}"
    RPASS="$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
    mysql -u root <<SQL || die "Could not create the RADIUS database as the MariaDB root user (run: sudo mysql)."
CREATE DATABASE IF NOT EXISTS \`$RDB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$RUSER'@'localhost' IDENTIFIED BY '$RPASS';
ALTER USER '$RUSER'@'localhost' IDENTIFIED BY '$RPASS';
GRANT ALL PRIVILEGES ON \`$RDB\`.* TO '$RUSER'@'localhost';
FLUSH PRIVILEGES;
SQL
    if [ "$(mysql -u root -N -B -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$RDB' AND table_name='radcheck'")" = 0 ]; then
      mysql -u root "$RDB" < "$RAD_DIR/mods-config/sql/main/mysql/schema.sql" || die "Could not load the FreeRADIUS tables"
      ok "FreeRADIUS tables created in database '$RDB'"
    fi
    env_set RADIUS_DB_NAME "$RDB"; env_set RADIUS_DB_USER "$RUSER"; env_set RADIUS_DB_PASSWORD "$RPASS"
    env_set RADIUS_DB_HOST 127.0.0.1; env_set RADIUS_DB_PORT 3306
    ok "RADIUS database ready (password generated and stored in .env)"
    # sql module: our own complete file (the packaged one has a mysql TLS block that blocks local connections)
    [ -f "$RAD_DIR/mods-available/sql" ] && cp -p "$RAD_DIR/mods-available/sql" "$RAD_DIR/mods-available/sql.dist-$STAMP"
    cat > "$RAD_DIR/mods-available/sql" <<CONF
# Written by VAULT deploy/install.sh ($STAMP); the original is sql.dist-$STAMP
sql {
	dialect = "mysql"
	driver = "rlm_sql_mysql"
	mysql {
		warnings = auto
	}
	server = "localhost"
	port = 3306
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
	# NAS clients come from the "nas" table, managed on the RADIUS / AAA -> NAS Clients page
	read_clients = yes
	client_table = "nas"
	group_attribute = "sql-SQL-Group"
	\$INCLUDE \${modconfdir}/\${.:name}/main/\${dialect}/queries.conf
}
CONF
    chown root:freerad "$RAD_DIR/mods-available/sql"; chmod 640 "$RAD_DIR/mods-available/sql"
    ln -sf ../mods-available/sql "$RAD_DIR/mods-enabled/sql"
    ok "FreeRADIUS connected to its database"
  else ok "existing RADIUS database settings kept"; fi

  # Always point FreeRADIUS at its database, even when the password already existed (writes the sql
  # module from .env and enables it, fixing the packaged TLS block). install.sh restarts FreeRADIUS
  # below, so skip the restart inside the helper.
  SETUP_SQL_NO_RESTART=1 APP_DIR="$APP_DIR" ENV_FILE="$APP_DIR/.env" RAD_DIR="$RAD_DIR" \
    bash "$APP_DIR/deploy/radius/setup_sql.sh" \
    && ok "FreeRADIUS sql module configured from .env" \
    || warn "could not configure the FreeRADIUS sql module; run: sudo bash $APP_DIR/deploy/radius/setup_sql.sh"

  # "where this user may log in" policy (RADIUS / AAA -> AAA Users)
  if [ ! -f "$RAD_DIR/policy.d/dbms_device_limit" ]; then
    install -m 640 -o root -g freerad "$APP_DIR/deploy/radius/dbms_device_limit" "$RAD_DIR/policy.d/dbms_device_limit"
  fi
  SITE_DEF="$RAD_DIR/sites-enabled/default"
  if [ -f "$SITE_DEF" ] && ! grep -q "dbms_device_limit" "$SITE_DEF"; then
    awk 'BEGIN{inauth=0;done=0}
         /^authorize[ \t]*\{/{inauth=1}
         {print}
         inauth && !done && /^[ \t]*-?sql[ \t]*$/ {print "\tdbms_device_limit"; done=1}
         inauth && /^\}/{inauth=0}' "$(readlink -f "$SITE_DEF")" > "/tmp/dbms-default.$$"
    if grep -q "dbms_device_limit" "/tmp/dbms-default.$$"; then
      cp "/tmp/dbms-default.$$" "$(readlink -f "$SITE_DEF")"; ok "per-device login limits enabled"
    else warn "no 'sql' line in authorize { } of $SITE_DEF: per-device login limits not enabled"; fi
    rm -f "/tmp/dbms-default.$$"
  fi
  # Huawei switches limited to privilege 0-3 (NAS Clients type "Huawei (levels 0-3 only)")
  install -m 640 -o root -g freerad "$APP_DIR/deploy/radius/dbms_huawei_levels" "$RAD_DIR/policy.d/dbms_huawei_levels"
  if [ -f "$SITE_DEF" ] && ! grep -q "dbms_huawei_levels" "$SITE_DEF"; then
    awk 'BEGIN{done=0} {print} !done && /^post-auth[ \t]*\{/ {print "\tdbms_huawei_levels"; done=1}' "$(readlink -f "$SITE_DEF")" > "/tmp/dbms-default.$$"
    if grep -q "dbms_huawei_levels" "/tmp/dbms-default.$$"; then cp "/tmp/dbms-default.$$" "$(readlink -f "$SITE_DEF")"; ok "Huawei 0-3 level switches supported"; fi
    rm -f "/tmp/dbms-default.$$"
  fi
  if freeradius -C >/dev/null 2>&1; then
    systemctl enable freeradius >/dev/null 2>&1; systemctl restart freeradius && ok "FreeRADIUS is running"
  else
    rad_restore; systemctl restart freeradius 2>/dev/null || true
    warn "FreeRADIUS rejected the new configuration (check: sudo freeradius -XC); the previous one was restored"
  fi
  # RADIUS ports 1812-1813/udp: opened per NAS Clients device in section 6 (enable_firewall_sync.sh),
  # not for the whole internet
fi

chown "$SVC_USER:$SVC_USER" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"

# ---- 6. RADIUS (only when it is configured) ------------------------------------------------------------
if [ -n "$(env_get RADIUS_DB_PASSWORD)" ] && [ "$(env_get RADIUS_DB_PASSWORD)" != "change-me" ]; then
  step "RADIUS / AAA"
  if py radius_init >/dev/null 2>&1; then ok "RADIUS tables ready"; else warn "RADIUS database not reachable: check RADIUS_DB_* in .env (the rest works)"; fi
  if command -v freeradius >/dev/null 2>&1 || command -v radiusd >/dev/null 2>&1; then
    if ENV_FILE="$APP_DIR/.env" bash "$APP_DIR/deploy/radius/enable_login_log.sh" >/dev/null 2>&1; then ok "logins are recorded with their device"
    else warn "device logging for logins could not be enabled; run: sudo bash $APP_DIR/deploy/radius/enable_login_log.sh"; fi
    if [ "$(env_get RADIUS_DYNAMIC_CLIENTS)" = 1 ] && grep -qs "dbms_dynamic_clients" /etc/freeradius/3.0/clients.conf; then ok "new switches work at once (no FreeRADIUS restart)"
    elif ENV_FILE="$APP_DIR/.env" bash "$APP_DIR/deploy/radius/enable_dynamic_clients.sh" >/dev/null 2>&1; then ok "new switches work at once (no FreeRADIUS restart)"
    else warn "could not enable instant switch adding; run: sudo bash $APP_DIR/deploy/radius/enable_dynamic_clients.sh"; fi
    if [ ! -f /etc/sudoers.d/dbms-radius ]; then
      sed "s/^dbms /$SVC_USER /" "$APP_DIR/deploy/radius/sudoers-dbms.example" > /tmp/dbms-radius.$$
      if visudo -cf /tmp/dbms-radius.$$ >/dev/null; then install -m 440 /tmp/dbms-radius.$$ /etc/sudoers.d/dbms-radius; ok "the app may restart FreeRADIUS after NAS changes"; fi
      rm -f /tmp/dbms-radius.$$
    fi
    if APP_DIR="$APP_DIR" ENV_FILE="$APP_DIR/.env" SVC_USER="$SVC_USER" bash "$APP_DIR/deploy/radius/enable_firewall_sync.sh" >/dev/null 2>&1; then
      ok "firewall: RADIUS 1812-1813/udp open only for NAS Clients devices"
    else warn "RADIUS firewall sync not enabled; run: sudo bash $APP_DIR/deploy/radius/enable_firewall_sync.sh"; fi
  fi
fi

# ---- 7. service ------------------------------------------------------------------------------------
step "Service"
PORT=8495
if [ -f /etc/systemd/system/dbms.service ]; then
  p="$(grep -oE -- '--port[ =]+[0-9]+' /etc/systemd/system/dbms.service | grep -oE '[0-9]+' | head -n1 || true)"; PORT="${p:-$PORT}"
fi
sed -e "s|^User=.*|User=$SVC_USER|" -e "s|^Group=.*|Group=$SVC_USER|" -e "s|^WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" \
    -e "s|^ExecStart=.*|ExecStart=$APP_DIR/.venv/bin/python manage.py serve --host 127.0.0.1 --port $PORT|" \
    "$APP_DIR/deploy/dbms.service" > /etc/systemd/system/dbms.service
systemctl daemon-reload; systemctl enable dbms >/dev/null 2>&1
ok "service uses port $PORT"

# ---- 8a. fresh server: HTTPS website with nginx and a self-signed certificate ---------------------------
proxied_site() { grep -rlE "proxy_pass[[:space:]]+https?://(127\.0\.0\.1|localhost):$PORT" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -n1 || true; }
WANT_HTTPS=0
if [ -z "$(proxied_site)" ] && [ "$MODE" = install ]; then
  if [ -n "$PRE_WANT_HTTPS" ]; then [ "$PRE_WANT_HTTPS" = y ] && WANT_HTTPS=1
  elif [ "$(ask "Publish the website on HTTPS with nginx (self-signed certificate)? (y/n)" "y")" = y ]; then WANT_HTTPS=1; fi
fi
if [ "$WANT_HTTPS" = 1 ]; then
  step "HTTPS website"
  need=(); for p in nginx openssl; do dpkg -s "$p" >/dev/null 2>&1 || need+=("$p"); done
  [ ${#need[@]} -eq 0 ] || { DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need[@]}" >/dev/null; ok "installed: ${need[*]}"; }
  ADDR="$(env_get DJANGO_ALLOWED_HOSTS | tr ',' '\n' | grep -vE '^(localhost|127\.0\.0\.1|::1)?$' | tail -n1 || true)"
  ADDR="${ADDR:-$(hostname -I | awk '{print $1}')}"
  mkdir -p /etc/ssl/dbms; chmod 700 /etc/ssl/dbms
  if [ ! -f /etc/ssl/dbms/dbms.crt ]; then
    if [[ "$ADDR" =~ ^[0-9.]+$ ]]; then SAN="IP:$ADDR"; else SAN="DNS:$ADDR"; fi
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$ADDR" -addext "subjectAltName=$SAN" \
      -keyout /etc/ssl/dbms/dbms.key -out /etc/ssl/dbms/dbms.crt >/dev/null 2>&1 || die "Could not create the certificate"
    chmod 600 /etc/ssl/dbms/dbms.key; ok "certificate created for $ADDR (valid 10 years; replace it with a real one any time)"
  fi
  sed -e "s|backup.example.com|$ADDR|g" -e "s|/etc/ssl/certs/dbms.crt|/etc/ssl/dbms/dbms.crt|" \
      -e "s|/etc/ssl/private/dbms.key|/etc/ssl/dbms/dbms.key|" -e "s|127.0.0.1:8495|127.0.0.1:$PORT|" \
      "$APP_DIR/deploy/nginx-dbms.conf" > /etc/nginx/sites-available/dbms
  ln -sf /etc/nginx/sites-available/dbms /etc/nginx/sites-enabled/dbms
  rm -f /etc/nginx/sites-enabled/default
  if [ -n "$PRE_WANT_HTTPS" ]; then
    DOMAIN_REQ="$PRE_DOMAIN"; DOMAIN_EMAIL="$PRE_DOMAIN_EMAIL"
  else
    DOMAIN_REQ="$(ask "Domain name for the website, e.g. backup.example.com (press Enter to use the IP only)" "")"
    [ -n "$DOMAIN_REQ" ] && DOMAIN_EMAIL="$(ask "Email for certificate expiry notices (Enter = none)" "")"
  fi
  if nginx -t >/dev/null 2>&1; then systemctl enable nginx >/dev/null 2>&1; systemctl reload nginx 2>/dev/null || systemctl restart nginx; ok "website published on https://$ADDR"
  else rm -f /etc/nginx/sites-enabled/dbms; warn "nginx rejected the site; check /etc/nginx/sites-available/dbms"; fi
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ok "firewall: 80/tcp and 443/tcp open"
  fi
fi

# ---- 8. nginx in front: pass the real visitor IP, hide the version ------------------------------------
if command -v nginx >/dev/null 2>&1; then
  step "nginx"
  SITE="$(grep -rlE "proxy_pass[[:space:]]+https?://(127\.0\.0\.1|localhost):$PORT" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -n1 || true)"
  if [ -n "$SITE" ]; then
    SITE="$(readlink -f "$SITE")"
    if ! grep -q "X-Forwarded-For" "$SITE" || ! grep -q "X-Forwarded-Proto" "$SITE" || ! grep -q "X-Forwarded-Host" "$SITE" || ! grep -q "server_tokens off" "$SITE"; then
      cp -p "$SITE" "$BACKUP_ROOT/nginx-$(basename "$SITE")-$STAMP"
      # add each header ONLY if that exact header is missing: a header sent twice ("https, https")
      # is rejected by the app with "Header X-Forwarded-Proto malformed"
      for hv in "X-Forwarded-Host \$host" "X-Forwarded-Proto \$scheme" "X-Forwarded-For \$remote_addr"; do
        grep -q "proxy_set_header[[:space:]]\+${hv%% *}[[:space:]]" "$SITE" || \
          sed -i -E "/proxy_pass[[:space:]]+https?:\/\/(127\.0\.0\.1|localhost):$PORT/a\\        proxy_set_header $hv;" "$SITE"
      done
      grep -q "server_tokens off" "$SITE" || sed -i -E "/proxy_pass[[:space:]]+https?:\/\/(127\.0\.0\.1|localhost):$PORT/a\\        server_tokens off;" "$SITE"
      if nginx -t >/dev/null 2>&1; then systemctl reload nginx; ok "nginx now passes the real visitor IP ($SITE)"
      else cp -p "$BACKUP_ROOT/nginx-$(basename "$SITE")-$STAMP" "$SITE"; warn "nginx rejected the change; original restored ($SITE)"; fi
    else ok "nginx already passes the real visitor IP"; fi
    [ "$(env_get DBMS_BEHIND_PROXY)" = 1 ] || { env_set DBMS_BEHIND_PROXY 1; ok "app trusts nginx for the visitor IP"; }
    if grep -qE "listen[[:space:]]+[^;]*443" "$SITE"; then
      for k in DBMS_SECURE_COOKIES DBMS_FORCE_HTTPS; do [ "$(env_get $k)" = 1 ] || { env_set $k 1; ok "$k=1 (site uses HTTPS)"; }; done
    fi
  else warn "no nginx site proxies to port $PORT yet: see deploy/nginx-dbms.conf"; fi
fi

# ---- 8b. optional: turn on the ufw firewall (SSH, web and RADIUS stay open) ---------------------------
if command -v ufw >/dev/null 2>&1 && ! ufw status 2>/dev/null | grep -q "Status: active"; then
  DO_UFW=0
  if [ -n "$PRE_WANT_UFW" ]; then [ "$PRE_WANT_UFW" = y ] && DO_UFW=1
  elif [ "$MODE" = install ] && [ "$(ask "Turn on the ufw firewall now (SSH, web and RADIUS stay open, the rest is blocked)? (y/n)" "y")" = y ]; then DO_UFW=1; fi
  if [ "$DO_UFW" = 1 ]; then
    step "Firewall (ufw)"
    # allow SSH FIRST so enabling the firewall never locks the admin out
    ufw allow OpenSSH >/dev/null 2>&1 || true
    ufw allow 22/tcp  >/dev/null 2>&1 || true
    if command -v nginx >/dev/null 2>&1; then ufw allow 80/tcp >/dev/null 2>&1 || true; ufw allow 443/tcp >/dev/null 2>&1 || true; fi
    if ufw --force enable >/dev/null 2>&1; then
      ok "firewall on (SSH and web stay open)"
      # open RADIUS 1812/1813 only for the devices on NAS Clients (none yet = closed until you add them)
      [ -x /usr/local/sbin/dbms-radius-firewall ] && { /usr/local/sbin/dbms-radius-firewall >/dev/null 2>&1 || true; ok "RADIUS 1812-1813/udp opened for NAS Clients devices only"; }
    else warn "could not turn on ufw; later run:  sudo ufw allow OpenSSH && sudo ufw enable"; fi
  fi
fi

# ---- 9. start and check ------------------------------------------------------------------------------
step "Start"
systemctl restart dbms
for _ in $(seq 1 20); do curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done
if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then ok "the website is answering"
else rollback; die "The new version did not start (see: journalctl -u dbms -n 50). The previous version was restored."; fi

if [ -n "${DOMAIN_REQ:-}" ]; then
  step "Domain $DOMAIN_REQ"
  bash "$APP_DIR/deploy/set-domain.sh" "$DOMAIN_REQ" ${DOMAIN_EMAIL:+"$DOMAIN_EMAIL"} \
    || warn "the domain could not be set up now; later run: sudo bash $APP_DIR/deploy/set-domain.sh $DOMAIN_REQ"
fi

printf "\n${c_g}Done.${c_0} %s finished. Open the website and press Ctrl+F5.\n" "$([ $MODE = install ] && echo Installation || echo Update)"
[ -n "$CODE_BACKUP" ] && echo "Previous version kept in: $CODE_BACKUP"
echo "Log of this run: $LOG"
