#!/usr/bin/env python3
"""
56k WiFi Zeitmaschine - Wayback Machine Proxy

Ein HTTP-Proxy, der alle Anfragen ueber die Wayback Machine des Internet Archive leitet.
Das Ziel-Jahr wird aus der gemeinsamen Zustandsdatei gelesen.

Laeuft als transparenter Proxy auf Port 8888.
"""

import json
import re
import socket
import threading
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests

STATE_FILE = Path("/tmp/zeitmaschine_state.json")
WAYBACK_BASE = "https://web.archive.org/web"
PORTAL_IP = "192.168.4.1"
PORTAL_PORT = 8080

# Domains die nicht durch den Proxy geleitet werden sollen
BYPASS_DOMAINS = {
    "zeitmaschine.local",
    "192.168.4.1",
    "web.archive.org",
    "archive.org",
}

# Session fuer Connection-Pooling
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})


def get_year():
    """Liest das aktuell gesetzte Jahr aus der Zustandsdatei."""
    try:
        data = json.loads(STATE_FILE.read_text())
        if data.get("active", False):
            return data.get("year", 1999)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


class WaybackProxyHandler(BaseHTTPRequestHandler):
    """HTTP-Handler der Anfragen ueber die Wayback Machine leitet."""

    # Logging unterdruecken im Normalbetrieb
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def do_HEAD(self):
        self._handle_request("HEAD")

    def _handle_request(self, method):
        # Host aus dem Request extrahieren
        host = self.headers.get("Host", "").split(":")[0]

        # Bypass fuer lokale Domains
        if host in BYPASS_DOMAINS or host == "":
            self._redirect_to_portal()
            return

        # Captive Portal Detection abfangen
        if self._is_captive_check(host, self.path):
            self._redirect_to_portal()
            return

        year = get_year()

        # Wenn kein Jahr aktiv -> zum Portal leiten
        if year is None:
            self._redirect_to_portal()
            return

        # Original-URL rekonstruieren
        original_url = f"http://{host}{self.path}"

        # Wayback Machine URL bauen
        # Format: https://web.archive.org/web/YYYY/http://example.com/path
        wayback_url = f"{WAYBACK_BASE}/{year}/{original_url}"

        try:
            # Request an Wayback Machine weiterleiten
            headers = {}
            for key in ["Accept", "Accept-Language", "Accept-Encoding"]:
                if key in self.headers:
                    headers[key] = self.headers[key]

            # POST-Body lesen falls vorhanden
            body = None
            if method == "POST":
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    body = self.rfile.read(content_length)

            resp = session.request(
                method=method,
                url=wayback_url,
                headers=headers,
                data=body,
                allow_redirects=True,
                timeout=30,
                stream=True,
            )

            # Response zurueckgeben
            content = resp.content

            # Wayback Machine Toolbar und Banner entfernen
            content = self._strip_wayback_toolbar(content, resp.headers.get("Content-Type", ""))

            # Wayback-URLs in der Antwort zurueckschreiben auf originale URLs
            content = self._rewrite_urls(content, year, resp.headers.get("Content-Type", ""))

            self.send_response(resp.status_code)

            # Headers weiterleiten (gefiltert)
            skip_headers = {
                "transfer-encoding", "content-encoding",
                "content-length", "connection",
                "x-archive-orig-content-length",
            }
            for key, value in resp.headers.items():
                if key.lower() not in skip_headers:
                    # Wayback-spezifische Header nicht weiterleiten
                    if not key.lower().startswith("x-archive"):
                        self.send_header(key, value)

            self.send_header("Content-Length", str(len(content)))
            self.end_headers()

            if method != "HEAD":
                self.wfile.write(content)

        except requests.exceptions.Timeout:
            self._send_error(504, "Zeitmaschine: Die Wayback Machine antwortet nicht.")
        except requests.exceptions.ConnectionError:
            self._send_error(502, "Zeitmaschine: Keine Verbindung zur Wayback Machine.")
        except Exception as e:
            self._send_error(500, f"Zeitmaschine Fehler: {str(e)}")

    def _is_captive_check(self, host, path):
        """Erkennt Captive-Portal-Detection-Anfragen."""
        captive_indicators = [
            "connectivitycheck", "captive.apple.com",
            "msftconnecttest", "detectportal",
            "nmcheck.gnome.org", "generate_204",
            "gen_204", "hotspot-detect",
            "success.txt", "ncsi.txt",
        ]
        check = f"{host}{path}".lower()
        return any(ind in check for ind in captive_indicators)

    def _redirect_to_portal(self):
        """Leitet zum Captive Portal weiter."""
        self.send_response(302)
        self.send_header("Location", f"http://zeitmaschine.local/")
        self.end_headers()

    def _strip_wayback_toolbar(self, content, content_type):
        """Entfernt die Wayback Machine Toolbar aus HTML-Antworten."""
        if "text/html" not in content_type:
            return content

        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            return content

        # Wayback Machine Toolbar-Div entfernen
        text = re.sub(
            r'<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->',
            '', text, flags=re.DOTALL
        )

        # Wayback Machine Banner/Script entfernen
        text = re.sub(
            r'<script[^>]*>.*?__wm\.init\(.*?\).*?</script>',
            '', text, flags=re.DOTALL
        )

        # wombat.js und andere Wayback-Scripte entfernen
        text = re.sub(
            r'<script[^>]*src="[^"]*/(wombat|wbhack|analytics|client-rewrite)[^"]*\.js"[^>]*></script>',
            '', text, flags=re.DOTALL
        )

        # Wayback CSS entfernen
        text = re.sub(
            r'<link[^>]*href="[^"]*/_static/[^"]*"[^>]*/?>',
            '', text, flags=re.DOTALL
        )

        # Banner div entfernen
        text = re.sub(
            r'<div\s+id="wm-ipp-base"[^>]*>.*?</div>\s*</div>\s*</div>',
            '', text, flags=re.DOTALL
        )

        return text.encode("utf-8")

    def _rewrite_urls(self, content, year, content_type):
        """Schreibt Wayback-URLs zurueck auf die originalen URLs."""
        if "text/html" not in content_type and "text/css" not in content_type:
            return content

        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            return content

        # URLs wie /web/2000/http://example.com -> http://example.com
        text = re.sub(
            r'(https?://web\.archive\.org)?/web/\d{1,14}[a-z_]*/?(https?://)',
            r'\2',
            text
        )

        return text.encode("utf-8")

    def _send_error(self, code, message):
        """Sendet eine Fehlerseite im Zeitmaschine-Stil."""
        body = f"""<!DOCTYPE html>
<html><head><title>Zeitmaschine - Fehler</title>
<style>
body {{ background: #0a0a0a; color: #ff0040; font-family: monospace;
       display: flex; align-items: center; justify-content: center;
       min-height: 100vh; text-align: center; }}
h1 {{ font-size: 2rem; }}
p {{ color: #00ff41; margin-top: 1rem; }}
a {{ color: #00e5ff; }}
</style></head>
<body><div>
<h1>FEHLER {code}</h1>
<p>{message}</p>
<p><a href="http://zeitmaschine.local/">Zurueck zum Portal</a></p>
</div></body></html>"""

        content = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class ThreadedHTTPServer(HTTPServer):
    """HTTP Server mit Thread-Support."""
    allow_reuse_address = True

    def process_request(self, request, client_address):
        thread = threading.Thread(target=self._handle, args=(request, client_address))
        thread.daemon = True
        thread.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


def main():
    port = 8888
    server = ThreadedHTTPServer(("0.0.0.0", port), WaybackProxyHandler)
    print(f"Zeitmaschine Wayback-Proxy laeuft auf Port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProxy beendet.")
        server.shutdown()


if __name__ == "__main__":
    main()
