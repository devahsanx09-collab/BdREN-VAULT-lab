#!/usr/bin/env bash
# Check that every RADIUS user gets the access level the panel says, on every vendor.
#
# READ-ONLY: this script changes nothing. It checks
#   1. FreeRADIUS is running, listening on UDP 1812 and its configuration is valid
#   2. the DBMS policies are installed (device limits, Huawei 0-3 levels, dynamic clients)
#   3. nothing outside the panel forces a level (e.g. a DEFAULT entry giving Huawei-Exec-Privilege = 15)
#   4. the three access levels send the right value to Cisco, Huawei, Juniper, MikroTik and Fortinet,
#      with ":=" so the panel always wins
#   5. every user: exactly one level, no per-user overrides, where the user may log in
#   6. the NAS clients and their types
#   7. the latest logins with the level each user should have received
# and ends with "ALL CHECKS PASSED" or the list of problems and how to fix them.
#
# Usage:   sudo bash /opt/dbms/deploy/radius/check_levels.sh
#          (reads RADIUS_DB_* from /opt/dbms/.env; set ENV_FILE=/path/.env to use another file)
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
sql "SELECT 1" >/dev/null 2>&1 || die "Cannot connect to database '$DB_NAME' as '$DB_USER' (check RADIUS_DB_* in $ENV_FILE)"

RADDB=""
for d in /etc/freeradius/3.0 /etc/freeradius /etc/raddb; do [ -d "$d" ] && { RADDB="$d"; break; }; done
RADIUSD="$(command -v freeradius || command -v radiusd || true)"

# ---- 1. service ----------------------------------------------------------------------------------
say "1. FreeRADIUS service"
if systemctl is-active --quiet freeradius 2>/dev/null || systemctl is-active --quiet radiusd 2>/dev/null; then
  ok "FreeRADIUS is running"
else
  bad "FreeRADIUS is NOT running: no RADIUS user can log in on any switch" \
      "sudo pkill -f 'freeradius -X'; sudo systemctl start freeradius   (if it still fails: sudo freeradius -XC | tail -15)"
fi
if command -v ss >/dev/null && ss -lun 2>/dev/null | grep -q ':1812\b'; then
  ok "listening on UDP 1812"
else
  warn "nothing is listening on UDP 1812" "start FreeRADIUS (see above)"
fi
if [ -n "$RADIUSD" ]; then
  if "$RADIUSD" -C >/tmp/dbms-radius-check.log 2>&1; then ok "configuration is valid"
  else bad "FreeRADIUS configuration check failed (details: /tmp/dbms-radius-check.log)" "sudo freeradius -XC | tail -15"; fi
fi

# ---- 2. DBMS policies ----------------------------------------------------------------------------
say "2. DBMS policies in FreeRADIUS"
SITE="$RADDB/sites-enabled/default"
active() { grep -Ev '^[[:space:]]*#' "$1" 2>/dev/null; }
if [ -z "$RADDB" ] || [ ! -f "$SITE" ]; then
  bad "FreeRADIUS site file not found ($SITE)" "re-run: sudo bash /opt/dbms/deploy/install.sh"
else
  block() { active "$SITE" | awk -v s="$1" '$0 ~ "^[[:space:]]*"s"[[:space:]]*\\{" {f=1} f {print} f && /^}/ {exit}'; }
  if block authorize | grep -qw dbms_device_limit; then ok "per-device limits (dbms_device_limit) are enforced"
  else bad "dbms_device_limit is not in 'authorize': users can log in on switches outside their list" "re-run: sudo bash /opt/dbms/deploy/install.sh"; fi
  if block post-auth | grep -qw dbms_huawei_levels; then ok "Huawei 0-3 level cap (dbms_huawei_levels) is installed"
  else warn "dbms_huawei_levels is not in 'post-auth': super-admin is not capped to 3 on 'Huawei (levels 0-3 only)' switches" "re-run: sudo bash /opt/dbms/deploy/install.sh"; fi
