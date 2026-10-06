#!/usr/bin/env python3
"""To-Do-Bot: Telegram (Text oder Sprachnachricht) -> Trello-Karten.

Ablauf: Nachricht kommt an -> bei Sprache wird sie in Text umgewandelt (Google Gemini)
-> Claude sortiert in Karten + passende Liste + Datum -> Karten landen in Trello.
Keine Schluessel im Code: alles kommt aus Umgebungsvariablen (.env lokal, Variablen in der Cloud).
"""
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

# --- Einstellungen (aus Umgebungsvariablen) ---------------------------------
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TRELLO_KEY = os.environ.get("TRELLO_KEY", "")
TRELLO_TOKEN = os.environ.get("TRELLO_TOKEN", "")
BOARD = os.environ.get("TRELLO_BOARD", "CvKnA1Yo")  # Franny's To-Do's
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")  # bevorzugtes Modell, sonst automatisch das neueste Flash-Modell
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Vienna"))

TG = f"https://api.telegram.org/bot{TG_TOKEN}"
TRELLO = "https://api.trello.com/1"


def tg_send(chat_id, text, buttons=None):
    body = {"chat_id": chat_id, "text": text}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": buttons}
    requests.post(f"{TG}/sendMessage", json=body, timeout=30)


def trello_lists():
    r = requests.get(
        f"{TRELLO}/boards/{BOARD}/lists",
        params={"key": TRELLO_KEY, "token": TRELLO_TOKEN, "fields": "name"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()  # [{id, name}]


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


def sort_todos(text, list_names):
    now = datetime.now(TZ)
    system = (
        "Du sortierst gesprochene oder getippte To-Dos in Trello-Karten fuer Sunny.\n"
        f"Heute ist {now:%A, %d.%m.%Y}, {now:%H:%M} Uhr (Zeitzone {TZ.key}).\n"
        "Verfuegbare Listen (exakt so schreiben): " + " | ".join(list_names) + "\n"
        "Regeln:\n"
        "- Mehrere To-Dos in einer Nachricht = mehrere Karten.\n"
        "- Titel kurz und konkret, mit Verb am Anfang, Sprache wie Sunny sie sagt (Deutsch).\n"
        "- list: die Liste, die Sunny nennt (auch sinngemaess, z. B. 'Franz privat' = Tagesliste Franz PRIVAT). "
        "Nennt sie keine, setze list auf null.\n"
        "- due: nur wenn ein Termin genannt wird, als ISO-Zeit lokal (YYYY-MM-DDTHH:MM). Ohne Uhrzeit 09:00. "
        "'morgen', 'Freitag' usw. ab heute ausrechnen. Sonst null.\n"
        "- desc: nur Zusatzdetails, die nicht in den Titel passen, sonst leer.\n"
        "- Erfinde nichts."
    )
    tool = {
        "name": "karten_anlegen",
        "description": "Legt die erkannten To-Dos als Trello-Karten an.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cards": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "list": {"type": ["string", "null"]},
                            "due": {"type": ["string", "null"]},
                            "desc": {"type": "string"},
                        },
                        "required": ["title", "list", "due"],
                    },
                }
            },
            "required": ["cards"],
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
            "tool_choice": {"type": "tool", "name": "karten_anlegen"},
            "messages": [{"role": "user", "content": text}],
        },
        timeout=60,
    )
    r.raise_for_status()
    for block in r.json()["content"]:
        if block["type"] == "tool_use":
            return block["input"]["cards"]
    return []


def find_list(name, lists):
    """Gibt die genannte Liste zurueck, oder None (dann fragt der Bot nach)."""
    if not name:
        return None
    wanted = name.lower()
    for l in lists:
        if l["name"].lower() == wanted:
            return l
    for l in lists:  # Teilmatch
        if wanted in l["name"].lower() or l["name"].lower() in wanted:
            return l
    return None


def list_buttons(lists):
    """Tasten fuer alle Listen, die 'Neue To-Do' heissen, zuerst."""
    ordered = sorted(lists, key=lambda l: "neue to-do" not in l["name"].lower())
    rows = [[{"text": l["name"], "callback_data": "L:" + l["id"]}] for l in ordered]
    return rows


