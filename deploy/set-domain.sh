#!/usr/bin/env bash
# =====================================================================================================
#  Put the website on a domain name, with a real HTTPS certificate when possible.
#
#     sudo bash /opt/vault/deploy/set-domain.sh backup.example.com you@example.com
#
#  Before you run it:
#    1. DNS: an "A" record  backup.example.com -> this server's public IP
#    2. Ports 80 and 443 of this server reachable from the internet (needed for Let's Encrypt)
#
#  What it does:
#    - adds the domain to the app's allowed names (.env: DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS)
#    - adds the domain to the nginx site that serves the app (the IP keeps working)
#    - gets a free Let's Encrypt certificate with certbot and renews it automatically
#      (the email is only used by Let's Encrypt for expiry warnings; running this accepts their terms:
#       https://letsencrypt.org/repository/). Add --self-signed to skip Let's Encrypt.
#    - if Let's Encrypt is not possible (DNS not ready, port 80 closed), a self-signed certificate for the
#      domain is used instead; run the script again later to get the real one
#    - checks nginx before reloading and puts the previous files back if anything fails
# =====================================================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/vault}"
DOMAIN="${1:-}"; EMAIL="${2:-}"; SELF_SIGNED=0
for a in "$@"; do [ "$a" = "--self-signed" ] && SELF_SIGNED=1; done
[ "$EMAIL" = "--self-signed" ] && EMAIL=""
STAMP="$(date +%Y%m%d-%H%M%S)"; BACKUP="/var/backups/vault/domain-$STAMP"

