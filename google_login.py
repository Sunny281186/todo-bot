#!/usr/bin/env python3
"""Einmalig am eigenen Rechner ausfuehren: holt den GOOGLE_REFRESH_TOKEN fuer den Zoom-Bot.

  python3 google_login.py   (fragt nach Client-ID und Clientschluessel)

Oeffnet den Browser, du meldest dich mit deinem Google-Konto an, danach steht der Token im Terminal.
Braucht nur Python 3, keine weiteren Pakete. Der Bot darf nur Dateien sehen und aendern, die er selbst angelegt hat (Berechtigung drive.file).
"""
import http.server
import json
import os
import urllib.parse
import urllib.request
import webbrowser

CLIENT = os.environ.get("GOOGLE_CLIENT_ID") or input("Client-ID: ").strip()
SECRET = os.environ.get("GOOGLE_CLIENT_SECRET") or input("Clientschluessel: ").strip()
PORT = 8765
REDIRECT = f"http://localhost:{PORT}"


class Handler(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        Handler.code = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Fertig – du kannst dieses Fenster schließen.".encode())

    def log_message(self, *args):
        pass


url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
    "client_id": CLIENT, "redirect_uri": REDIRECT, "response_type": "code",
    "scope": "https://www.googleapis.com/auth/drive.file", "access_type": "offline", "prompt": "consent"})
print("Falls sich kein Browser oeffnet, diesen Link aufrufen:\n" + url, flush=True)
webbrowser.open(url)
server = http.server.HTTPServer(("localhost", PORT), Handler)
while not Handler.code:
    server.handle_request()
body = urllib.parse.urlencode({
    "code": Handler.code, "client_id": CLIENT, "client_secret": SECRET,
    "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).encode()
with urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30) as r:
    print("\nGOOGLE_REFRESH_TOKEN =", json.load(r)["refresh_token"])