def create_card(card, lst):
    params = {
        "key": TRELLO_KEY, "token": TRELLO_TOKEN,
        "idList": lst["id"], "name": card["title"], "pos": "bottom",
    }
    if card.get("desc"):
        params["desc"] = card["desc"]
    if card.get("due"):
        local = datetime.fromisoformat(card["due"]).replace(tzinfo=TZ)
        params["due"] = local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    r = requests.post(f"{TRELLO}/cards", params=params, timeout=30)
    r.raise_for_status()


def handle(msg):
    chat_id = str(msg["chat"]["id"])
    if not TG_CHAT:
        tg_send(chat_id, f"Hallo! Deine Chat-ID ist {chat_id}. Trage sie als TELEGRAM_CHAT_ID ein, dann bin ich nur für dich da.")
        return
    if chat_id != TG_CHAT:
        return  # Fremde werden ignoriert

    text = (msg.get("text") or "").strip()
    if text.startswith("/start") or text.startswith("/hilfe"):
        tg_send(chat_id, "Schick mir deine To-Dos als Text oder Sprachnachricht und sag dazu, wohin sie sollen "
                         "(z. B. 'Rechnung schreiben, in die Tagesliste, bis Freitag'). /listen zeigt dir die Listen.")
        return
    if text.startswith("/listen"):
        tg_send(chat_id, "Meine Listen:\n" + "\n".join("• " + l["name"] for l in trello_lists()))
        return

    voice = msg.get("voice") or msg.get("audio")
    if voice:
        text = transcribe(voice["file_id"])
        tg_send(chat_id, f"🎤 Verstanden: {text}")
    if not text:
        return

    lists = trello_lists()
    cards = sort_todos(text, [l["name"] for l in lists])
    if not cards:
        tg_send(chat_id, "Ich habe kein To-Do erkannt. Sag es mir bitte nochmal anders.")
        return
    lines, pending = [], []
    for c in cards:
        lst = find_list(c.get("list"), lists)
        if not lst:
            pending.append(c)
            continue
        create_card(c, lst)
        due = f" (bis {datetime.fromisoformat(c['due']):%d.%m. %H:%M})" if c.get("due") else ""
        lines.append(f"✅ {c['title']}{due}\n    → {lst['name']}")
    if lines:
        tg_send(chat_id, "\n".join(lines))
    if pending:
        txt = "❓ In welche Liste soll das?\n" + "\n".join(
            "• " + c["title"] + (f" ⏰ {c['due']}" if c.get("due") else "") for c in pending)
        tg_send(chat_id, txt, list_buttons(lists))


def handle_callback(cb):
    msg = cb["message"]
    chat_id = str(msg["chat"]["id"])
    if chat_id != TG_CHAT:
        return
    requests.post(f"{TG}/answerCallbackQuery", json={"callback_query_id": cb["id"]}, timeout=30)
    lists = trello_lists()
    lst = next((l for l in lists if l["id"] == cb["data"][2:]), None)
    cards = []
    for line in msg.get("text", "").splitlines():
        if line.startswith("• "):
            body, due = line[2:], None
            m = re.search(r" ⏰ (\d{4}-\d\d-\d\dT\d\d:\d\d)$", body)
            if m:
                due, body = m.group(1), body[:m.start()]
            cards.append({"title": body, "due": due})
    if not lst or not cards:
        return
    for c in cards:
        create_card(c, lst)
    done = "\n".join(f"✅ {c['title']}\n    → {lst['name']}" for c in cards)
    requests.post(f"{TG}/editMessageText", json={"chat_id": chat_id, "message_id": msg["message_id"], "text": done}, timeout=30)


def main():
    missing = [k for k, v in {"TELEGRAM_TOKEN": TG_TOKEN, "TRELLO_KEY": TRELLO_KEY, "TRELLO_TOKEN": TRELLO_TOKEN,
                              "ANTHROPIC_API_KEY": ANTHROPIC_KEY, "GEMINI_API_KEY": GEMINI_KEY}.items() if not v]
    if missing:
        sys.exit("Fehlt: " + ", ".join(missing))
    once = "--once" in sys.argv  # GitHub Actions: offene Nachrichten abarbeiten, dann beenden
    print("To-Do-Bot läuft.", flush=True)
    offset = None
    while True:
        try:
            r = requests.get(f"{TG}/getUpdates", params={"timeout": 0 if once else 50, "offset": offset}, timeout=70).json()
        except Exception as e:
            print("Telegram-Fehler:", e, flush=True)
            if once:
                sys.exit(1)
            time.sleep(5)
            continue
        if once and not r.get("result"):
            return
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


if __name__ == "__main__":
    main()
