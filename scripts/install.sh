#!/usr/bin/env bash
# MOSI PLAN – Installation auf Debian 13 (trixie). Aufruf: sudo ./install.sh
source "$(dirname "$0")/common.sh"
need_root
echo; echo "  MOSI PLAN – Installation"; echo

# 1. System prüfen
c_info "System wird geprüft …"
. /etc/os-release || die "Betriebssystem nicht erkennbar."
if [ "${ID:-}" != "debian" ] || [ "${VERSION_ID:-}" != "13" ]; then
  c_warn "Erkannt: ${PRETTY_NAME:-unbekannt}. Unterstützt wird Debian 13."; confirm "Trotzdem fortfahren?" || exit 1
else c_ok "Debian 13 erkannt"; fi
ARCH=$(dpkg --print-architecture); [[ "$ARCH" =~ ^(amd64|arm64)$ ]] || die "Architektur $ARCH wird nicht unterstützt."
FREE_GB=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc 0-9)
[ "$FREE_GB" -ge 8 ] || die "Zu wenig freier Speicher ($FREE_GB GB). Mindestens 8 GB nötig."
c_ok "Freier Speicher: ${FREE_GB} GB"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo); [ "$MEM_MB" -ge 1500 ] || c_warn "Wenig Arbeitsspeicher (${MEM_MB} MB). Empfohlen: 2 GB+."

# 2.–4. Docker
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  c_info "Docker wird aus dem offiziellen Docker-Repository installiert …"
  apt-get update -qq && apt-get install -y -qq ca-certificates curl openssl >/dev/null
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME:-trixie} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -qq && apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  systemctl enable --now docker >/dev/null
fi
c_ok "Docker $(docker --version | awk '{print $3}' | tr -d ,) mit Compose verfügbar"
command -v openssl >/dev/null || apt-get install -y -qq openssl >/dev/null
# Docker-Logrotation global begrenzen (zusätzlich zu den Compose-Einstellungen)
if [ ! -f /etc/docker/daemon.json ]; then
  echo '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }' > /etc/docker/daemon.json
  systemctl restart docker
fi

# 5. Verzeichnisse
mkdir -p data/{postgres,app/backups,app/uploads,app/tmp,hermes,certs,acme,ollama}
chown -R 1000:1000 data/app

# 6./7. Konfiguration + Secrets
if [ -f .env ]; then
  c_ok "Vorhandene .env wird beibehalten"
else
  rand() { openssl rand -hex "$1"; }
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  read -r -p "Domain für MOSI PLAN (leer lassen, wenn nur IP/VPN): " DOMAIN
  if [ -n "$DOMAIN" ]; then
    read -r -p "Let's-Encrypt-Zertifikat automatisch holen? (Port 80 muss erreichbar sein) [J/n]: " LE
    TLS=selfsigned; [ "${LE,,}" != "n" ] && TLS=letsencrypt
    NAME="$DOMAIN"; URL="https://$DOMAIN"
  else
    TLS=selfsigned; NAME="${IP:-localhost}"; URL="https://${IP:-localhost}"
    c_warn "Ohne Domain wird ein selbstsigniertes Zertifikat verwendet (Browser-Warnung einmalig bestätigen)."
  fi
  echo
  echo "KI (Sprachmodell) für MOSI:"
  echo "  1) Lokal & kostenlos auf diesem Server (Ollama, nur CPU – langsamer, keine Daten nach außen)  [empfohlen]"
  echo "  2) OpenRouter (extern, Kosten/Limits je nach Modell)"
  echo "  3) Anderer OpenAI-kompatibler Endpunkt"
  echo "  4) Später einrichten"
  read -r -p "Auswahl [1]: " P; P=${P:-1}
  PROVIDER=""; MODEL=""; BASE=""; KEY=""; PROFILES="hermes"; AIMODE="hermes"; CTX=8192
  if [ "$P" = "1" ]; then
    PROVIDER=custom; BASE="http://ollama:11434/v1"; PROFILES="hermes,ollama"; AIMODE="direct"
    # Modell nach Arbeitsspeicher wählen (Qwen 2.5 unterstützt Werkzeugaufrufe in Ollama)
    if [ "$MEM_MB" -ge 14000 ]; then MODEL="qwen2.5:7b"; CTX=16384
    elif [ "$MEM_MB" -ge 7000 ]; then MODEL="qwen2.5:7b"; CTX=8192
    else MODEL="qwen2.5:3b"; CTX=8192; fi
    c_info "Arbeitsspeicher ${MEM_MB} MB -> lokales Modell ${MODEL} (Kontext ${CTX})"
    read -r -p "Anderes Ollama-Modell verwenden? (leer = ${MODEL}): " M2; MODEL=${M2:-$MODEL}
    KEY="ollama"
  elif [ "$P" = "2" ]; then
    PROVIDER=openrouter; BASE="https://openrouter.ai/api/v1"
    read -r -p "OpenRouter-Modell (Modell-ID von openrouter.ai/models): " MODEL
    read -r -s -p "OpenRouter-API-Schlüssel: " KEY; echo
  elif [ "$P" = "3" ]; then
    PROVIDER=custom
    read -r -p "Basis-URL (z. B. http://192.168.1.10:11434/v1): " BASE
    read -r -p "Modellname: " MODEL
    read -r -s -p "API-Schlüssel (leer, falls keiner): " KEY; echo
  fi
  cat > .env <<EOV
