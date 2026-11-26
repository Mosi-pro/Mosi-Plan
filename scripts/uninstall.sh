#!/usr/bin/env bash
# Entfernt MOSI PLAN. Daten werden nur nach ausdrücklicher Bestätigung gelöscht.
source "$(dirname "$0")/common.sh"
need_root
confirm "Container von MOSI PLAN stoppen und entfernen?" || exit 1
dc --profile hermes down --remove-orphans
docker image rm mosi-plan-backend mosi-plan-frontend 2>/dev/null || true
c_ok "Container entfernt. Daten liegen weiterhin in $ROOT/data."
if confirm "ALLE Daten (Datenbank, Backups, Konfiguration) unwiderruflich löschen?"; then
  rm -rf "$ROOT/data" "$ROOT/.env" /etc/cron.d/mosi-certbot
  c_ok "Daten gelöscht."
fi
