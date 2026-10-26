#!/usr/bin/env python3
"""To-Do-Bot: Telegram (Text oder Sprachnachricht) -> eigene To-Do-App + Erinnerungen.

Ablauf: Nachricht kommt an -> bei Sprache wird sie in Text umgewandelt (Google Gemini)
-> Claude sortiert in To-Dos + passende Kategorie + Datum -> To-Dos landen in der App.
Die App (Ordner docs/) und der Bot teilen sich eine geheime GitHub-Gist-Datei (todos.json).
Faellige Erinnerungen schickt der Bot als Telegram-Nachricht mit Tasten (Erledigt / Spaeter).
Keine Schluessel im Code: alles kommt aus Umgebungsvariablen (.env lokal, Variablen in der Cloud).
"""
import base64
import json
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

# --- Einstellungen (aus Umgebungsvariablen) ---------------------------------
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
GIST_TOKEN = os.environ.get("GIST_TOKEN", "")
GIST_ID = os.environ.get("TODO_GIST_ID", "").strip()
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")  # bevorzugtes Modell, sonst automatisch das neueste Flash-Modell
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Vienna"))  # Ersatz, bis die App ihre Zeitzone gemeldet hat

TG = f"https://api.telegram.org/bot{TG_TOKEN}"
GH = "https://api.github.com"
FILE = "todos.json"  # schreibt nur die App
BOT_FILE = "todos-bot.json"  # schreibt nur der Bot - so ueberschreibt keiner die Aenderungen des anderen
STATE_FILE = "bot.json"  # merkt sich z. B., ob der Abend-Check heute schon raus ist (die App fasst ihn nicht an)
EVENING = int(os.environ.get("EVENING_HOUR", "19"))  # Abend-Erinnerung um 19 Uhr (Ortszeit)

# Gleiche Kategorien wie in der App (docs/app.js)
CATEGORIES = [
    {"id": "sunny", "name": "Sunny", "emoji": "🎀", "area": "Privat"},
    {"id": "franny", "name": "Franny", "emoji": "🩷", "area": "Privat"},
    {"id": "slb", "name": "School-Life-Balance", "emoji": "🎓", "area": "Business"},
    {"id": "miller", "name": "Michelle Miller", "emoji": "🏚️", "area": "Business"},
    {"id": "wagner", "name": "Markus Wagner", "emoji": "🏡", "area": "Business"},
    {"id": "falk", "name": "Stefan Falk", "emoji": "🌐", "area": "Business"},
]
CAT = {c["id"]: c for c in CATEGORIES}


def cat_label(cat_id):
    c = CAT.get(cat_id)
    return f"{c['emoji']} {c['name']}" if c else "📥 Eingang"


# --- Telegram ----------------------------------------------------------------
def tg_send(chat_id, text, buttons=None):
    body = {"chat_id": chat_id, "text": text}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": buttons}
    res = requests.post(f"{TG}/sendMessage", json=body, timeout=30).json()
    if not res.get("ok"):
        print("Telegram hat die Antwort abgelehnt:", res.get("description"), flush=True)
    return res


def tg_edit(chat_id, message_id, text):
    requests.post(f"{TG}/editMessageText",
                  json={"chat_id": chat_id, "message_id": message_id, "text": text}, timeout=30)


# --- Speicher (geheime Gist) ---------------------------------------------------
def read_file(files, name):
    f = files.get(name)
    if not f:
        return {}
    content = f["content"] if not f.get("truncated") else requests.get(f["raw_url"], timeout=30).text
    return json.loads(content or "{}")


def merge(*lists):
    """Pro To-Do gewinnt die neuere Aenderung; Geloeschtes bleibt 30 Tage als Markierung."""
    newest = {}
    for todos in lists:
        for t in todos:
            if t["id"] not in newest or t.get("updated", 0) > newest[t["id"]].get("updated", 0):
                newest[t["id"]] = t
    month = now_ms() - 30 * 86400000
    return [t for t in newest.values() if not (t.get("deleted") and t.get("updated", 0) < month)]


def load(name=FILE):
    """To-Dos = Datei der App + Datei des Bots zusammengefuehrt. Andere Dateien (z. B. bot.json) einzeln."""
    r = requests.get(f"{GH}/gists/{GIST_ID}", headers=gh_headers(), timeout=30)
    r.raise_for_status()
    files = r.json()["files"]
    if name != FILE:
        return read_file(files, name)
    app, mine = read_file(files, FILE), read_file(files, BOT_FILE)
    return {"version": 1, "tz": app.get("tz"), "todos": merge(app.get("todos", []), mine.get("todos", []))}


