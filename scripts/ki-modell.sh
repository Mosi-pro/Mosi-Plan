#!/usr/bin/env bash
# Wechselt das lokale KI-Modell (Ollama). Beispiel: sudo ./scripts/ki-modell.sh qwen2.5:3b
# Empfehlung nach RAM: unter 6 GB qwen2.5:1.5b · 6–11 GB qwen2.5:3b · ab 11 GB qwen2.5:7b
source "$(dirname "$0")/common.sh"
need_root
MODEL="${1:-}"; [ -n "$MODEL" ] || die "Modell angeben, z. B.: sudo $0 qwen2.5:3b"
grep -q "ollama" <<<"$(env_get COMPOSE_PROFILES)" || die "Lokale KI (Ollama) ist nicht aktiviert (COMPOSE_PROFILES in .env)."
echo "Arbeitsspeicher: $(free -h | awk '/Mem:/ {print $2 " gesamt, " $7 " verfügbar"}')"
dc up -d ollama >/dev/null
c_info "Lade ${MODEL} …"
dc exec -T ollama ollama pull "$MODEL" || die "Download fehlgeschlagen."
sed -i "s|^AI_DIRECT_MODEL=.*|AI_DIRECT_MODEL=${MODEL}|" .env
dc exec -T backend python -m app.cli set-ai-model --model "$MODEL" --base-url "http://ollama:11434/v1"
# Nicht mehr verwendete Modelle entfernen (spart Speicher)
for OLD in $(dc exec -T ollama ollama list | awk 'NR>1 {print $1}'); do
  [ "$OLD" != "$MODEL" ] && [ "$OLD" != "${MODEL}:latest" ] && dc exec -T ollama ollama rm "$OLD" >/dev/null && c_info "Entfernt: $OLD"
done
dc restart ollama >/dev/null
c_ok "Fertig. Unter Einstellungen → KI „Verbindung testen“ (erste Antwort kann bis zu 1 Minute dauern)."
