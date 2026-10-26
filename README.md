# Meine To-Dos 🎀

Eigene To-Do-App (statt Trello) mit Telegram-Bot und Erinnerungen.

**Privat:** 🎀 Sunny · 🩷 Franny
**Business:** 🎓 School-Life-Balance · 🏚️ Michelle Miller · 🏡 Markus Wagner · 🌐 Stefan Falk

- **App** (`docs/`): läuft im Browser und lässt sich aufs Handy legen wie eine echte App.
  **Liste oder Kanban-Board** (🆕 New · 📋 To-Do · 🔨 In Bearbeitung · ⏳ Wait · ✅ Erledigt) – pro Kunde oder als Gesamtübersicht;
  Karten am Laptop per Maus verschieben, am Handy im Bearbeiten-Fenster den Status wählen.
  To-Dos anlegen, Datum/Uhrzeit, Erinnerung (zum Termin, 15 Min., 1 Std., 3 Std., 1 Tag vorher oder am Vorabend um 19 Uhr), Notizen, abhaken.
- **Telegram-Bot** (`bot.py`): To-Dos per Text oder Sprachnachricht schicken – landen direkt in der App, in der richtigen Kategorie.
  `/offen` zeigt alles Offene.
- **Erinnerungen** kommen als Telegram-Nachricht mit Tasten **✅ Erledigt**, **😴 1 Std** und **😴 Morgen**.

- **Abend-Check** jeden Tag um 19 Uhr Ortszeit: Was ist überfällig, was steht heute noch und morgen an?
  Uhrzeit änderbar über die Variable `EVENING_HOUR`.
- **Zeitzone automatisch:** Die App meldet bei jedem Öffnen, in welcher Zeitzone dein Handy gerade ist (z. B. auf Reisen).
  Erinnerungen und Abend-Check richten sich dann nach der Ortszeit dort.

Daten liegen in einer **geheimen GitHub-Gist** (`todos.json`) – nicht in diesem (öffentlichen) Repo.
App und Bot lesen und schreiben dieselbe Datei.

## Einrichtung (einmalig, ca. 10 Minuten)

### 1. GitHub-Token für die Daten
1. GitHub → Settings → Developer settings → **Fine-grained tokens** → *Generate new token*
2. Name: `To-Dos`, Ablauf: z. B. 1 Jahr
3. Unter **Account permissions** → **Gists** → *Read and write*. Sonst nichts.
4. Token kopieren (`github_pat_…`).

### 2. App online stellen (GitHub Pages)
1. Diesen Branch in `main` mergen.
2. Repo → Settings → **Pages** → Source: *Deploy from a branch* → Branch `main`, Ordner **`/docs`** → Save.
3. Nach 1–2 Minuten läuft die App unter `https://sunny281186.github.io/todo-bot/`.
4. App öffnen → Token eintragen → **Verbinden**. Die App legt die geheime Gist an und zeigt dir die **Gist-ID**.
5. Aufs Handy legen: iPhone → Safari → Teilen → *Zum Home-Bildschirm*; Android → Chrome → ⋮ → *App installieren*.
   Auf weiteren Geräten einfach denselben Token eintragen – die Gist wird automatisch gefunden.

### 3. Bot & Erinnerungen
Repo → Settings → Secrets and variables → **Actions** → diese Secrets anlegen:

| Secret | Inhalt |
|---|---|
| `GIST_TOKEN` | der Token aus Schritt 1 |
| `TODO_GIST_ID` | die Gist-ID aus der App (⚙️) |
| `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | wie bisher |

`TRELLO_KEY` / `TRELLO_TOKEN` werden nicht mehr gebraucht.

Der Workflow läuft alle 5 Minuten: Er holt neue Telegram-Nachrichten ab und verschickt fällige Erinnerungen.
GitHub startet geplante Läufe manchmal ein paar Minuten später – Erinnerungen kommen also **± ein paar Minuten** genau.
Hinweis: GitHub pausiert geplante Workflows, wenn im Repo 60 Tage lang nichts passiert – dann unter *Actions* wieder aktivieren.

## Warum Telegram und nicht WhatsApp?
WhatsApp erlaubt automatische Nachrichten nur über die *WhatsApp Business Cloud API* von Meta
(Business-Konto, eigene Telefonnummer, genehmigte Nachrichtenvorlagen, ggf. Kosten pro Nachricht).
Telegram ist kostenlos, der Bot existiert schon, und die Nachrichten kommen als ganz normale Push-Benachrichtigung aufs Handy –
inklusive Tasten zum Abhaken.