def use_tz(data):
    """Die App traegt ein, in welcher Zeitzone Sunny gerade ist (z. B. auf Reisen) - die gilt dann auch hier."""
    global TZ
    try:
        TZ = ZoneInfo(data.get("tz") or TZ.key)
    except Exception:
        pass
    return data


def save(data, name=FILE):
    if name == FILE:
        name = BOT_FILE  # die Datei der App fasst der Bot nie an
    r = requests.patch(f"{GH}/gists/{GIST_ID}", headers=gh_headers(), timeout=30,
                       json={"files": {name: {"content": json.dumps(data, ensure_ascii=False, indent=1)}}})
    r.raise_for_status()


def gh_headers():
    return {"Authorization": f"Bearer {GIST_TOKEN}", "Accept": "application/vnd.github+json"}


def now_ms():
    return int(time.time() * 1000)


def utc_iso(dt):
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def due_local(due):
    """'YYYY-MM-DD' (ganztags = 09:00) oder 'YYYY-MM-DDTHH:MM' -> datetime in TZ."""
    if len(due) == 10:
        due += "T09:00"
    return datetime.fromisoformat(due).replace(tzinfo=TZ)


def fmt_due(due):
    if not due:
        return ""
    d = due_local(due)
    return f"{d:%d.%m.}" if len(due) == 10 else f"{d:%d.%m. %H:%M}"


def remind_at_of(due, remind):
    """remind = Minuten vor dem Termin oder 'abend' (= am Vorabend um 19 Uhr)."""
    if not due or remind is None:
        return None
    if remind == "abend":
        eve = due_local(due) - timedelta(days=1)
        return utc_iso(eve.replace(hour=EVENING, minute=0, second=0, microsecond=0))
    return utc_iso(due_local(due) - timedelta(minutes=int(remind)))


def new_todo(title, cat, due=None, remind=None, notes=""):
    remind_at = remind_at_of(due, remind)
    return {
        "id": secrets.token_hex(5), "title": title, "cat": cat, "notes": notes,
        "due": due, "remind": remind if due else None, "remindAt": remind_at, "reminded": False,
        "status": "new", "done": False, "created": now_ms(), "updated": now_ms(),
    }


# --- Sprache -> Text (Gemini) --------------------------------------------------
def gemini_candidates():
    """Stabile Gemini-Flash-Modelle, neueste zuerst (Modellnamen aendern sich bei Google oefter)."""
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     headers={"x-goog-api-key": GEMINI_KEY}, params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    skip = ("lite", "image", "tts", "live", "preview", "exp", "thinking", "robotics", "computer", "embedding")
    found = []
    for m in r.json().get("models", []):
        n = m["name"].split("/")[-1]
        if (n.startswith("gemini-") and "flash" in n and "generateContent" in m.get("supportedGenerationMethods", [])
                and not any(x in n for x in skip)):
            v = re.match(r"gemini-(\d+(?:\.\d+)?)", n)
            found.append((float(v.group(1)) if v else 0, n))
    if not found:
        raise RuntimeError("Kein passendes Gemini-Modell gefunden")
    names = [n for _, n in sorted(found, reverse=True)]
    if GEMINI_MODEL:  # bevorzugtes Modell zuerst, die anderen als Ersatz
        names = [GEMINI_MODEL] + [n for n in names if n != GEMINI_MODEL]
    return names


_gemini_ok = None  # Modell, das schon funktioniert hat


def transcribe(file_id):
    global _gemini_ok
    info = requests.get(f"{TG}/getFile", params={"file_id": file_id}, timeout=30).json()
    path = info["result"]["file_path"]
    audio = requests.get(f"https://api.telegram.org/file/bot{TG_TOKEN}/{path}", timeout=60).content
    body = {"contents": [{"parts": [
        {"text": "Schreibe diese deutsche Sprachnachricht wortgetreu auf. Gib nur den Text aus."},
        {"inline_data": {"mime_type": "audio/ogg", "data": base64.b64encode(audio).decode()}},
    ]}]}
    last = None
    for model in ([_gemini_ok] if _gemini_ok else gemini_candidates()[:4]):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY}, json=body, timeout=40,
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            _gemini_ok = model
            print("Gemini-Modell:", model, flush=True)
            return text
        except Exception as e:
            print(f"Gemini {model} ging nicht: {e!r}", flush=True)
            last = e
    raise last