fi
if active "$RADDB/clients.conf" | grep -q dbms_dynamic_clients; then ok "new switches work without restart (dynamic clients)"
else warn "dynamic clients are not enabled: a new switch needs a FreeRADIUS restart" "sudo bash /opt/dbms/deploy/radius/enable_dynamic_clients.sh"; fi

# ---- 3. levels forced outside the panel ---------------------------------------------------------
say "3. Level attributes set outside the panel"
LEVEL_RE='Huawei-Exec-Privilege|priv-lvl|Mikrotik-Group|Juniper-Local-User-Name|Fortinet-Group-Name|Administrative-User|NAS-Prompt-User'
FOUND=0
while IFS= read -r f; do
  case "$f" in
    */dbms_*) continue ;;
    # The files module reads only these names; backups next to them (authorize.dbms-backup-...) are inert.
    "$RADDB/mods-config/files/"*)
      case "${f##*/}" in authorize|accounting|pre-proxy) ;; *) continue ;; esac ;;
  esac
  while IFS= read -r line; do
    FOUND=1
    bad "$f: $line" "remove or comment out (#) that line, then: sudo freeradius -C && sudo systemctl restart freeradius"
  done < <(grep -nE "$LEVEL_RE" "$f" 2>/dev/null | grep -Ev '^[0-9]+:[[:space:]]*#')
done < <(find -L "$RADDB/mods-config/files" "$RADDB/sites-enabled" "$RADDB/policy.d" "$RADDB/users" -maxdepth 1 -type f 2>/dev/null)
[ "$FOUND" = 0 ] && ok "no file forces a level; the panel decides"
AUTHZ="$RADDB/mods-config/files/authorize"
if [ -f "$AUTHZ" ]; then
  # Entries start in column 0 ("name  Check-Item ..." or "DEFAULT ..."); reply lines are indented.
  # FreeRADIUS ships a few DEFAULT entries (PPP / SLIP dial-up) that set no level: only named users matter here.
  ENTRIES="$(grep -Ev '^[[:space:]]*(#|$)' "$AUTHZ" | grep -E '^[^[:space:]]' | awk '$1 != "DEFAULT" {print $1}' | sort | uniq -c | awk '{printf "%s%s", (NR>1?", ":""), ($1>1? $2" x"$1 : $2)}')"
  if [ -n "$ENTRIES" ]; then
    warn "users defined in $AUTHZ (checked BEFORE the panel's users): $ENTRIES" \
         "such a user can log in with that file's password even after being deleted in the panel; remove the entries you do not need"
  else
    ok "no users defined outside the panel (FreeRADIUS's own DEFAULT entries are fine)"
  fi
fi

# ---- 4. group attributes -------------------------------------------------------------------------
say "4. What each access level sends to the devices"
EXPECTED="super-admin|Cisco-AVPair|+=|shell:priv-lvl=15
super-admin|Huawei-Exec-Privilege|:=|15
super-admin|Mikrotik-Group|:=|full
super-admin|Juniper-Local-User-Name|:=|super-user
super-admin|Fortinet-Group-Name|:=|super_admin
read-write|Cisco-AVPair|+=|shell:priv-lvl=7
read-write|Huawei-Exec-Privilege|:=|2
read-write|Mikrotik-Group|:=|write
read-write|Juniper-Local-User-Name|:=|operator
read-write|Fortinet-Group-Name|:=|rw_admin
read-only|Cisco-AVPair|+=|shell:priv-lvl=1
read-only|Huawei-Exec-Privilege|:=|1
read-only|Mikrotik-Group|:=|read
read-only|Juniper-Local-User-Name|:=|read-only
read-only|Fortinet-Group-Name|:=|ro_admin"
ACTUAL="$(sql "SELECT groupname, attribute, op, value FROM radgroupreply" | tr '\t' '|')"
GROUP_OK=1
WEAK_OPS=()
while IFS='|' read -r g a o v; do
  row="$(printf '%s\n' "$ACTUAL" | awk -F'|' -v g="$g" -v a="$a" '$1==g && $2==a' | head -n1)"
  if [ -z "$row" ]; then
    GROUP_OK=0; bad "$g: $a is missing (should be $o $v)" "sudo -u dbms /opt/dbms/.venv/bin/python /opt/dbms/manage.py seed_groups   (or re-run install.sh)"
  else
    IFS='|' read -r _ _ ro rv <<<"$row"
    if [ "$rv" != "$v" ]; then
      GROUP_OK=0; bad "$g: $a = $rv (should be $v)" "sudo -u dbms /opt/dbms/.venv/bin/python /opt/dbms/manage.py seed_groups   (or re-run install.sh)"
    elif [ "$ro" != "$o" ]; then
      GROUP_OK=0; WEAK_OPS+=("$g $a")
    fi
  fi
