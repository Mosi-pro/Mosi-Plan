# Installation & Betrieb

## Voraussetzungen
- Debian 13 (trixie), amd64 oder arm64, Root-Zugang (sudo)
- mindestens 2 GB RAM, 8 GB freier Speicher (Betrieb plant mit max. 15 GB, hartes Limit 30 GB)
- optional eine Domain, die auf den Server zeigt (für ein gültiges HTTPS-Zertifikat)
- optional ein KI-Anbieter (siehe [KI_HERMES.md](KI_HERMES.md))

## Ablauf von `sudo ./install.sh`
1. Prüft Betriebssystem, Architektur, freien Speicher und RAM
2. Installiert Docker Engine + Compose-Plugin aus dem offiziellen Docker-Repository (falls nötig) und setzt Docker-Logrotation
3. Legt `data/` an (Datenbank, Uploads, Backups, Hermes, Zertifikate)
4. Fragt Domain, HTTPS-Variante und KI-Anbieter ab und erzeugt `.env` mit zufälligen Secrets (`openssl rand`), Rechte 600
5. Erzeugt `data/hermes/config.yaml` aus `deployment/hermes/config.yaml.template`
6. Baut die Images, startet Datenbank und Backend (Migrationen laufen automatisch), danach alle Dienste
7. Führt Healthchecks aus, legt das Administratorkonto an (Passwort wird nicht gespeichert, nur als Argon2id-Hash)
8. Zeigt Adresse und nächste Schritte

Ein erneuter Aufruf ist gefahrlos: vorhandene `.env` und Daten bleiben erhalten.

## Container
| Dienst | Aufgabe | Ports |
|---|---|---|
| `database` | PostgreSQL 17 | nur intern |
| `backend` | FastAPI, Jobs, MCP-Endpunkt für Hermes | nur intern |
| `frontend` | Nginx: App + Reverse Proxy + TLS | 80, 443 |
| `hermes` | Hermes Agent Gateway (API-Server) | nur intern |

Alle Dienste haben `restart: unless-stopped` – nach einem Server-Neustart startet MOSI PLAN automatisch.

## Speicherbegrenzung
- Docker-Logs: max. 3 × 10 MB je Container (Compose) und global per `/etc/docker/daemon.json`
- Uploads: max. 10 MB je Datei (Profilbild 2 MB); Audio wird **nie** gespeichert, nur zur Transkription weitergereicht
- Backups: 14 Datenbank-Backups (täglich 02:30) und 14 Voll-Backups (`backup.sh`)
- Tägliche Bereinigung (03:30): alte Benachrichtigungen (90 Tage), Audit-Log (365 Tage), abgelaufene Sitzungen, temporäre Dateien
- Speicherüberwachung: Hinweis in der App bei 80 % und 90 % des Limits `STORAGE_LIMIT_GB` (Standard 30), Anzeige unter Einstellungen → System und in `status.sh`
- Keine lokalen Sprach- oder KI-Modelle werden heruntergeladen. Größter Posten ist das Hermes-Image (mehrere GB).

## Updates und Backups
`update.sh` erstellt zuerst ein Voll-Backup, zieht den neuen Code, baut neu und startet; Migrationen sind additiv (Alembic). Wiederherstellung mit `restore.sh` (fragt nach ausdrücklicher Bestätigung und sichert vorher den aktuellen Stand).

## Passwort vergessen
```bash
sudo docker compose exec backend python -m app.cli reset-password --username admin
```
