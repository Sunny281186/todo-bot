#!/usr/bin/env python3
"""Zoom-Bot: Zoom-Cloud-Aufnahmen -> Transkript + Zusammenfassung mit To-Dos -> Google Drive.

Ablauf: neue Cloud-Aufnahmen bei Zoom abholen -> Zoom-Transkript nehmen (oder, falls es keins gibt,
die Tonspur mit Google Gemini abschreiben) -> Claude schreibt eine ausfuehrliche Zusammenfassung mit
To-Dos -> pro Call ein Unterordner in Google Drive mit zwei Google Docs (Zusammenfassung, Transkript).
Optional: To-Dos zusaetzlich als Trello-Karten, Meldung mit Link per Telegram.
Keine Schluessel im Code: alles kommt aus Umgebungsvariablen (.env lokal, Secrets in GitHub).
"""
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic
import requests

import bot  # Telegram, Trello und Gemini-Modellsuche vom To-Do-Bot mitbenutzen

# --- Einstellungen (aus Umgebungsvariablen) ---------------------------------
ZOOM_ACCOUNT = os.environ.get("ZOOM_ACCOUNT_ID", "")
ZOOM_CLIENT = os.environ.get("ZOOM_CLIENT_ID", "")
ZOOM_SECRET = os.environ.get("ZOOM_CLIENT_SECRET", "")
ZOOM_USER = os.environ.get("ZOOM_USER", "me")  # "me" = Besitzer der Zoom-App
LOOKBACK_DAYS = int(os.environ.get("ZOOM_LOOKBACK_DAYS", "7"))  # so weit zurueck wird nachgeschaut
WAIT_HOURS = float(os.environ.get("TRANSCRIPT_WAIT_HOURS", "3"))  # so lange auf Zooms Transkript warten
MIN_MINUTES = int(os.environ.get("ZOOM_MIN_MINUTES", "2"))  # kuerzere Aufnahmen ueberspringen

G_CLIENT = os.environ.get("GOOGLE_CLIENT_ID", "")
G_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
G_REFRESH = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
DRIVE_FOLDER = os.environ.get("DRIVE_FOLDER_NAME", "Zoom-Calls")

MODEL = os.environ.get("ZOOM_CLAUDE_MODEL", "claude-sonnet-5-5")
TRELLO_LIST = os.environ.get("ZOOM_TRELLO_LIST", "")  # Name der Trello-Liste, leer = keine Karten
TZ = bot.TZ

ZOOM = "https://api.zoom.us/v2"
DRIVE = "https://www.googleapis.com/drive/v3"
GEMINI = "https://generativelanguage.googleapis.com"
FOLDER_MIME = "application/vnd.google-apps.folder"


# --- Zoom --------------------------------------------------------------------
def zoom_token():
    r = requests.post("https://zoom.us/oauth/token",
                      params={"grant_type": "account_credentials", "account_id": ZOOM_ACCOUNT},
                      auth=(ZOOM_CLIENT, ZOOM_SECRET), timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def zoom_recordings(token):
    """Alle Cloud-Aufnahmen der letzten LOOKBACK_DAYS Tage, aelteste zuerst."""
    today = datetime.now(timezone.utc).date()
    meetings, start = [], today - timedelta(days=LOOKBACK_DAYS)
    while start <= today:  # Zoom erlaubt hoechstens 30 Tage pro Abfrage
        end = min(start + timedelta(days=29), today)
        params = {"from": start.isoformat(), "to": end.isoformat(), "page_size": 300}
        while True:
            r = requests.get(f"{ZOOM}/users/{ZOOM_USER}/recordings", params=params,
                             headers={"Authorization": f"Bearer {token}"}, timeout=30)
            r.raise_for_status()
            data = r.json()
            meetings += data.get("meetings", [])
            if not data.get("next_page_token"):
                break
            params["next_page_token"] = data["next_page_token"]
        start = end + timedelta(days=1)
    return sorted(meetings, key=lambda m: m["start_time"])


def zoom_download(url, token):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=600)
    r.raise_for_status()
    return r.content