done <<<"$EXPECTED"
if [ "${#WEAK_OPS[@]}" -gt 0 ]; then
  bad "${#WEAK_OPS[@]} level attribute(s) use '=' instead of ':=', so a level set anywhere else wins over the panel (${WEAK_OPS[0]}, ...)" \
      "sudo mysql $DB_NAME -e \"UPDATE radgroupreply SET op=':=' WHERE op='=' AND groupname IN ('super-admin','read-write','read-only');\""
fi
[ "$GROUP_OK" = 1 ] && ok "super-admin, read-write and read-only send the right level to every vendor"
printf '\n  %-12s %-18s %-24s %-12s %-12s %s\n' "LEVEL" "CISCO" "HUAWEI" "JUNIPER" "MIKROTIK" "FORTINET"
for g in super-admin read-write read-only; do
  val() { printf '%s\n' "$ACTUAL" | awk -F'|' -v g="$g" -v a="$1" '$1==g && $2==a {print $4; exit}'; }
  printf '  %-12s %-18s %-24s %-12s %-12s %s\n' "$g" "$(val Cisco-AVPair | sed 's/shell://')" "$(val Huawei-Exec-Privilege)" \
         "$(val Juniper-Local-User-Name)" "$(val Mikrotik-Group)" "$(val Fortinet-Group-Name)"
done

# ---- 5. users ------------------------------------------------------------------------------------
say "5. Users"
HAS_LIMITS=0
[ "$(sql "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='dbms_user_nas'")" = "1" ] && HAS_LIMITS=1
USERS="$(sql "SELECT DISTINCT username FROM radcheck WHERE attribute IN ('Cleartext-Password','SSHA2-256-Password') ORDER BY username")"
if [ -z "$USERS" ]; then
  warn "there are no RADIUS users yet" ""
else
  printf '  %-18s %-13s %s\n' "USER" "LEVEL" "CAN LOG IN ON"
  while IFS= read -r u; do
    [ -n "$u" ] || continue
    ue="${u//\'/\'\'}"
    groups="$(sql "SELECT groupname FROM radusergroup WHERE username='$ue' ORDER BY priority" | paste -sd, -)"
    where="all devices"
    if [ "$HAS_LIMITS" = 1 ]; then
      lim="$(sql "SELECT COALESCE(n.shortname, l.nasname) FROM dbms_user_nas l LEFT JOIN nas n ON n.nasname = l.nasname WHERE l.username='$ue' ORDER BY 1" | paste -sd, -)"
      [ -n "$lim" ] && where="$lim"
    fi
    printf '  %-18s %-13s %s\n' "$u" "${groups:--}" "$where"
    case "$groups" in
      "")  bad "user '$u' has no access level: FreeRADIUS sends no level (device default applies)" "open the user in the panel and save a level" ;;
      *,*) bad "user '$u' has more than one level ($groups)" "open the user in the panel and save one level" ;;
      super-admin|read-write|read-only) ;;
      *)   bad "user '$u' has an unknown level '$groups'" "open the user in the panel and save a level" ;;
    esac
    over="$(sql "SELECT CONCAT(attribute,' ',op,' ',value) FROM radreply WHERE username='$ue'" | paste -sd';' -)"
    [ -n "$over" ] && bad "user '$u' has personal reply attributes that can override the level: $over" \
      "sudo mysql $DB_NAME -e \"DELETE FROM radreply WHERE username='$ue';\""
  done <<<"$USERS"