# --- Text -> To-Dos (Claude) ---------------------------------------------------
def sort_todos(text):
    now = datetime.now(TZ)
    cats = "\n".join(f"  {c['id']} = {c['emoji']} {c['name']} ({c['area']})" for c in CATEGORIES)
    system = (
        "Du sortierst gesprochene oder getippte To-Dos fuer Sunny in ihre To-Do-App.\n"
        f"Heute ist {now:%A, %d.%m.%Y}, {now:%H:%M} Uhr (Zeitzone {TZ.key}).\n"
        "Kategorien (id = Bedeutung):\n" + cats + "\n"
        "Regeln:\n"
        "- Mehrere To-Dos in einer Nachricht = mehrere To-Dos.\n"
        "- title kurz und konkret, mit Verb am Anfang, Sprache wie Sunny sie sagt (Deutsch).\n"
        "- cat: die id der Kategorie, die Sunny nennt oder die eindeutig passt "
        "(z. B. 'Schule', 'SLB' = slb; 'Michelle' = miller; 'Markus' = wagner; 'Stefan' = falk; 'Franny' = franny; "
        "'privat', 'fuer mich' = sunny). Ist es unklar, setze cat auf null.\n"
        "- due: nur wenn ein Termin genannt wird, als ISO-Zeit lokal (YYYY-MM-DDTHH:MM). Ohne Uhrzeit 09:00. "
        "'morgen', 'Freitag' usw. ab heute ausrechnen. Sonst null.\n"
        "- remind: Minuten VOR dem Termin, zu denen erinnert werden soll (z. B. 'eine Stunde vorher' = 60, "
        "'am Vortag' = 1440), oder \"abend\" fuer 'am Vorabend' / 'abends vorher' (= Vortag 19 Uhr). "
        "Bei Termin ohne Angabe 0 (= zum Termin). Ohne Termin null.\n"
        "- notes: nur Zusatzdetails, die nicht in den Titel passen, sonst leer.\n"
        "- Erfinde nichts."
    )
    tool = {
        "name": "todos_anlegen",
        "description": "Legt die erkannten To-Dos in der App an.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "cat": {"type": ["string", "null"], "enum": [c["id"] for c in CATEGORIES] + [None]},
                            "due": {"type": ["string", "null"]},
                            "remind": {"type": ["integer", "string", "null"]},
                            "notes": {"type": "string"},
                        },
                        "required": ["title", "cat", "due", "remind"],
                    },
                }
            },
            "required": ["todos"],
        },
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"},
        json={
            "model": MODEL,
            "max_tokens": 1000,
            "system": system,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "todos_anlegen"},
            "messages": [{"role": "user", "content": text}],
        },
        timeout=60,
    )
    r.raise_for_status()
    for block in r.json()["content"]:
        if block["type"] == "tool_use":
            return block["input"]["todos"]
    return []


def cat_buttons():
    rows = [[{"text": f"{c['emoji']} {c['name']}", "callback_data": "C:" + c["id"]}] for c in CATEGORIES]
    return rows


def open_list(data):
    todos = [t for t in data["todos"] if not t.get("done") and not t.get("deleted")]
    if not todos:
        return "🎉 Nichts offen!"
    out = []
    for cat_id in [c["id"] for c in CATEGORIES] + [None]:
        mine = sorted((t for t in todos if t.get("cat") == cat_id), key=lambda t: t.get("due") or "9999")
        if mine:
            out.append(cat_label(cat_id))
            out += [f"  • {t['title']}" + (f" ⏰ {fmt_due(t['due'])}" if t.get("due") else "") for t in mine]
    return "\n".join(out)


