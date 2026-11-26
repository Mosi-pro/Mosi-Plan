#!/usr/bin/env bash
# Vollständiges Backup: Datenbank (pg_dump), Uploads, Konfiguration. Aufbewahrung: 14 Archive.
source "$(dirname "$0")/common.sh"
DEST="${1:-$ROOT/data/app/backups}"
mkdir -p "$DEST"
TS=$(date +%Y%m%d-%H%M%S); TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
c_info "Datenbank wird gesichert …"
dc exec -T database pg_dump -U mosi -d mosi --format=custom > "$TMP/database.dump" || die "pg_dump fehlgeschlagen"
cp .env "$TMP/env" 2>/dev/null || true
tar -C "$ROOT/data" -cf "$TMP/files.tar" app/uploads hermes/config.yaml hermes/.env 2>/dev/null || tar -C "$ROOT/data" -cf "$TMP/files.tar" app/uploads
tar -C "$TMP" -czf "$DEST/mosi-full-$TS.tar.gz" database.dump env files.tar
chmod 600 "$DEST/mosi-full-$TS.tar.gz"
ls -1t "$DEST"/mosi-full-*.tar.gz | tail -n +15 | xargs -r rm -f
c_ok "Backup erstellt: $DEST/mosi-full-$TS.tar.gz ($(du -h "$DEST/mosi-full-$TS.tar.gz" | cut -f1))"