fi

# ---- 6. NAS clients ------------------------------------------------------------------------------
say "6. NAS clients (switches allowed to ask this server)"
NAS="$(sql "SELECT nasname, shortname, type FROM nas ORDER BY shortname")"
if [ -z "$NAS" ]; then
  warn "no NAS clients: no switch can use RADIUS yet" "RADIUS / AAA -> NAS Clients -> Add"
else
  printf '  %-18s %-28s %s\n' "IP" "NAME" "TYPE"
  while IFS=$'\t' read -r ip name type; do
    printf '  %-18s %-28s %s\n' "$ip" "$name" "$type"
  done <<<"$NAS"
  echo "  (Huawei switches that only know levels 0-3 should be type 'huawei-3'; super-admin then gets 3.)"
fi

# ---- 7. latest logins ----------------------------------------------------------------------------
say "7. Latest logins"
DEV="''"
[ "$(sql "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='radpostauth' AND column_name='nasipaddress'")" = "1" ] && DEV="p.nasipaddress"
LOGINS="$(sql "SELECT DATE_FORMAT(p.authdate,'%Y-%m-%d %H:%i'), p.username, p.reply, COALESCE(NULLIF(n.shortname,''), $DEV, ''), COALESCE(g.groupname,'-')
               FROM radpostauth p LEFT JOIN nas n ON n.nasname = $DEV LEFT JOIN radusergroup g ON g.username = p.username
               ORDER BY p.id DESC LIMIT 15" 2>/dev/null)"
if [ -z "$LOGINS" ]; then
  echo "  no logins recorded yet"
else
  printf '  %-17s %-16s %-14s %-26s %s\n' "TIME" "USER" "RESULT" "DEVICE" "LEVEL"
  while IFS=$'\t' read -r t u r d g; do
    printf '  %-17s %-16s %-14s %-26s %s\n' "$t" "$u" "$r" "${d:--}" "$g"
  done <<<"$LOGINS"
fi

# ---- summary -------------------------------------------------------------------------------------
say "Result"
if [ "${#PROBLEMS[@]}" -eq 0 ]; then
  printf '  \033[1;32mALL CHECKS PASSED\033[0m: every user gets exactly the level shown in the panel.\n'
else
  printf '  \033[1;31m%d problem(s) found. Fix them in this order:\033[0m\n' "${#PROBLEMS[@]}"
  i=1
  last=""
  for p in "${PROBLEMS[@]}"; do
    printf '  %d. %s\n' "$i" "${p%%|*}"
    fix="${p#*|}"
    if [ -n "$fix" ] && [ "$fix" != "$last" ]; then printf '     fix: %s\n' "$fix"; fi
    last="$fix"; i=$((i+1))
  done
  echo "  (a step without 'fix:' uses the same fix as the step above it)"
fi
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  printf '  \033[1;33m%d warning(s):\033[0m\n' "${#WARNINGS[@]}"
  for w in "${WARNINGS[@]}"; do
    printf '  - %s\n' "${w%%|*}"
    fix="${w#*|}"; [ -n "$fix" ] && printf '     fix: %s\n' "$fix"
  done
fi
cat <<'EOF'

  On the device, confirm with a test login:
    Huawei : display user-interface vty 0      -> ActualPrivi (read-only = 1)
    Cisco  : show privilege                    -> read-only = 1, super-admin = 15
    Juniper: show cli authorization            -> class of the template user
EOF
[ "${#PROBLEMS[@]}" -eq 0 ]
