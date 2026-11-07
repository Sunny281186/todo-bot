"""Facebook-Antwort-Assistent: Screenshots rein, PN- und Kommentar-Entwurf raus.

Läuft nur lokal (127.0.0.1). Der API-Schlüssel kommt aus der Umgebungsvariable
ANTHROPIC_API_KEY und steht nie im Code. Es wird nichts in Facebook gelesen oder gesendet.
"""
import base64
import json
import os
from pathlib import Path

import anthropic
from flask import Flask, jsonify, request, send_from_directory

BASE = Path(__file__).parent
WISSEN = BASE / "wissen"
MODEL = os.environ.get("FB_MODEL", "claude-sonnet-5-5")
MAX_BILDER = 12
ERLAUBT = {"image/jpeg", "image/png", "image/webp", "image/gif"}

THEMEN = ["bankkonto", "compliance_adresse", "firmengruendung", "residency", "llc", "immobilien", "sonstiges"]

TOOL = {
    "name": "ergebnis",
    "description": "Liefert die Auswertung aller relevanten Posts auf den Screenshots.",
    "input_schema": {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "description": "Ein Eintrag pro erkanntem Post mit einer Person, die etwas fragt oder schreibt.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name der Person wie im Screenshot, sonst 'unbekannt'."},
                        "post_kurz": {"type": "string", "description": "Worum es im Post geht, ein Satz."},
                        "thema": {"type": "string", "enum": THEMEN},
                        "sucht_hilfe": {"type": "boolean", "description": "True nur, wenn die Person erkennbar Hilfe oder Rat sucht und das Angebot wirklich passt."},
                        "einschaetzung": {"type": "string", "description": "Kurze Begründung, warum ein Entwurf entsteht oder warum nicht."},
                        "pn": {"type": "string", "description": "Entwurf der Direktnachricht. Platzhalter {LINK} für den Link. Leer, wenn sucht_hilfe false."},
                        "kommentar": {"type": "string", "description": "Entwurf des öffentlichen Kommentars. Leer, wenn sucht_hilfe false."},
                        "link_key": {"type": "string", "description": "Schlüssel aus der Link-Liste, z. B. bankkonto."},
                    },
                    "required": ["name", "post_kurz", "thema", "sucht_hilfe", "einschaetzung", "pn", "kommentar", "link_key"],
                },
            }
        },
        "required": ["posts"],
    },
}


def lade_wissen():
    teile = []
    for datei in ("angebot.md", "erfahrung.md", "regeln.md"):
        teile.append((WISSEN / datei).read_text(encoding="utf-8"))
    links = json.loads((WISSEN / "links.json").read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(teile), links


def baue_system_prompt(wissen, links):
    return (
        "Du hilfst Sunny dabei, in Auswanderer-Gruppen auf Facebook persönlich und hilfreich auf Posts zu antworten. "
        "Sunny schreibt aus eigener Erfahrung mit Georgien. Du bekommst Screenshots von Posts und erstellst Entwürfe. "
        "Sunny liest, ändert und sendet alles selbst.\n\n"
        "Halte dich strikt an das Wissen unten. Erfinde keine Erfahrungen, Preise oder Versprechen. "
        "Schreibe auf Deutsch, per Du, natürlich und kurz, wie ein Mensch, nicht wie Werbung.\n"
        "Pro Person mit relevantem Post ein Eintrag. Wenn die Person keine Hilfe sucht oder das Angebot nicht passt, "
        "setze sucht_hilfe auf false und lasse pn, kommentar und link_key leer bzw. 'bankkonto' als Platzhalter.\n"
        "In der PN steht der Platzhalter {LINK} genau einmal an passender Stelle. "
        "Der Kommentar markiert die Person mit @Name, enthält keinen Link und bittet, Nachrichtenanfragen und Spam-Ordner zu prüfen.\n"
        "Rufe am Ende das Tool 'ergebnis' auf.\n\n"
        f"Verfügbare link_key-Werte: {', '.join(k for k, v in links.items() if k != 'hinweis' and v)}\n\n"
        "=== WISSEN ===\n\n" + wissen
    )


def analysiere(bilder, notiz, client=None):
    """bilder: Liste von (media_type, bytes). Gibt Liste von Post-Dicts zurück."""
    wissen, links = lade_wissen()
    client = client or anthropic.Anthropic()
    inhalt = []
    for media_type, daten in bilder:
        inhalt.append({"type": "image", "source": {"type": "base64", "media_type": media_type,
                                                    "data": base64.b64encode(daten).decode()}})
    text = "Bitte werte die Screenshots aus."
    if notiz.strip():
        text += f"\n\nNotiz von Sunny (hat Vorrang): {notiz.strip()}"
    inhalt.append({"type": "text", "text": text})

    antwort = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=baue_system_prompt(wissen, links),
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "ergebnis"},
        messages=[{"role": "user", "content": inhalt}],
    )
    posts = []
    for block in antwort.content:
        if block.type == "tool_use" and block.name == "ergebnis":
            posts = block.input.get("posts", [])
    for p in posts:
        url = links.get(p.get("link_key", ""), "") or ""
        p["pn"] = (p.get("pn") or "").replace("{LINK}", url)
    return posts


app = Flask(__name__, static_folder=str(BASE / "static"))
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/analyze")
def analyze():
    dateien = request.files.getlist("bilder")
    if not dateien:
        return jsonify(fehler="Bitte mindestens einen Screenshot hochladen."), 400
    if len(dateien) > MAX_BILDER:
        return jsonify(fehler=f"Maximal {MAX_BILDER} Screenshots auf einmal."), 400
    bilder = []
    for f in dateien:
        if f.mimetype not in ERLAUBT:
            return jsonify(fehler=f"Dateityp nicht unterstützt: {f.mimetype}"), 400
        bilder.append((f.mimetype, f.read()))
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify(fehler="ANTHROPIC_API_KEY ist nicht gesetzt."), 500
    try:
        posts = analysiere(bilder, request.form.get("notiz", ""))
    except anthropic.APIError as e:
        return jsonify(fehler=f"Fehler bei der KI-Anfrage: {e.__class__.__name__}"), 502
    return jsonify(posts=posts)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False)
