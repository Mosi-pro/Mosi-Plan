#!/bin/sh
# Erzeugt die Nginx-Konfiguration je nach HTTPS-Modus:
#   TLS_MODE=off        nur HTTP (Mikrofon/PWA nur über localhost!)
#   TLS_MODE=selfsigned selbstsigniertes Zertifikat (für VPN/LAN, Browser-Warnung)
#   TLS_MODE=custom     eigenes Zertifikat unter /certs/fullchain.pem + /certs/privkey.pem (z. B. Let's Encrypt)
set -e
MODE="${TLS_MODE:-selfsigned}"
CONF=/etc/nginx/conf.d/mosi.conf
mkdir -p /certs
if [ "$MODE" = "off" ]; then
  cat > $CONF <<EOC
server { listen 80 default_server; listen [::]:80 default_server; server_name _; include /etc/nginx/mosi/common.conf; }
EOC
  exit 0
fi
if [ "$MODE" = "selfsigned" ] && [ ! -s /certs/fullchain.pem ] && command -v openssl >/dev/null; then
  echo "Erzeuge selbstsigniertes Zertifikat für ${SERVER_NAME:-localhost}"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 -keyout /certs/privkey.pem -out /certs/fullchain.pem \
    -subj "/CN=${SERVER_NAME:-localhost}" -addext "subjectAltName=DNS:${SERVER_NAME:-localhost},DNS:localhost,IP:127.0.0.1${SERVER_IP:+,IP:$SERVER_IP}" >/dev/null 2>&1
fi
if [ ! -s /certs/fullchain.pem ]; then
  echo "FEHLER: Kein Zertifikat in data/certs/ (fullchain.pem, privkey.pem). install.sh erneut ausführen oder TLS_MODE=off setzen." >&2
  exit 1
fi
cat > $CONF <<EOC
server { listen 80 default_server; listen [::]:80 default_server; server_name _;
  location /.well-known/acme-challenge/ { root /var/www/acme; }
  location / { return 301 https://\$host\$request_uri; } }
server { listen 443 ssl default_server; listen [::]:443 ssl default_server; http2 on; server_name _;
  ssl_certificate /certs/fullchain.pem; ssl_certificate_key /certs/privkey.pem;
  ssl_protocols TLSv1.2 TLSv1.3; ssl_session_cache shared:SSL:5m;
  add_header Strict-Transport-Security "max-age=31536000" always;
  include /etc/nginx/mosi/common.conf; }
EOC
