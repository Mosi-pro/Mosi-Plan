#!/usr/bin/env bash
# Aktualisiert MOSI PLAN ohne Datenverlust: Backup -> neuer Code -> Build -> Migration -> Neustart
source "$(dirname "$0")/common.sh"
need_root
c_info "Sicherheits-Backup vor dem Update …"; "$ROOT/scripts/backup.sh"
if [ -d .git ]; then c_info "Neuen Code holen …"; git pull --ff-only || die "git pull fehlgeschlagen – lokale Änderungen?"; fi
dc build --pull -q
dc pull -q hermes 2>/dev/null || true
dc up -d --remove-orphans   # Backend führt Migrationen beim Start aus
for i in $(seq 1 40); do dc exec -T backend curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 3; done
docker image prune -f >/dev/null
c_ok "Update abgeschlossen."; "$ROOT/scripts/status.sh"
