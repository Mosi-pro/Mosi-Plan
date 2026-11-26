# Testbericht

Stand: 26.11.2026. Umgebung: Linux-Container, Python 3.13, PostgreSQL 16 (lokal für Tests; Produktion nutzt 17), Node 22, Chromium (Playwright).

## 1. Backend – automatisierte Tests (pytest)
`cd backend && python -m pytest` → **57 bestanden, 0 fehlgeschlagen**. Die Tests führen zuerst die echten Alembic-Migrationen auf einer leeren Datenbank aus.

| Bereich | Datei | Geprüft |
|---|---|---|
| Login/Logout, Sicherheit | `test_auth.py` | Login, falsches Passwort, Logout invalidiert Sitzung, CSRF-Pflicht, Argon2id, Rate-Limit (429), geschützte Endpunkte (401), Passwortänderung inkl. Stärkeprüfung, Profil/Zeitzonen-Validierung, Avatar-Upload mit Magic-Byte-Prüfung |
| Datenbank, Projekte, Aufgaben | `test_projects_tasks.py` | Anlegen/Bearbeiten, Fortschritt, Unteraufgaben (max. eine Ebene), Status/Prioritäten, Abschließen, Löschen archiviert offene Aufgaben, Dashboard-Zusammenfassung aus echten Daten, globale Suche |
| Interner Kalender | `test_calendar.py` | CRUD, Konflikterkennung, ganztägige Termine, Wiederholungen über die Zeitumstellung (09:00 bleibt 09:00), Einzeltermin löschen, ungültige RRULE, Kategorien & Filter |
| Google Calendar & Sync | `test_google.py` | OAuth-Flow inkl. State-Prüfung, Kalenderliste, Sync ohne Duplikate, Löschungen aus Google, ganztägig/transparent, Schreiben, ETag-Konflikt (412 → 409), Nur-Lese-Kalender, abgelaufenes Token mit klarer Meldung, Trennen. Gegen einen simulierten Google-Server (`httpx.MockTransport`) – ein echtes Google-Konto war nicht verfügbar. |
| KI-Werkzeuge & MCP | `test_tools.py` | Pflichtwerkzeuge vorhanden, kein Shell-/Dateiwerkzeug, Validierung, Bestätigungspflicht (Löschen, Massenänderung, Projektplan, Google-Schreiben), Bestätigen/Ablehnen, Projektplan mit Abhängigkeiten/Zyklus-Erkennung, MCP-Endpunkt (Auth, initialize, tools/list, tools/call) |
| Agent | `test_agent.py` | Hermes-Streaming (SSE inkl. `hermes.tool.progress`), direkter Anbieter mit Werkzeugaufrufen, Fallback bei Hermes-Ausfall, App bleibt bei KI-Ausfall nutzbar, Bestätigungen werden der Nachricht zugeordnet |
| Wochenplaner | `test_planner.py` | Keine Überschneidungen, nur Arbeitstage/-zeiten, Mittagspause, Puffer, Blocklänge, Deadline-Priorität, Freigabe erzeugt nur interne Termine, keine Doppelplanung, Verschieben/Entfernen/Neu generieren/Verwerfen, Verlauf, Sonntags-Job genau einmal + Benachrichtigung |
| Gedächtnis, Benachrichtigungen, Sprache, System | `test_misc.py` | Gedächtnis-CRUD, deutsche Volltextsuche, Ablehnung sensibler Daten; Terminerinnerung ohne Doppelmeldung, Überfällig-Digest, Typfilter, Discord (Mock), VAPID/Push-Abo; STT/TTS-Server-Proxys (Mock), Einstellungsvalidierung, Systemstatus, Speicherbericht, Export ohne Passwort-Hash, Sicherheitsheader |

## 2. Frontend
- TypeScript-Typprüfung (`tsc -b`, strict) und Produktions-Build (`vite build`): **erfolgreich**.
- Browser-Ende-zu-Ende-Test (Playwright, Chromium, Desktop 1440×900 und iPhone 13) gegen echtes Backend + Produktions-Build: **23 von 23 bestanden** – Login (falsch/richtig), Projekt/Aufgabe/Termin per Dialog und Tastenkürzel, Abhaken, Befehlsleiste `Strg+K`, Kalenderansichten, alle Seiten, Wochenplan-Entwurf, Sprach-Overlay, PWA-Manifest, Service-Worker-Registrierung, keine JS-Fehler, **kein horizontales Scrollen auf dem Smartphone**, mobiler Mikrofonbutton. Screenshots: `docs/screenshots/`.

## 3. Deployment
- `docker compose config` gültig; Shell-Skripte syntaktisch geprüft (`bash -n`).
- Image-Build in der Testumgebung **nicht vollständig möglich**: Docker Hub antwortete mit „429 Too Many Requests“ (Limit der Sandbox), Alpine-Paketquellen waren gesperrt. Daraufhin wurde das Frontend-Image so umgebaut, dass es keine Zusatzpakete mehr benötigt.
- **Noch nicht durchgeführt:** Installation auf einem frischen Debian-13-Server, Let's-Encrypt-Ausstellung, Start des echten Hermes-Containers mit einem echten Modellanbieter, echtes Google-Konto, Mikrofonaufnahme/Sprachausgabe auf echten Geräten (Headless-Browser hat kein Mikrofon; die Fehlerbehandlung wurde geprüft), Push auf iOS/Android, `backup.sh`/`restore.sh` gegen laufende Container. Diese Punkte bitte bei der Erstinstallation prüfen (Checkliste unten).

## 4. Checkliste für die Erstinstallation
1. `sudo ./install.sh` → Abschlussmeldung und `./scripts/status.sh` grün
2. Anmelden, Einstellungen → System: Datenbank ok, Hermes „verbunden“
3. Einstellungen → KI → „Verbindung testen“
4. Assistent: „Was habe ich diese Woche noch offen?“
5. Mikrofonbutton auf PC und Smartphone (HTTPS!), Stimme unter Einstellungen → Sprache testen
6. Google verbinden (docs/GOOGLE_CALENDAR.md), synchronisieren
7. Wochenplan erstellen und freigeben
8. `sudo ./scripts/backup.sh`, danach testweise `restore.sh`
