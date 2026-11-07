# Facebook-Antwort-Assistent

Hilft dabei, auf passende Posts in Auswanderer-Gruppen persönlich und hilfreich zu antworten.

**So läuft es:**
1. Du schickst Screenshots (und optional eine kurze Sprachnotiz) von Posts.
2. Der Assistent prüft, ob die Person wirklich Hilfe sucht.
3. Er schreibt zwei Entwürfe: eine **PN** und einen **kurzen öffentlichen Kommentar** mit Markierung.
4. Du liest, änderst, gibst frei und sendest **selbst**.
5. Die Person kommt in eine Namensliste, damit niemand doppelt angeschrieben wird.

**Wichtig:**
- Es wird nichts automatisch in Facebook gelesen, kommentiert oder gesendet.
- Es gibt kein Tageslimit.
- Nichts wird ohne deine Freigabe verwendet.

## Starten (am Laptop)
1. Python 3 installieren, falls noch nicht vorhanden.
2. Im Ordner `fb-assistent/` ein Terminal öffnen und einmalig die Pakete installieren:
   `pip install -r requirements.txt`
3. API-Schlüssel nur für dieses Terminal setzen (nicht in eine Datei schreiben):
   - Mac/Linux: `export ANTHROPIC_API_KEY="dein-schluessel"`
   - Windows (PowerShell): `$env:ANTHROPIC_API_KEY="dein-schluessel"`
4. Starten: `python app.py`
5. Im Browser öffnen: http://127.0.0.1:5055

Die App ist nur auf deinem Rechner erreichbar. Das Modell lässt sich mit `FB_MODEL` ändern.

## Ordner
- `wissen/angebot.md` – Leistungen von Georgien Navigator
- `wissen/erfahrung.md` – deine eigene Erfahrung (Grundlage für die Texte)
- `wissen/regeln.md` – Ton, Aufbau und Leitplanken der Texte
- `app.py` – kleiner lokaler Server (Flask), ruft die KI auf
- `static/index.html` – Oberfläche (Screenshots, Notiz, Sprache, Kopieren)
- `wissen/links.json` – Links je Thema (Ref-Links trägst du später ein)

## Stand
- [x] Schritt 1–2: Ordner und Wissensdateien
- [x] Schritt 3: Web-App mit Screenshot-Analyse und den zwei Entwürfen (inkl. Sprachnotiz per Browser)
- [ ] Schritt 4: Textbausteine zum Auswählen, Namensliste
- [ ] Schritt 5: Nachverfolgung und Warnung vor doppelter Ansprache