def parse_vtt(vtt):
    """Zoom-VTT -> [(Sekunde, Sprecher, Text)], aufeinanderfolgende Saetze derselben Person zusammengefasst."""
    rows = []
    for block in re.split(r"\n\s*\n", vtt.replace("\r", "")):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        times = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if times is None:
            continue
        h, m, s = lines[times].split("-->")[0].strip().split(":")
        sec = int(h) * 3600 + int(m) * 60 + float(s)
        text = " ".join(lines[times + 1:]).strip()
        speaker, _, said = text.partition(": ")
        if not said or len(speaker) > 60:
            speaker, said = "", text
        if rows and rows[-1][1] == speaker:
            rows[-1] = (rows[-1][0], speaker, rows[-1][2] + " " + said)
        else:
            rows.append((sec, speaker, said))
    return rows


def clock(sec):
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec // 60 % 60:02d}:{sec % 60:02d}"


# --- Gemini (nur wenn Zoom kein Transkript liefert) -----------------------------
def gemini_transcribe(audio, mime, title):
    """Laedt die Tonspur ueber die Gemini-Files-API hoch (Calls sind fuer Inline-Daten zu gross)."""
    key = {"x-goog-api-key": bot.GEMINI_KEY}
    start = requests.post(f"{GEMINI}/upload/v1beta/files", json={"file": {"display_name": title[:100]}}, timeout=60,
                          headers={**key, "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                                   "X-Goog-Upload-Header-Content-Length": str(len(audio)),
                                   "X-Goog-Upload-Header-Content-Type": mime})
    start.raise_for_status()
    up = requests.post(start.headers["x-goog-upload-url"], data=audio, timeout=900,
                       headers={"X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"})
    up.raise_for_status()
    f = up.json()["file"]
    for _ in range(60):  # warten, bis Google die Datei verarbeitet hat
        if f.get("state") == "ACTIVE":
            break
        time.sleep(5)
        f = requests.get(f"{GEMINI}/v1beta/{f['name']}", headers=key, timeout=30).json()
    prompt = ("Schreibe dieses Gespraech vollstaendig und wortgetreu auf, in der gesprochenen Sprache. "
              "Ein Absatz pro Sprecherwechsel, jede Zeile im Format '[HH:MM:SS] Name: Text'. "
              "Nenne Personen beim Namen, wenn er im Gespraech faellt, sonst 'Sprecher 1', 'Sprecher 2' usw. "
              "Gib nur das Transkript aus.")
    body = {"contents": [{"parts": [{"text": prompt}, {"file_data": {"mime_type": mime, "file_uri": f["uri"]}}]}],
            "generationConfig": {"maxOutputTokens": 65536}}
    last = None
    try:
        for model in bot.gemini_candidates()[:4]:
            try:
                r = requests.post(f"{GEMINI}/v1beta/models/{model}:generateContent", headers=key, json=body, timeout=900)
                r.raise_for_status()
                text = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"]).strip()
                print("Gemini-Modell:", model, flush=True)
                break
            except Exception as e:
                print(f"Gemini {model} ging nicht: {e!r}", flush=True)
                last = e
        else:
            raise last
    finally:
        requests.delete(f"{GEMINI}/v1beta/{f['name']}", headers=key, timeout=30)
    rows = []
    for line in text.splitlines():
        m = re.match(r"\[?(\d+):(\d\d)(?::(\d\d))?\]?\s*([^:]{1,60}):\s*(.+)", line.strip())
        if m:
            a, b, c = int(m.group(1)), int(m.group(2)), m.group(3)
            sec = a * 3600 + b * 60 + int(c) if c else a * 60 + b
            rows.append((sec, m.group(4).strip(), m.group(5).strip()))
        elif line.strip() and rows:
            rows[-1] = (rows[-1][0], rows[-1][1], rows[-1][2] + " " + line.strip())
        elif line.strip():
            rows.append((0, "", line.strip()))
    return rows


