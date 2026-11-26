#!/usr/bin/env bash
# Gemeinsame Hilfsfunktionen
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
c_ok() { printf '\033[32m✓\033[0m %s\n' "$*"; }
c_info() { printf '\033[34m›\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_err() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; }
die() { c_err "$*"; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "Bitte mit sudo ausführen: sudo $0 $*"; }
dc() { docker compose "$@"; }
confirm() { # confirm "Frage" -> erwartet exakt "ja"
  local ans; read -r -p "$1 Tippe 'ja' zum Bestätigen: " ans; [ "$ans" = "ja" ];
}
env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }
