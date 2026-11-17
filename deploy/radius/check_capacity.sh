#!/usr/bin/env bash
# Check FreeRADIUS's own capacity against how many logins may hit it at the same time.
#
# READ-ONLY: this script changes nothing. Background: every device backup is an SSH login, and most of
# these switches authenticate that login through THIS FreeRADIUS server. A big backup run starts several
# SSH logins within the same second (VAULT paces them, but still), so several switches ask FreeRADIUS for
# an Access-Request at once. If FreeRADIUS's own thread pool or its SQL connection pool is too small for
# that burst, a request queues up or times out - the switch then rejects the login with "AAA server busy"
# (VAULT retries it automatically a few minutes later, but it is better avoided). This script checks:
#   1. FreeRADIUS is running and its configuration is valid
#   2. the thread pool (how many requests FreeRADIUS can work on at once) against VAULT's own worker count
#   3. the SQL module's connection pool (how many of those threads can query the database at once)
#   4. the radius log for signs the pool was ever exhausted (queued / dropped requests)
# and ends with "ALL CHECKS PASSED" or what to raise and how.
#
# Usage:   sudo bash /opt/dbms/deploy/radius/check_capacity.sh
#          (reads RADIUS_DB_* and DBMS_DB_* from /opt/dbms/.env; set ENV_FILE=/path/.env to use another file)
set -uo pipefail

