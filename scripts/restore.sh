#!/usr/bin/env bash
# Stellt ein Backup wieder her. Aufruf: sudo ./scripts/restore.sh data/app/backups/mosi-full-….tar.gz
source "$(dirname "$0")/common.sh"
need_root
FILE="${1:-}"; [ -f "$FILE" ] || die "Backup-Datei angeben: $0 <datei.tar.gz>"
c_warn "Die aktuelle Datenbank wird durch das Backup ERSETZT."
confirm "Wiederherstellung von $(basename "$FILE") starten?" || exit 1
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
tar -C "$TMP" -xzf "$FILE"
[ -f "$TMP/database.dump" ] || die "Ungültiges Backup (database.dump fehlt)."
c_info "Sicherheitskopie des aktuellen Stands …"; "$ROOT/scripts/backup.sh" "$ROOT/data/app/backups/pre-restore" >/dev/null || true
dc stop backend
dc exec -T database psql -U mosi -d postgres -c "DROP DATABASE IF EXISTS mosi WITH (FORCE);" -c "CREATE DATABASE mosi OWNER mosi;" >/dev/null
dc exec -T database pg_restore -U mosi -d mosi --no-owner < "$TMP/database.dump" || die "pg_restore fehlgeschlagen"
if [ -f "$TMP/files.tar" ]; then tar -C "$ROOT/data" -xf "$TMP/files.tar"; chown -R 1000:1000 data/app; fi
c_warn "Hinweis: .env aus dem Backup liegt in $FILE (Datei 'env'). Bei einem neuen Server SECRET_KEY von dort übernehmen, sonst sind gespeicherte API-Schlüssel nicht lesbar."
dc up -d backend
for i in $(seq 1 40); do dc exec -T backend curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 3; done
c_ok "Wiederherstellung abgeschlossen."