def handle(msg):
    chat_id = str(msg["chat"]["id"])
    if not TG_CHAT:
        tg_send(chat_id, f"Hallo! Deine Chat-ID ist {chat_id}. Trage sie als TELEGRAM_CHAT_ID ein, dann bin ich nur für dich da.")
        return
    if chat_id != TG_CHAT:
        return  # Fremde werden ignoriert

    text = (msg.get("text") or "").strip()
    print("Nachricht erhalten:", "Sprache" if (msg.get("voice") or msg.get("audio")) else "Text", flush=True)
    if text.startswith("/start") or text.startswith("/hilfe"):
        tg_send(chat_id, "Schick mir deine To-Dos als Text oder Sprachnachricht und sag dazu, wohin sie sollen "
                         "(z. B. 'Angebot für Markus schreiben, bis Freitag 14 Uhr, eine Stunde vorher erinnern'). "
                         "/offen zeigt alles, was noch offen ist.")
        return
    if text.startswith("/offen") or text.startswith("/listen"):
        tg_send(chat_id, open_list(load()))
        return

    voice = msg.get("voice") or msg.get("audio")
    if voice:
        text = transcribe(voice["file_id"])
        tg_send(chat_id, f"🎤 Verstanden: {text}")
    if not text:
        return

    data = use_tz(load())
    found = sort_todos(text)
    for t in found:  # nur gueltige Erinnerungen uebernehmen
        if t.get("remind") not in (None, "abend") and not isinstance(t.get("remind"), int):
            t["remind"] = 0
    if not found:
        tg_send(chat_id, "Ich habe kein To-Do erkannt. Sag es mir bitte nochmal anders.")
        return
    todos = [new_todo(t["title"], t.get("cat") if t.get("cat") in CAT else None,
                      t.get("due"), t.get("remind"), t.get("notes") or "") for t in found]
    data["todos"] += todos
    lines = []
    for t in todos:
        due = f" (⏰ {fmt_due(t['due'])})" if t.get("due") else ""
        lines.append(f"✅ {t['title']}{due}\n    → {cat_label(t['cat'])}")
    pending = [t for t in todos if not t["cat"]]
    if pending:
        lines.append("\n❓ Wohin gehört das, was im Eingang gelandet ist?")
        sent = tg_send(chat_id, "\n".join(lines), cat_buttons())
        for t in pending:  # damit der Tastendruck spaeter genau diese To-Dos findet
            t["tgmsg"] = sent.get("result", {}).get("message_id")
    else:
        tg_send(chat_id, "\n".join(lines))
    save(data)


def handle_callback(cb):
    msg = cb["message"]
    chat_id = str(msg["chat"]["id"])
    if chat_id != TG_CHAT:
        return
    requests.post(f"{TG}/answerCallbackQuery", json={"callback_query_id": cb["id"]}, timeout=30)
    kind, _, arg = cb["data"].partition(":")
    data = use_tz(load())
    by_id = {t["id"]: t for t in data["todos"]}

    if kind == "C":  # Kategorie fuer die offenen To-Dos dieser Nachricht
        todos = [t for t in data["todos"] if t.get("tgmsg") == msg["message_id"] and not t.get("cat")]
        for t in todos:
            t["cat"], t["updated"] = arg, now_ms()
            t.pop("tgmsg", None)
        if todos:
            save(data)
        tg_edit(chat_id, msg["message_id"],
                "\n".join(f"✅ {t['title']}\n    → {cat_label(arg)}" for t in todos) or "Schon erledigt 👍")
    elif kind == "D":  # Erledigt
        t = by_id.get(arg)
        if t:
            t["done"], t["status"], t["updated"] = True, "done", now_ms()
            save(data)
        tg_edit(chat_id, msg["message_id"], f"✅ Erledigt: {t['title']}" if t else "Nicht mehr gefunden.")
    elif kind == "S":  # Spaeter nochmal erinnern: S:<id>:<minuten>
        tid, _, minutes = arg.partition(":")
        t = by_id.get(tid)
        if t:
            later = datetime.now(TZ) + timedelta(minutes=int(minutes or 60))
            t["remindAt"], t["reminded"], t["updated"] = utc_iso(later), False, now_ms()
            save(data)
            tg_edit(chat_id, msg["message_id"], f"😴 {t['title']}\nIch erinnere dich um {later:%H:%M} Uhr wieder.")


def check_reminders():
    """Schickt alle faelligen Erinnerungen per Telegram und merkt sich, dass sie raus sind."""
    if not TG_CHAT:
        return
    data = use_tz(load())
    now = datetime.now(ZoneInfo("UTC"))
    changed = False
    for t in data["todos"]:
        if t.get("done") or t.get("deleted") or t.get("reminded") or not t.get("remindAt"):
            continue
        if datetime.fromisoformat(t["remindAt"].replace("Z", "+00:00")) > now:
            continue
        text = f"🔔 {t['title']}\n{cat_label(t.get('cat'))}"
        if t.get("due"):
            text += f"\n⏰ {fmt_due(t['due'])}"
        if t.get("notes"):
            text += f"\n📝 {t['notes']}"
        tg_send(TG_CHAT, text, [
            [{"text": "✅ Erledigt", "callback_data": f"D:{t['id']}"}],
            [{"text": "😴 1 Std", "callback_data": f"S:{t['id']}:60"},
             {"text": "😴 Morgen", "callback_data": f"S:{t['id']}:1440"}],
        ])
        t["reminded"], t["updated"] = True, now_ms()
        changed = True
    if changed:
        save(data)