POSTGRES_PASSWORD=$(rand 24)
SECRET_KEY=$(rand 32)
PUBLIC_URL=$URL
SERVER_NAME=$NAME
SERVER_IP=$IP
TLS_MODE=$([ "$TLS" = letsencrypt ] && echo custom || echo selfsigned)
HTTP_PORT=80
HTTPS_PORT=443
COOKIE_SECURE=true
COMPOSE_PROFILES=$PROFILES
AI_MODE=$AIMODE
OLLAMA_CONTEXT_LENGTH=$CTX
HERMES_ENABLED=true
HERMES_IMAGE=nousresearch/hermes-agent:stable
HERMES_API_KEY=$(rand 32)
MCP_TOKEN=$(rand 32)
AI_DIRECT_BASE_URL=$BASE
AI_DIRECT_MODEL=$MODEL
AI_DIRECT_API_KEY=$KEY
STORAGE_LIMIT_GB=30
MAX_UPLOAD_MB=10
LOG_LEVEL=INFO
EOV
  chmod 600 .env
  # Hermes-Konfiguration
  BASELINE=""; [ -n "$BASE" ] && BASELINE="  base_url: \"$BASE\""
  sed -e "s|__HERMES_PROVIDER__|${PROVIDER:-custom}|" -e "s|__HERMES_MODEL__|${MODEL}|" -e "s|__HERMES_BASE_URL_LINE__|$BASELINE|" deployment/hermes/config.yaml.template > data/hermes/config.yaml
  {
    echo "API_SERVER_KEY=$(env_get HERMES_API_KEY)"
    echo "MOSI_MCP_TOKEN=$(env_get MCP_TOKEN)"
    [ "$PROVIDER" = openrouter ] && echo "OPENROUTER_API_KEY=$KEY"
    [ "$PROVIDER" = custom ] && [ -n "$KEY" ] && echo "OPENAI_API_KEY=$KEY"
    true
  } > data/hermes/.env
  chmod 600 data/hermes/.env
  chown -R 10000:10000 data/hermes   # Hermes-Container läuft als UID 10000
  c_ok "Konfiguration und Secrets erzeugt (.env, data/hermes/)"
  if [ "$TLS" = letsencrypt ]; then
    c_info "Let's-Encrypt-Zertifikat wird angefordert …"
    apt-get install -y -qq certbot >/dev/null
    if certbot certonly --standalone --non-interactive --agree-tos --register-unsafely-without-email -d "$DOMAIN"; then
      cp -L "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "/etc/letsencrypt/live/$DOMAIN/privkey.pem" data/certs/
      echo "0 4 * * 1 root certbot renew --quiet --webroot -w $ROOT/data/acme --deploy-hook 'cp -L /etc/letsencrypt/live/$DOMAIN/*.pem $ROOT/data/certs/ && docker compose -f $ROOT/docker-compose.yml restart frontend'" > /etc/cron.d/mosi-certbot
      c_ok "Zertifikat installiert (automatische Erneuerung eingerichtet)"
    else
      c_warn "Zertifikat konnte nicht geholt werden – nutze selbstsigniertes Zertifikat."; sed -i 's/^TLS_MODE=.*/TLS_MODE=selfsigned/' .env
    fi
  fi
