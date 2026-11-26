# MOSI PLAN

**Your personal AI planning assistant.** MOSI PLAN ist ein persönlicher Planer für eine Person: Dashboard, interner Kalender und Google Calendar, Projekte, Aufgaben, ein automatischer Wochenplan, ein dauerhaftes Gedächtnis und ein Sprachassistent auf Basis von [Hermes Agent](https://github.com/NousResearch/hermes-agent).

## Installation in drei Schritten (Debian 13)

```bash
git clone <dieses-repository> mosi-plan && cd mosi-plan
```

```bash
sudo ./install.sh
```

Das Skript prüft das System, installiert bei Bedarf Docker, erzeugt sichere Secrets, fragt Domain und KI-Anbieter ab, startet alles und legt das Administratorkonto an. Danach ist MOSI PLAN unter der angezeigten HTTPS-Adresse erreichbar.

Details: [docs/INSTALLATION.md](docs/INSTALLATION.md)

## Verwaltung

| Befehl | Zweck |
|---|---|
| `sudo ./scripts/update.sh` | Backup, neuer Code, Migrationen, Neustart |
| `sudo ./scripts/backup.sh` | Vollständiges Backup (Datenbank, Uploads, Konfiguration) |
| `sudo ./scripts/restore.sh <datei>` | Backup wiederherstellen (mit Bestätigung) |
| `./scripts/status.sh` | Containerstatus, Health, Speicherverbrauch |
| `./scripts/logs.sh [dienst] [-f]` | Logs anzeigen |
| `sudo ./scripts/uninstall.sh` | Entfernen (Daten nur nach ausdrücklicher Bestätigung) |

## Funktionen

- **Dashboard** mit datenbasierter Tageszusammenfassung, Tagesleiste, fälligen/überfälligen Aufgaben, Deadlines und Projekten (anpassbar)
- **KI-Assistent** (Chat und Sprache) mit kontrollierten Werkzeugen; Löschen, Massenänderungen, Projektpläne und Schreiben in Google brauchen deine Bestätigung
- **Sprachsteuerung**: Mikrofonbutton auf allen Seiten, Wellenform, Statusfolge (Aufnahme → Verarbeitung → Denken → Aktion → Antwort → Fertig), Vorlesen mit männlicher deutscher Stimme
- **Kalender**: interner MOSI-Kalender (Kategorien, Wiederholungen, Erinnerungen, ganztägig) und Google Calendar (OAuth, Sync, Konflikterkennung); Tag/Woche/Monat/Liste, Drag-and-drop
- **Projekte & Aufgaben** mit Unteraufgaben, Abhängigkeiten, Fortschritt, Verlauf, KI-Zusammenfassung
- **Intelligente Projektplanung**: MOSI zerlegt Vorhaben, schätzt Aufwand, prüft den Kalender und legt den Plan zur Bestätigung vor
- **Automatischer Wochenplan** jeden Sonntag 18:00 (Europe/Berlin) als Entwurf: bestätigen, bearbeiten, neu generieren, verwerfen, Verlauf
- **Gedächtnis** mit deutscher Volltextsuche; sensible Daten werden abgelehnt
- **Benachrichtigungen**: In-App, Browser, Web-Push (PWA), Discord
- **Globale Befehlsleiste** (`Strg+K`), Tastenkürzel `N` für neue Aufgabe
- **PWA** für Android und iOS

## Dokumentation

- [Installation & Betrieb](docs/INSTALLATION.md)
- [HTTPS, Mikrofon & PWA](docs/HTTPS.md)
- [KI: Hermes Agent & Anbieter](docs/KI_HERMES.md)
- [Google Calendar einrichten](docs/GOOGLE_CALENDAR.md)
- [Architektur & Sicherheit](docs/ARCHITEKTUR.md)
- [Testbericht](docs/TESTBERICHT.md)

## Entwicklung

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd backend && .venv/bin/python -m pytest
```

```bash
cd frontend && npm install && npm run dev
```
