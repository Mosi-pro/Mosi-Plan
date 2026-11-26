# Google Calendar einrichten

1. **Google Cloud Console öffnen**: https://console.cloud.google.com/
2. **Projekt erstellen**: oben Projektauswahl → „Neues Projekt“ → Name z. B. „MOSI PLAN“.
3. **Google Calendar API aktivieren**: „APIs & Dienste“ → „Bibliothek“ → „Google Calendar API“ → „Aktivieren“.
4. **OAuth-Zustimmungsbildschirm** („Google Auth Platform“ / „OAuth consent screen“): Nutzertyp „Extern“, App-Name, Support-E-Mail. Unter „Zielgruppe“ dein eigenes Google-Konto als **Testnutzer** eintragen. Bereich (Scope): `https://www.googleapis.com/auth/calendar`.
   - Hinweis: Solange die App im Status „Testing“ ist, können Refresh-Tokens nach einiger Zeit ablaufen (Google nennt hierfür 7 Tage). MOSI meldet das verständlich („Google-Verbindung abgelaufen – bitte neu verbinden“). Für dauerhafte Nutzung die App auf „In Produktion“ stellen (für Eigennutzung ohne Verifizierung möglich, Google zeigt dann einen Warnhinweis beim Verbinden).
5. **OAuth-Client erstellen**: „Clients“ / „Anmeldedaten“ → „Client-ID erstellen“ → Typ **Webanwendung**.
6. **Redirect-URI eintragen**: `https://DEINE-ADRESSE/api/google/callback` (exakt so, wird in MOSI unter Einstellungen → Kalender angezeigt). Google akzeptiert für Webanwendungen nur HTTPS-Adressen (oder localhost) – reine IP-Adressen werden in der Regel abgelehnt, daher eine Domain verwenden.
7. **Client-ID und Secret in MOSI eintragen**: Einstellungen → Kalender → Google Calendar → speichern (Secret wird verschlüsselt gespeichert). Alternativ `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env`.
8. **Verbindung testen**: „Mit Google verbinden“ → Google-Konto wählen → zustimmen. Danach Kalender auswählen und „Jetzt synchronisieren“.

## Synchronisationsregeln
- Google-Termine werden gespiegelt (−60 bis +400 Tage, alle 10 Minuten, einstellbar). Eindeutig über (Kalender-ID, Event-ID) → keine Duplikate.
- Google ist für Google-Termine führend; in Google gelöschte Termine verschwinden in MOSI.
- Wiederholungen werden als Einzelinstanzen geladen (`singleEvents`). Bearbeiten in MOSI ändert die jeweilige Instanz.
- Änderungen aus MOSI werden mit ETag (`If-Match`) gesendet; wurde der Termin zwischenzeitlich in Google geändert, meldet MOSI einen **Konflikt** statt zu überschreiben.
- Interne Termine und Wochenpläne werden **nie** automatisch nach Google kopiert – nur bei ausdrücklicher Auswahl.
- Zeitzonen: Speicherung in UTC, Anzeige in der Profil-Zeitzone; Sommer-/Winterzeit wird über IANA-Zeitzonen korrekt behandelt.
