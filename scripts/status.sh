#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
dc ps
echo
if dc exec -T backend curl -fsS http://127.0.0.1:8000/api/health 2>/dev/null; then echo; c_ok "Backend gesund"; else c_err "Backend antwortet nicht"; fi
LIMIT=$(env_get STORAGE_LIMIT_GB); LIMIT=${LIMIT:-30}
USED_KB=$(du -sk "$ROOT/data" 2>/dev/null | cut -f1)
IMG_KB=$(docker system df --format '{{.Type}} {{.Size}}' 2>/dev/null | head -1 | awk '{print $2}')
PCT=$(( USED_KB * 100 / (LIMIT * 1024 * 1024) ))
echo "Speicher (data/): $(du -sh "$ROOT/data" | cut -f1) von ${LIMIT} GB (${PCT} %), Docker-Images: ${IMG_KB:-?}"
[ "$PCT" -ge 90 ] && c_err "Speicher über 90 %!" || { [ "$PCT" -ge 80 ] && c_warn "Speicher über 80 %"; } || true