def evening_check():
    """Jeden Abend ab 19 Uhr einmal: Was ist ueberfaellig, was steht heute noch und morgen an?"""
    if not TG_CHAT:
        return
    data = use_tz(load())
    now = datetime.now(TZ)
    if now.hour < EVENING:
        return
    state = load(STATE_FILE)
    today = f"{now:%Y-%m-%d}"
    if state.get("evening") == today:
        return
    tomorrow = f"{now + timedelta(days=1):%Y-%m-%d}"
    todos = [t for t in data["todos"] if not t.get("done") and not t.get("deleted") and t.get("due")]
    groups = [
        ("⚠️ Überfällig", [t for t in todos if t["due"][:10] < today]),
        ("📌 Heute noch", [t for t in todos if t["due"][:10] == today and due_local(t["due"]) > now]),
        ("🌅 Morgen", [t for t in todos if t["due"][:10] == tomorrow]),
    ]
    lines = ["🌙 Dein Abend-Check"]
    for label, items in groups:
        if items:
            lines.append(f"\n{label}")
            lines += [f"  • {CAT.get(t.get('cat'), {}).get('emoji', '📥')} {t['title']}"
                      + (f" ⏰ {due_local(t['due']):%H:%M}" if len(t["due"]) > 10 else "")
                      for t in sorted(items, key=lambda t: t["due"])]
    if len(lines) == 1:
        lines.append("Morgen steht nichts Festes an. Schönen Abend! ✨")
    tg_send(TG_CHAT, "\n".join(lines))
    state["evening"] = today
    save(state, STATE_FILE)


def main():
    missing = [k for k, v in {"TELEGRAM_TOKEN": TG_TOKEN, "GIST_TOKEN": GIST_TOKEN, "TODO_GIST_ID": GIST_ID,
                              "ANTHROPIC_API_KEY": ANTHROPIC_KEY, "GEMINI_API_KEY": GEMINI_KEY}.items() if not v]
    if missing:
        sys.exit("Fehlt: " + ", ".join(missing))
    once = "--once" in sys.argv  # offene Nachrichten abarbeiten, Erinnerungen schicken, beenden
    # --minuten N: so lange durchgehend laufen, dann sauber beenden (GitHub Actions startet den naechsten Lauf)
    minutes = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--minuten=")), 0)
    deadline = time.time() + minutes * 60 if minutes else None
    print("To-Do-Bot läuft." + (f" (für {minutes} Minuten)" if minutes else ""), flush=True)
    offset = None
    while True:
        if deadline and time.time() > deadline:
            if offset is not None:  # Verarbeitetes bei Telegram bestaetigen, damit der naechste Lauf es nicht doppelt macht
                requests.get(f"{TG}/getUpdates", params={"timeout": 0, "offset": offset}, timeout=30)
            print("Zeit um, bis zum nächsten Lauf.", flush=True)
            return
        try:
            r = requests.get(f"{TG}/getUpdates", params={"timeout": 0 if once else 50, "offset": offset}, timeout=70).json()
        except Exception as e:
            print("Telegram-Fehler:", e, flush=True)
            if once:
                sys.exit(1)
            time.sleep(5)
            continue
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            cb = u.get("callback_query")
            msg = u.get("message") or (cb or {}).get("message")
            if not msg:
                continue
            try:
                handle_callback(cb) if cb else handle(msg)
            except Exception as e:
                print("Fehler:", repr(e), flush=True)
                try:
                    tg_send(msg["chat"]["id"], "⚠️ Das hat nicht geklappt. Versuch es bitte nochmal.")
                except Exception:
                    pass
        if once and r.get("result"):
            continue  # weitere Nachrichten abholen
        try:
            check_reminders()
            evening_check()
        except Exception as e:
            print("Erinnerungs-Fehler:", repr(e), flush=True)
        if once:
            return


if __name__ == "__main__":
    main()