ENV_FILE="${ENV_FILE:-/opt/dbms/.env}"
PROBLEMS=()
WARNINGS=()
say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[1;32mOK\033[0m    %s\n' "$*"; }
bad()  { printf '  \033[1;31mFAIL\033[0m  %s\n' "$1"; PROBLEMS+=("$1|${2:-}"); }
warn() { printf '  \033[1;33mWARN\033[0m  %s\n' "$1"; WARNINGS+=("$1|${2:-}"); }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo:  sudo bash $0"
[ -r "$ENV_FILE" ] || die "Cannot read $ENV_FILE (set ENV_FILE=/path/to/.env)"
command -v mysql >/dev/null || die "The mysql client is not installed"

env_get() { grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+|[[:space:]]+$//g' -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }

RAD_DB_NAME="$(env_get RADIUS_DB_NAME)"; RAD_DB_NAME="${RAD_DB_NAME:-radius}"
RAD_DB_USER="$(env_get RADIUS_DB_USER)"; RAD_DB_USER="${RAD_DB_USER:-radius}"
RAD_DB_PASS="$(env_get RADIUS_DB_PASSWORD)"
RAD_DB_HOST="$(env_get RADIUS_DB_HOST)"; RAD_DB_HOST="${RAD_DB_HOST:-127.0.0.1}"
RAD_DB_PORT="$(env_get RADIUS_DB_PORT)"; RAD_DB_PORT="${RAD_DB_PORT:-3306}"

DBMS_DB_NAME="$(env_get DBMS_DB_NAME)"; DBMS_DB_NAME="${DBMS_DB_NAME:-dbms}"
DBMS_DB_USER="$(env_get DBMS_DB_USER)"; DBMS_DB_USER="${DBMS_DB_USER:-dbms}"
DBMS_DB_PASS="$(env_get DBMS_DB_PASSWORD)"
DBMS_DB_HOST="$(env_get DBMS_DB_HOST)"; DBMS_DB_HOST="${DBMS_DB_HOST:-127.0.0.1}"
DBMS_DB_PORT="$(env_get DBMS_DB_PORT)"; DBMS_DB_PORT="${DBMS_DB_PORT:-3306}"

MYCNF="$(mktemp)"; chmod 600 "$MYCNF"; trap 'rm -f "$MYCNF"' EXIT
rad_sql() { printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' "$RAD_DB_USER" "$RAD_DB_PASS" "$RAD_DB_HOST" "$RAD_DB_PORT" > "$MYCNF"
            mysql --defaults-extra-file="$MYCNF" -N -B "$RAD_DB_NAME" -e "$1" 2>/dev/null; }
dbms_sql() { printf '[client]\nuser=%s\npassword=%s\nhost=%s\nport=%s\n' "$DBMS_DB_USER" "$DBMS_DB_PASS" "$DBMS_DB_HOST" "$DBMS_DB_PORT" > "$MYCNF"
             mysql --defaults-extra-file="$MYCNF" -N -B "$DBMS_DB_NAME" -e "$1" 2>/dev/null; }

RADDB=""
for d in /etc/freeradius/3.0 /etc/freeradius /etc/raddb; do [ -d "$d" ] && { RADDB="$d"; break; }; done
[ -n "$RADDB" ] || die "Could not find the FreeRADIUS configuration directory"

# ---- 1. service ----------------------------------------------------------------------------------
say "1. FreeRADIUS service"
if systemctl is-active --quiet freeradius 2>/dev/null || systemctl is-active --quiet radiusd 2>/dev/null; then
  ok "FreeRADIUS is running"
else
  bad "FreeRADIUS is NOT running" "sudo systemctl start freeradius"
fi

# ---- 2. how many logins can happen at once (VAULT's side) ----------------------------------------
say "2. VAULT's side: how many devices it logs in to at the same time"
WORKERS="$(dbms_sql "SELECT value FROM scheduling_appsetting WHERE \`key\`='workers'" | tr -d '[:space:]')"
if [ -z "$WORKERS" ]; then
  WORKERS="$(env_get WORKERS)"; WORKERS="${WORKERS:-5}"
  echo "  Settings page value not set; using the .env / default of $WORKERS parallel SSH sessions."
else
  echo "  Settings page: $WORKERS parallel SSH sessions (System Settings -> Performance)."
fi
case "$WORKERS" in ''|*[!0-9]*) WORKERS=5 ;; esac
NAS_COUNT="$(rad_sql "SELECT COUNT(*) FROM nas")"
echo "  $NAS_COUNT NAS client(s) registered; a full backup run can knock on FreeRADIUS from up to $WORKERS of them within the same second or two."

# ---- 3. FreeRADIUS's own thread pool ---------------------------------------------------------------
say "3. FreeRADIUS thread pool (how many requests it works on at once)"
RADIUSD_CONF="$RADDB/radiusd.conf"
pool_value() { awk -v k="$1" '/^[[:space:]]*thread[[:space:]]+pool[[:space:]]*\{/{f=1} f && $0 ~ "^[[:space:]]*"k"[[:space:]]*=" {gsub(/[^0-9]/,"",$0); print; f2=1} f && /^[[:space:]]*\}/{if(f2)exit; f=0}' "$RADIUSD_CONF" | head -n1; }
if [ -f "$RADIUSD_CONF" ]; then
  MAX_SERVERS="$(pool_value max_servers)"
  START_SERVERS="$(pool_value start_servers)"
  if [ -z "$MAX_SERVERS" ]; then
    warn "could not read 'max_servers' from $RADIUSD_CONF (thread pool section may be commented out / default build)" ""
  else
    echo "  thread pool: start_servers=${START_SERVERS:-?}, max_servers=$MAX_SERVERS"
    NEED=$((WORKERS * 3))
    if [ "$MAX_SERVERS" -lt "$NEED" ]; then
      bad "thread pool max_servers ($MAX_SERVERS) is less than about 3x VAULT's worker count ($WORKERS, i.e. $NEED) - a big backup run can exhaust it" \
          "raise 'max_servers' to at least $NEED in $RADIUSD_CONF's 'thread pool { }' block, then: sudo freeradius -C && sudo systemctl restart freeradius"
    else
      ok "thread pool max_servers ($MAX_SERVERS) comfortably covers $WORKERS parallel SSH logins"
    fi
  fi
else
  warn "$RADIUSD_CONF not found" ""
fi

# ---- 4. the SQL module's own connection pool -----------------------------------------------------
say "4. SQL module connection pool (how many threads can query the database at once)"
SQLCONF=""
for f in "$RADDB/mods-enabled/sql" "$RADDB/mods-available/sql"; do [ -f "$f" ] && { SQLCONF="$f"; break; }; done
if [ -z "$SQLCONF" ]; then
  warn "could not find the sql module file (mods-enabled/sql)" ""
else
  # Prints the raw right-hand side of "key = value" inside the first 'pool { }' block, quotes stripped -
  # the default FreeRADIUS config writes max = ${thread[pool].max_servers} (a reference, not a number).
  sql_pool_value() { awk -v k="$1" '/^[[:space:]]*pool[[:space:]]*\{/{f=1} f && $0 ~ "^[[:space:]]*"k"[[:space:]]*=" {sub(/^[^=]*=[[:space:]]*/,""); gsub(/^"|"[[:space:]]*$/,""); print; f2=1} f && /^[[:space:]]*\}/{if(f2)exit; f=0}' "$SQLCONF" | head -n1; }
  SQL_MAX_RAW="$(sql_pool_value max)"
  SQL_START="$(sql_pool_value start)"
  if [ -z "$SQL_MAX_RAW" ]; then
    warn "could not read the SQL pool's 'max' from $SQLCONF" ""
  elif printf '%s' "$SQL_MAX_RAW" | grep -q '\${thread'; then
    echo "  SQL pool ($SQLCONF): start=${SQL_START:-?}, max=$SQL_MAX_RAW"
    ok "SQL pool max follows the thread pool automatically (no separate limit to worry about)"
  elif printf '%s' "$SQL_MAX_RAW" | grep -qE '^[0-9]+$'; then
    echo "  SQL pool ($SQLCONF): start=${SQL_START:-?}, max=$SQL_MAX_RAW"
    if [ -n "${MAX_SERVERS:-}" ] && [ "$SQL_MAX_RAW" -lt "$MAX_SERVERS" ]; then
      bad "SQL pool max ($SQL_MAX_RAW) is smaller than the thread pool max_servers ($MAX_SERVERS) - threads will queue for a database connection" \
          "raise 'max' in $SQLCONF's 'pool { }' block to at least $MAX_SERVERS, then: sudo freeradius -C && sudo systemctl restart freeradius"
    else
      ok "SQL pool max ($SQL_MAX_RAW) is not the bottleneck"
    fi
  else
    warn "SQL pool 'max' is set to '$SQL_MAX_RAW' in $SQLCONF (not a plain number) - could not compare it automatically" ""
  fi
fi

# ---- 5. signs the pool was ever exhausted ---------------------------------------------------------
say "5. Recent signs of exhaustion (last 7 days)"
HITS="$(journalctl -u freeradius --since '7 days ago' 2>/dev/null | grep -icE 'no connection available|too many open connections|queued? too long|unable to spawn')"
if [ "${HITS:-0}" -gt 0 ]; then
  bad "$HITS log line(s) in the last 7 days point to the thread/SQL pool running out" \
      "raise the pool sizes above, or check: sudo journalctl -u freeradius --since '7 days ago' | grep -iE 'no connection available|too many open connections|queued? too long|unable to spawn'"
else
  ok "no sign of pool exhaustion in the FreeRADIUS log"
fi

# ---- summary ----------------------------------------------------------------------------------------
say "Result"
if [ "${#PROBLEMS[@]}" -eq 0 ]; then
  printf '  \033[1;32mALL CHECKS PASSED\033[0m: FreeRADIUS has enough headroom for VAULT'\''s backup logins.\n'
else
  printf '  \033[1;31m%d problem(s) found. Fix them in this order:\033[0m\n' "${#PROBLEMS[@]}"
  i=1
  for p in "${PROBLEMS[@]}"; do
    printf '  %d. %s\n' "$i" "${p%%|*}"
    fix="${p#*|}"; [ -n "$fix" ] && printf '     fix: %s\n' "$fix"
    i=$((i+1))
  done
fi
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  printf '  \033[1;33m%d warning(s):\033[0m\n' "${#WARNINGS[@]}"
  for w in "${WARNINGS[@]}"; do
    printf '  - %s\n' "${w%%|*}"
    fix="${w#*|}"; [ -n "$fix" ] && printf '     fix: %s\n' "$fix"
  done
fi
[ "${#PROBLEMS[@]}" -eq 0 ]