fi
[ -f data/hermes/.env ] || touch data/hermes/.env
# Selbstsigniertes Zertifikat (falls kein anderes vorhanden)
if [ ! -s data/certs/fullchain.pem ]; then
  SN=$(env_get SERVER_NAME); SIP=$(env_get SERVER_IP)
  SAN="DNS:${SN:-localhost},DNS:localhost,IP:127.0.0.1"
  [[ "$SN" =~ ^[0-9.]+$ ]] && SAN="IP:$SN,DNS:localhost,IP:127.0.0.1"
  [ -n "$SIP" ] && [ "$SIP" != "$SN" ] && SAN="$SAN,IP:$SIP"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 -keyout data/certs/privkey.pem -out data/certs/fullchain.pem \
    -subj "/CN=${SN:-localhost}" -addext "subjectAltName=$SAN" >/dev/null 2>&1
  chmod 644 data/certs/fullchain.pem; chmod 600 data/certs/privkey.pem
  c_ok "Selbstsigniertes Zertifikat erzeugt (data/certs/)"
fi

# Ports prüfen (häufig: Apache/nginx des Systems belegt Port 80/443)
for PORT in $(env_get HTTP_PORT) $(env_get HTTPS_PORT); do
  if ss -ltnH "sport = :$PORT" 2>/dev/null | grep -q . && ! docker ps --format '{{.Names}}' | grep -q 'mosi-plan-frontend'; then
    PROC=$(ss -ltnpH "sport = :$PORT" 2>/dev/null | grep -o 'users:(("[^"]*' | head -1 | cut -d'"' -f2)
    c_err "Port $PORT ist bereits belegt (Programm: ${PROC:-unbekannt})."
    echo "   Lösung A: anderes Programm stoppen, z. B.:  systemctl disable --now ${PROC:-apache2}"
    echo "   Lösung B: andere Ports in .env setzen (HTTP_PORT=8080, HTTPS_PORT=8443) und install.sh erneut starten"
    exit 1
  fi
done

# 8.–10. Datenbank, Migrationen, Anwendung
c_info "Container werden gebaut und gestartet (dauert beim ersten Mal einige Minuten) …"
dc build --pull -q
dc up -d database
dc up -d backend   # führt beim Start die Datenbankmigrationen aus
dc up -d

# 11. Healthchecks
c_info "Warte auf Healthchecks …"
for i in $(seq 1 60); do
  if dc exec -T backend curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then c_ok "Backend und Datenbank laufen"; break; fi
  sleep 3; [ "$i" = 60 ] && die "Backend startet nicht. Details: ./scripts/logs.sh backend"
done

# Lokales Modell herunterladen (einmalig, einige GB)
if grep -q "ollama" <<<"$(env_get COMPOSE_PROFILES)"; then
  OM=$(env_get AI_DIRECT_MODEL)
  c_info "Lokales Sprachmodell ${OM} wird heruntergeladen (einmalig, je nach Modell 2–5 GB) …"
  for i in $(seq 1 20); do dc exec -T ollama ollama list >/dev/null 2>&1 && break; sleep 3; done
  if dc exec -T ollama ollama pull "$OM"; then c_ok "Modell ${OM} bereit"; else c_warn "Download fehlgeschlagen – später erneut: docker compose exec ollama ollama pull ${OM}"; fi
fi

# Administrator anlegen
if ! dc exec -T backend python -m app.cli has-admin; then
  echo; c_info "Administratorkonto anlegen"
  read -r -p "Benutzername [admin]: " ADMIN; ADMIN=${ADMIN:-admin}
  read -r -p "Anzeigename: " DNAME
  while true; do
    read -r -s -p "Passwort (mind. 10 Zeichen, Groß-/Kleinbuchstaben, Ziffer): " PW; echo
    read -r -s -p "Passwort wiederholen: " PW2; echo
    [ "$PW" = "$PW2" ] || { c_warn "Passwörter stimmen nicht überein."; continue; }
    printf '%s\n' "$PW" | dc exec -T backend python -m app.cli create-admin --username "$ADMIN" --name "$DNAME" && break
  done
  unset PW PW2
fi
if dc ps hermes --format '{{.State}}' 2>/dev/null | grep -q running; then c_ok "Hermes Agent läuft"; else c_warn "Hermes läuft (noch) nicht – MOSI funktioniert trotzdem. Details: ./scripts/logs.sh hermes"; fi

# 12. Infos
URL=$(env_get PUBLIC_URL)
echo
c_ok "MOSI PLAN ist installiert."
echo "   Adresse:        $URL"
echo "   Verwaltung:     ./scripts/status.sh | logs.sh | backup.sh | update.sh"
echo "   Google Calendar: siehe docs/GOOGLE_CALENDAR.md (Redirect-URI: $URL/api/google/callback)"
[ "$(env_get TLS_MODE)" = selfsigned ] && echo "   Hinweis: Selbstsigniertes Zertifikat – im Browser einmalig bestätigen. Für Mikrofon auf dem Handy wird ein vertrauenswürdiges Zertifikat empfohlen (docs/HTTPS.md)."
echo