# --- Claude ------------------------------------------------------------------
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Kurzer, sprechender Titel fuer den Call"},
        "participants": {"type": "array", "items": {"type": "string"}},
        "overview": {"type": "string", "description": "3-6 Saetze: Worum ging es, was ist herausgekommen"},
        "topics": {"type": "array", "items": {
            "type": "object",
            "properties": {"heading": {"type": "string"},
                           "points": {"type": "array", "items": {"type": "string"}}},
            "required": ["heading", "points"], "additionalProperties": False}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "todos": {"type": "array", "items": {
            "type": "object",
            "properties": {"task": {"type": "string"},
                           "owner": {"type": ["string", "null"]},
                           "due": {"type": ["string", "null"], "description": "YYYY-MM-DD, nur wenn genannt"},
                           "context": {"type": "string"}},
            "required": ["task", "owner", "due", "context"], "additionalProperties": False}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "participants", "overview", "topics", "decisions", "todos", "open_questions"],
    "additionalProperties": False,
}


def summarize(topic, started, transcript):
    system = (
        "Du fasst aufgezeichnete Zoom-Calls fuer Sunny zusammen. Schreibe auf Deutsch, sachlich und ausfuehrlich: "
        "Wer den Call nicht gehoert hat, soll danach alles Wichtige wissen - Zahlen, Namen, Begruendungen, "
        "Einwaende und Beispiele gehoeren dazu.\n"
        "- topics: die Themen in der Reihenfolge des Gespraechs, je Thema alle wesentlichen Punkte.\n"
        "- todos: jede Aufgabe, die jemand uebernimmt oder die vereinbart wird, als konkrete Handlung mit Verb. "
        "owner nur, wenn klar ist, wer sie macht. due nur, wenn ein Termin faellt; relative Angaben wie "
        "'naechsten Freitag' ab dem Datum des Calls ausrechnen. context: ein Satz, warum die Aufgabe ansteht.\n"
        "- Erfinde nichts, was nicht im Transkript steht. Ein leeres Feld ist besser als ein geratenes."
    )
    user = f"Call: {topic}\nDatum: {started:%A, %d.%m.%Y, %H:%M} Uhr\n\nTranskript:\n{transcript}"
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},  # lehnt das Modell ab, springt ein anderes ein
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude hat die Zusammenfassung abgelehnt")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Zusammenfassung wurde abgeschnitten (max_tokens)")
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


# --- Google Drive ------------------------------------------------------------
def google_token():
    r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": G_CLIENT, "client_secret": G_SECRET,
        "refresh_token": G_REFRESH, "grant_type": "refresh_token"})
    r.raise_for_status()
    return r.json()["access_token"]