c_g='\033[1;32m'; c_y='\033[1;33m'; c_r='\033[1;31m'; c_b='\033[1;34m'; c_0='\033[0m'
step() { printf "\n${c_b}==> %s${c_0}\n" "$*"; }
ok()   { printf "${c_g}  ✓${c_0} %s\n" "$*"; }
warn() { printf "${c_y}  !${c_0} %s\n" "$*"; }
die()  { printf "\n${c_r}ERROR:${c_0} %s\n" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run it with sudo:  sudo bash $0 your.domain.com you@example.com"
[ -n "$DOMAIN" ] || die "Usage:  sudo bash $0 backup.example.com you@example.com   [--self-signed]"
DOMAIN="$(echo "$DOMAIN" | tr '[:upper:]' '[:lower:]')"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || die "'$DOMAIN' is not a valid domain name"
[ -f "$APP_DIR/.env" ] || die "$APP_DIR/.env not found: install the application first (deploy/install.sh)"
command -v nginx >/dev/null 2>&1 || die "nginx is not installed: run deploy/install.sh first"

env_get() { grep -E "^$1=" "$APP_DIR/.env" | tail -n1 | cut -d= -f2- | sed -E -e 's/[[:space:]]+#.*$//' -e 's/^[[:space:]]+|[[:space:]]+$//g' -e 's/^["'\'']//' -e 's/["'\'']$//' || true; }
env_set() { if grep -qE "^$1=" "$APP_DIR/.env"; then sed -i "s|^$1=.*|$1=$2|" "$APP_DIR/.env"; else printf '%s=%s\n' "$1" "$2" >> "$APP_DIR/.env"; fi; }
add_to_list() { # add_to_list KEY VALUE  (comma-separated list without duplicates)
  local cur; cur="$(env_get "$1")"
  if printf '%s' ",$cur," | grep -qF ",$2,"; then return 0; fi
  env_set "$1" "${cur:+$cur,}$2"; }

# ---- which nginx site serves the app ---------------------------------------------------------------
PORT="$(grep -oE -- '--port[ =]+[0-9]+' /etc/systemd/system/vault.service 2>/dev/null | grep -oE '[0-9]+' | head -n1 || true)"; PORT="${PORT:-8495}"
SITE="$(grep -rlE "proxy_pass[[:space:]]+https?://(127\.0\.0\.1|localhost):$PORT" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | head -n1 || true)"
[ -n "$SITE" ] || die "No nginx site forwards to the app on port $PORT. Run deploy/install.sh first."
SITE="$(readlink -f "$SITE")"
mkdir -p "$BACKUP"; chmod 700 "$BACKUP"
cp -p "$SITE" "$BACKUP/"; cp -p "$APP_DIR/.env" "$BACKUP/env"
restore() { cp -p "$BACKUP/$(basename "$SITE")" "$SITE"; cp -p "$BACKUP/env" "$APP_DIR/.env"; nginx -t >/dev/null 2>&1 && systemctl reload nginx; warn "previous settings restored"; }
ok "nginx site: $SITE (backup in $BACKUP)"

# ---- DNS check (warning only: the server may be behind NAT) ------------------------------------------
step "DNS"
RESOLVED="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
if [ -z "$RESOLVED" ]; then warn "$DOMAIN does not resolve yet. Create the DNS A record first (a real certificate needs it)."
else
  ok "$DOMAIN -> $RESOLVED"
  mine=0; for ip in $RESOLVED; do hostname -I | tr ' ' '\n' | grep -qx "$ip" && mine=1; done
  [ "$mine" = 1 ] || warn "that is not an address of this server (fine if a router / NAT forwards it here)"
fi

# ---- app: accept the new name ---------------------------------------------------------------------------
step "Application settings"
add_to_list DJANGO_ALLOWED_HOSTS "$DOMAIN"
add_to_list DJANGO_CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
chown --reference="$BACKUP/env" "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"
ok ".env: $DOMAIN added to the allowed names"

# ---- nginx: answer to the domain too (the IP keeps working) ---------------------------------------------
step "nginx"
if ! grep -qE "server_name[^;]*[[:space:]]$DOMAIN([[:space:]]|;)" "$SITE"; then
  sed -i -E "s/^([[:space:]]*server_name[[:space:]]+)([^;]*);/\1$DOMAIN \2;/" "$SITE"
fi
nginx -t >/dev/null 2>&1 || { restore; die "nginx rejected the change; nothing was changed."; }
systemctl reload nginx; ok "nginx answers to $DOMAIN"

# ---- certificate ----------------------------------------------------------------------------------------
step "HTTPS certificate"
GOT_LE=0
if [ "$SELF_SIGNED" = 0 ] && [ -n "$RESOLVED" ]; then
  need=(); for p in certbot python3-certbot-nginx; do dpkg -s "$p" >/dev/null 2>&1 || need+=("$p"); done
  [ ${#need[@]} -eq 0 ] || { DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need[@]}" >/dev/null; ok "installed: ${need[*]}"; }
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; fi
  if [ -n "$EMAIL" ]; then ACCT=(-m "$EMAIL"); else ACCT=(--register-unsafely-without-email); fi
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos "${ACCT[@]}" --redirect --keep-until-expiring >"$BACKUP/certbot.log" 2>&1; then
    GOT_LE=1; ok "Let's Encrypt certificate installed (renews automatically)"
  else
    warn "Let's Encrypt did not issue a certificate (details: $BACKUP/certbot.log)."
    warn "Usual causes: DNS not pointing here yet, or port 80 not reachable from the internet."
  fi
fi
if [ "$GOT_LE" = 0 ]; then
  CRT="/etc/ssl/dbms/$DOMAIN.crt"; KEY="/etc/ssl/dbms/$DOMAIN.key"
  mkdir -p /etc/ssl/dbms; chmod 700 /etc/ssl/dbms
  if [ ! -f "$CRT" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$DOMAIN" -addext "subjectAltName=DNS:$DOMAIN" \
      -keyout "$KEY" -out "$CRT" >/dev/null 2>&1 || { restore; die "Could not create a certificate"; }
    chmod 600 "$KEY"
  fi
  # use it in the HTTPS server block of the site (only if that block does not use a Let's Encrypt one)
  if grep -q "ssl_certificate[[:space:]]" "$SITE" && ! grep -q "/etc/letsencrypt/" "$SITE"; then
    sed -i -E "s|^([[:space:]]*ssl_certificate)[[:space:]]+[^;]+;|\1     $CRT;|; s|^([[:space:]]*ssl_certificate_key)[[:space:]]+[^;]+;|\1 $KEY;|" "$SITE"
  fi
  if nginx -t >/dev/null 2>&1; then systemctl reload nginx; warn "self-signed certificate for $DOMAIN in use (browser shows 'Not secure'). Run this script again once DNS / port 80 are ready."
  else restore; die "nginx rejected the certificate settings; previous settings restored."; fi
fi

# ---- secure cookies on HTTPS, restart, check ------------------------------------------------------------
for k in DBMS_BEHIND_PROXY DBMS_SECURE_COOKIES DBMS_FORCE_HTTPS; do [ "$(env_get $k)" = 1 ] || env_set $k 1; done
systemctl restart vault
for _ in $(seq 1 20); do curl -fsSk --resolve "$DOMAIN:443:127.0.0.1" -o /dev/null "https://$DOMAIN/healthz" && break; sleep 1; done
if curl -fsSk --resolve "$DOMAIN:443:127.0.0.1" -o /dev/null "https://$DOMAIN/healthz"; then
  printf "\n${c_g}Done.${c_0} Open https://%s  (the IP address keeps working too)\n" "$DOMAIN"
else
  restore; systemctl restart vault; die "The website did not answer on https://$DOMAIN; previous settings restored (see: journalctl -u vault -n 50)."
fi
