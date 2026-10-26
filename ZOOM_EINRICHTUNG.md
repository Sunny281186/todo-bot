# Zoom-Bot einrichten: Calls → Zusammenfassung, To-Dos & Transkript in Google Drive

## Was passiert

Alle 30 Minuten läuft `zoom_bot.py` auf GitHub Actions (wie der To-Do-Bot):

1. Holt deine neuen **Zoom-Cloud-Aufnahmen** der letzten 7 Tage.
2. Nimmt das **Zoom-Transkript** (mit Sprechernamen). Gibt es keins, wartet er bis zu 3 Stunden
   und schreibt dann die Tonspur mit **Google Gemini** ab.
3. **Claude** schreibt eine ausführliche Zusammenfassung: Überblick, To-Dos (wer, bis wann, warum),
   Entscheidungen, alle Themen mit Details, offene Fragen.
4. In Google Drive entsteht im Ordner **„Zoom-Calls“** pro Call ein Unterordner, z. B.
   `2026-10-22 1400 – Kundenworkshop Müller`, mit zwei Google Docs:
   - `… – Zusammenfassung & To-Dos`
   - `… – Transkript` (mit Zeitstempeln und Sprechern)
5. Optional: To-Dos zusätzlich als **Trello-Karten**, und eine **Telegram-Nachricht** mit den Links.

Jeder Call wird nur einmal verarbeitet. Schlägt etwas fehl, versucht es der nächste Lauf erneut.

## Voraussetzungen

- Zoom-Konto mit **Cloud-Aufzeichnung** (Pro oder höher). Lokale Aufnahmen auf dem Rechner
  erreicht der Bot nicht – in Zoom beim Aufnehmen „In der Cloud aufnehmen“ wählen.

## 1. Zoom einstellen

1. zoom.us → **Einstellungen → Aufzeichnung → Cloud-Aufzeichnung**:
   - **Audio-Transkript** einschalten (sonst muss Gemini abschreiben – geht, kostet aber mehr Zeit).
   - **Nur-Audio-Datei aufnehmen** einschalten (die nutzt der Bot als Ersatz).
   - Optional „Aufzeichnung automatisch starten → in der Cloud“, dann vergisst du es nie.
2. **App anlegen:** marketplace.zoom.us → *Develop → Build App* → **Server-to-Server OAuth App**.
   - Unter *Scopes* hinzufügen: `cloud_recording:read:list_user_recordings:admin` und
     `cloud_recording:read:list_recording_files:admin` (falls Zoom die Namen anders anzeigt:
     die Scopes zum Lesen von Cloud-Aufzeichnungen).
   - App **aktivieren**. Dann **Account ID**, **Client ID** und **Client Secret** notieren.

## 2. Google Drive einrichten (einmalig, ca. 10 Minuten)

1. console.cloud.google.com → neues Projekt, z. B. „Zoom-Bot“.
2. *APIs & Dienste → Bibliothek* → **Google Drive API** aktivieren.
3. *OAuth-Zustimmungsbildschirm*: Typ **Extern**, Name „Zoom-Bot“, deine E-Mail eintragen.
   Danach auf **„App veröffentlichen“ / „In Produktion“** stellen – sonst läuft der Zugang
   nach 7 Tagen ab. (Eine Google-Prüfung ist dafür nicht nötig, die Berechtigung ist harmlos.)
4. *Anmeldedaten → Anmeldedaten erstellen → OAuth-Client-ID*, Typ **Desktop-App**.
   **Client-ID** und **Clientschlüssel** notieren.
5. Auf deinem Rechner einmal ausführen:
   ```
   python3 google_login.py
   ```
   Client-ID und Clientschlüssel eingeben, wenn danach gefragt wird. Mit dem Google-Konto anmelden, in dem die Dateien landen sollen (die Warnung „Google hat diese
   App nicht überprüft“ mit *Erweitert → Weiter* bestätigen – es ist deine eigene App).
   Im Terminal steht danach der **GOOGLE_REFRESH_TOKEN**.

Der Bot darf nur Dateien sehen, die er selbst angelegt hat – nicht den Rest deines Drives.
Den Ordner „Zoom-Calls“ legt er beim ersten Lauf selbst an. Du darfst ihn danach umbenennen,
verschieben oder freigeben; der Bot findet ihn trotzdem.

## 3. Secrets in GitHub eintragen

Repo → *Settings → Secrets and variables → Actions → New repository secret*:

| Secret | Woher |
|---|---|
| `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` | Zoom-App (Schritt 1) |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | Schritt 2 |
| `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | hast du schon vom To-Do-Bot |

Optional unter *Variables*: `ZOOM_TRELLO_LIST` = Name der Trello-Liste, in die die To-Dos als Karten
sollen (z. B. `Neue To-Do`). Leer lassen = keine Karten. Die Telegram-Nachricht kommt automatisch,
weil `TELEGRAM_TOKEN` und `TELEGRAM_CHAT_ID` schon eingetragen sind.

## 4. Testen

*Actions → Zoom-Bot → Run workflow*. Im Log steht „Abgelegt: …“ für jeden Call der letzten 7 Tage.

## Feineinstellungen (Umgebungsvariablen in `.github/workflows/zoom.yml`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `ZOOM_LOOKBACK_DAYS` | `7` | wie viele Tage zurück nach Aufnahmen gesucht wird |
| `TRANSCRIPT_WAIT_HOURS` | `3` | wie lange auf Zooms Transkript gewartet wird, bevor Gemini abschreibt |
| `ZOOM_MIN_MINUTES` | `2` | kürzere Aufnahmen werden übersprungen |
| `DRIVE_FOLDER_NAME` | `Zoom-Calls` | Name des Hauptordners beim ersten Anlegen |
| `ZOOM_CLAUDE_MODEL` | `claude-opus-5-5` | Modell für die Zusammenfassung |