def q(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def drive_find(token, query):
    r = requests.get(f"{DRIVE}/files", headers={"Authorization": f"Bearer {token}"}, timeout=30,
                     params={"q": query + " and trashed = false", "fields": "files(id,name,appProperties,webViewLink)"})
    r.raise_for_status()
    return r.json()["files"]


def drive_folder(token, name, parent=None, props=None):
    meta = {"name": name, "mimeType": FOLDER_MIME, "appProperties": props or {}}
    if parent:
        meta["parents"] = [parent]
    r = requests.post(f"{DRIVE}/files", headers={"Authorization": f"Bearer {token}"}, json=meta,
                      params={"fields": "id,webViewLink"}, timeout=30)
    r.raise_for_status()
    return r.json()


def root_folder(token):
    """Hauptordner; wird beim ersten Lauf angelegt und danach an seiner Markierung erkannt
    (darf also in Drive umbenannt oder verschoben werden)."""
    found = drive_find(token, f"mimeType = '{FOLDER_MIME}' and appProperties has {{ key='zoomBot' and value='root' }}")
    return found[0]["id"] if found else drive_folder(token, DRIVE_FOLDER, props={"zoomBot": "root"})["id"]


def drive_doc(token, name, parent, body_html):
    """Laedt HTML hoch und laesst Drive daraus ein Google Doc machen."""
    meta = {"name": name, "parents": [parent], "mimeType": "application/vnd.google-apps.document"}
    boundary = "zoombot"
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: text/html; charset=UTF-8\r\n\r\n{body_html}\r\n--{boundary}--").encode()
    r = requests.post("https://www.googleapis.com/upload/drive/v3/files", data=body, timeout=120,
                      params={"uploadType": "multipart", "fields": "id,webViewLink"},
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": f"multipart/related; boundary={boundary}"})
    r.raise_for_status()
    return r.json()


def drive_mark_done(token, file_id):
    r = requests.patch(f"{DRIVE}/files/{file_id}", headers={"Authorization": f"Bearer {token}"},
                       json={"appProperties": {"done": "1"}}, timeout=30)
    r.raise_for_status()


def drive_trash(token, file_id):
    requests.patch(f"{DRIVE}/files/{file_id}", headers={"Authorization": f"Bearer {token}"},
                   json={"trashed": True}, timeout=30).raise_for_status()


# --- Dokumente ---------------------------------------------------------------
def e(text):
    return html.escape(text or "")


def summary_html(s, topic, started, minutes, transcript_link):
    out = [f"<h1>{e(topic)}</h1>", f"<p><i>{e(s['title'])}</i></p>",
           f"<p><b>Datum:</b> {started:%d.%m.%Y, %H:%M} Uhr · {minutes} Min.<br>"
           f"<b>Teilnehmer:</b> {e(', '.join(s['participants'])) or '–'}<br>"
           f"<a href=\"{e(transcript_link)}\">Zum vollständigen Transkript</a></p>",
           "<h2>Überblick</h2>", f"<p>{e(s['overview'])}</p>",
           "<h2>To-Dos</h2>"]
    if s["todos"]:
        out.append("<table border=\"1\" cellpadding=\"4\"><tr><th>Aufgabe</th><th>Wer</th><th>Bis</th><th>Hintergrund</th></tr>")
        for t in s["todos"]:
            due = datetime.fromisoformat(t["due"]).strftime("%d.%m.%Y") if t.get("due") else ""
            out.append(f"<tr><td>☐ {e(t['task'])}</td><td>{e(t.get('owner'))}</td><td>{due}</td><td>{e(t['context'])}</td></tr>")
        out.append("</table>")
    else:
        out.append("<p>Keine To-Dos besprochen.</p>")
    if s["decisions"]:
        out += ["<h2>Entscheidungen</h2>", "<ul>"] + [f"<li>{e(d)}</li>" for d in s["decisions"]] + ["</ul>"]
    out.append("<h2>Besprochene Themen</h2>")
    for t in s["topics"]:
        out += [f"<h3>{e(t['heading'])}</h3>", "<ul>"] + [f"<li>{e(p)}</li>" for p in t["points"]] + ["</ul>"]
    if s["open_questions"]:
        out += ["<h2>Offene Fragen</h2>", "<ul>"] + [f"<li>{e(x)}</li>" for x in s["open_questions"]] + ["</ul>"]
    return "<html><head><meta charset=\"utf-8\"></head><body>" + "".join(out) + "</body></html>"


def transcript_html(rows, topic, started, source):
    out = [f"<h1>Transkript: {e(topic)}</h1>", f"<p>{started:%d.%m.%Y, %H:%M} Uhr · Quelle: {e(source)}</p>"]
    for sec, speaker, text in rows:
        who = f"<b>{e(speaker)}</b> " if speaker else ""
        out.append(f"<p><span style=\"color:#888\">[{clock(sec)}]</span> {who}{e(text)}</p>")
    return "<html><head><meta charset=\"utf-8\"></head><body>" + "".join(out) + "</body></html>"


def transcript_text(rows):
    return "\n".join(f"[{clock(sec)}] {speaker + ': ' if speaker else ''}{text}" for sec, speaker, text in rows)


# --- Ablauf ------------------------------------------------------------------
def process(meeting, ztoken, gtoken, root):
    """Gibt True zurueck, wenn der Call abgelegt wurde, False, wenn er (noch) nicht dran ist."""
    uuid, topic = meeting["uuid"], meeting.get("topic") or "Zoom-Call"
    if meeting.get("duration", 0) < MIN_MINUTES:
        return False
    existing = drive_find(token=gtoken, query=f"appProperties has {{ key='zoomUuid' and value='{q(uuid)}' }}")
    if any(f.get("appProperties", {}).get("done") == "1" for f in existing):
        return False
    files = [f for f in meeting.get("recording_files", []) if f.get("status") == "completed"]
    started = datetime.fromisoformat(meeting["start_time"].replace("Z", "+00:00")).astimezone(TZ)
    vtt = next((f for f in files if f.get("file_type") == "TRANSCRIPT"), None)
    if vtt:
        rows, source = parse_vtt(zoom_download(vtt["download_url"], ztoken).decode("utf-8", "replace")), "Zoom-Transkript"
    else:
        ended = max((f.get("recording_end") or meeting["start_time"] for f in files), default=meeting["start_time"])
        ended = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - ended < timedelta(hours=WAIT_HOURS):
            print(f"Warte noch auf Zoom-Transkript: {topic}", flush=True)
            return False
        audio = next((f for f in files if f.get("file_type") == "M4A"), None) or \
            next((f for f in files if f.get("file_type") == "MP4"), None)
        if not audio:
            return False
        mime = "audio/mp4" if audio["file_type"] == "M4A" else "video/mp4"
        rows, source = gemini_transcribe(zoom_download(audio["download_url"], ztoken), mime, topic), "Gemini (aus der Tonspur)"
    if not rows:
        print(f"Leeres Transkript: {topic}", flush=True)
        return False

    print(f"Fasse zusammen: {topic} ({started:%d.%m.%Y %H:%M})", flush=True)
    s = summarize(topic, started, transcript_text(rows))
    for t in s["todos"]:  # nur saubere Daten weitergeben
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", t.get("due") or ""):
            t["due"] = None
    for f in existing:  # halb fertiger Ordner vom letzten Versuch
        drive_trash(gtoken, f["id"])
    call = re.sub(r"[\\/]", "-", topic)  # Name des Zoom-Termins
    name = f"{call} – {started:%d.%m.%Y}"
    folder = drive_folder(gtoken, name, parent=root, props={"zoomUuid": uuid})
    tdoc = drive_doc(gtoken, f"{call} – Transkript – {started:%d.%m.%Y}", folder["id"],
                     transcript_html(rows, topic, started, source))
    sdoc = drive_doc(gtoken, f"{call} – To-Dos – {started:%d.%m.%Y}", folder["id"],
                     summary_html(s, topic, started, meeting.get("duration", 0), tdoc["webViewLink"]))
    drive_mark_done(gtoken, folder["id"])

    if TRELLO_LIST and bot.TRELLO_KEY and s["todos"]:
        lst = bot.find_list(TRELLO_LIST, bot.trello_lists())
        for t in s["todos"] if lst else []:
            desc = f"{t['context']}\n\nAus dem Call: {name}\n{sdoc['webViewLink']}"
            bot.create_card({"title": t["task"], "desc": desc, "due": t["due"] and t["due"] + "T09:00"}, lst)
    if bot.TG_TOKEN and bot.TG_CHAT:
        todos = "\n".join("☐ " + t["task"] for t in s["todos"][:15]) or "Keine To-Dos."
        bot.tg_send(bot.TG_CHAT, f"📞 {topic}\n{started:%d.%m. %H:%M}\n\n{todos}\n\n"
                                 f"📄 Zusammenfassung: {sdoc['webViewLink']}\n📝 Transkript: {tdoc['webViewLink']}")
    print(f"Abgelegt: {name}", flush=True)
    return True


def main():
    missing = [k for k, v in {"ZOOM_ACCOUNT_ID": ZOOM_ACCOUNT, "ZOOM_CLIENT_ID": ZOOM_CLIENT,
                              "ZOOM_CLIENT_SECRET": ZOOM_SECRET, "GOOGLE_CLIENT_ID": G_CLIENT,
                              "GOOGLE_CLIENT_SECRET": G_SECRET, "GOOGLE_REFRESH_TOKEN": G_REFRESH,
                              "ANTHROPIC_API_KEY": bot.ANTHROPIC_KEY}.items() if not v]
    if missing:
        sys.exit("Fehlt: " + ", ".join(missing))
    ztoken, gtoken = zoom_token(), google_token()
    root = root_folder(gtoken)
    failed = 0
    for meeting in zoom_recordings(ztoken):
        try:
            process(meeting, ztoken, gtoken, root)
        except Exception as ex:
            failed += 1
            print(f"Fehler bei {meeting.get('topic')!r}: {ex!r}", flush=True)
    if failed:
        sys.exit(f"{failed} Call(s) gingen nicht, nächster Versuch beim nächsten Lauf.")


if __name__ == "__main__":
    main()
