#!/usr/bin/env bash
# Logs anzeigen: ./scripts/logs.sh [backend|frontend|database|hermes] [-f]
source "$(dirname "$0")/common.sh"
dc logs --tail=200 "$@"
