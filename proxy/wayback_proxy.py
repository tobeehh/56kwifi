#!/usr/bin/env python3
"""
CHRONOSURF - Wayback Machine Proxy

Ein HTTP-Proxy, der alle Anfragen ueber die Wayback Machine des Internet Archive leitet.
Das Ziel-Jahr wird pro Client (MAC-Adresse) aus der gemeinsamen Zustandsdatei gelesen.

Laeuft als transparenter Proxy auf Port 8888.
"""

import json
import re
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests

STATE_FILE = Path("/tmp/chronosurf_state.json")
WAYBACK_BASE = "https://web.archive.org/web"
PORTAL_IP = "192.168.4.1"
PORTAL_PORT = 8080

BYPASS_DOMAINS = {
    "chronosurf.local",
    "192.168.4.1",
    "web.archive.org",
    "archive.org",
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

# Cache fuer IP->MAC und IP->Jahr Mapping (TTL 10s)
_ip_cache = {}
_ip_cache_lock = threading.Lock()
_CACHE_TTL = 10


def _get_mac_for_ip(ip):
    """Liest die MAC-Adresse aus der ARP-Tabelle."""
    try:
        with open("/proc/net/arp", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip:
                    mac = parts[3]
                    if mac != "00:00:00:00:00:00":
                        return mac.upper()
    except (FileNotFoundError, PermissionError):
        pass
    return ip


def get_year_for_ip(client_ip):
    """Liest das Jahr fuer eine bestimmte Client-IP (mit Cache)."""
    now = time.time()

    with _ip_cache_lock:
        cached = _ip_cache.get(client_ip)
        if cached and (now - cached["time"]) < _CACHE_TTL:
            return cached["year"]

    # Cache miss - State-File lesen
    mac = _get_mac_for_ip(client_ip)
    year = None

    try:
        data = json.loads(STATE_FILE.read_text())
        client = data.get("clients", {}).get(mac, {})
        if client.get("active", False):
            year = client.get("year", None)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    with _ip_cache_lock:
        _ip_cache[client_ip] = {"year": year, "time": now}

    return year


def track_visit(client_ip, domain):
    """Sendet Besuchs-Tracking an das Portal (non-blocking)."""
    def _track():
        try:
            requests.post(
                f"http://127.0.0.1:{PORTAL_PORT}/api/track",
                json={"ip": client_ip, "domain": domain},
                timeout=2,
            )
        except Exception:
            pass

    thread = threading.Thread(target=_track, daemon=True)
    thread.start()


class WaybackProxyHandler(BaseHTTPRequestHandler):
    """HTTP-Handler der Anfragen ueber die Wayback Machine leitet."""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def do_HEAD(self):
        self._handle_request("HEAD")

    def _handle_request(self, method):
        host = self.headers.get("Host", "").split(":")[0]

        if host in BYPASS_DOMAINS or host == "":
            self._redirect_to_portal()
            return

        if self._is_captive_check(host, self.path):
            self._redirect_to_portal()
            return

        # Jahr fuer diesen Client ermitteln (per MAC)
        client_ip = self.client_address[0]
        year = get_year_for_ip(client_ip)

        if year is None:
            self._redirect_to_portal()
            return

        # Statistik tracken
        track_visit(client_ip, host)

        original_url = f"http://{host}{self.path}"
        wayback_url = f"{WAYBACK_BASE}/{year}/{original_url}"

        try:
            headers = {}
            for key in ["Accept", "Accept-Language", "Accept-Encoding"]:
                if key in self.headers:
                    headers[key] = self.headers[key]

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

            content = resp.content

            # Wayback 404: Seite existierte in diesem Jahr nicht
            if resp.status_code == 404 or (
                resp.status_code == 200 and b"Wayback Machine has not archived" in content
            ):
                self._send_not_archived(host, year)
                return

            # Wayback Redirect-Seite (keine Snapshots gefunden)
            if resp.status_code == 200 and b"Page cannot be crawled" in content:
                self._send_not_archived(host, year)
                return

            content_type = resp.headers.get("Content-Type", "")
            content = self._strip_wayback_toolbar(content, content_type)
            content = self._rewrite_urls(content, year, content_type)

            self.send_response(resp.status_code)

            skip_headers = {
                "transfer-encoding", "content-encoding",
                "content-length", "connection",
                "x-archive-orig-content-length",
            }
            for key, value in resp.headers.items():
                if key.lower() not in skip_headers:
                    if not key.lower().startswith("x-archive"):
                        self.send_header(key, value)

            self.send_header("Content-Length", str(len(content)))
            self.end_headers()

            if method != "HEAD":
                self.wfile.write(content)

        except requests.exceptions.Timeout:
            self._send_error(504, "CHRONOSURF: Die Wayback Machine antwortet nicht.")
        except requests.exceptions.ConnectionError:
            self._send_error(502, "CHRONOSURF: Keine Verbindung zur Wayback Machine.")
        except Exception as e:
            self._send_error(500, f"CHRONOSURF Fehler: {str(e)}")

    def _is_captive_check(self, host, path):
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
        self.send_response(302)
        self.send_header("Location", "http://192.168.4.1:8080/")
        self.end_headers()

    def _strip_wayback_toolbar(self, content, content_type):
        if "text/html" not in content_type:
            return content

        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            return content

        text = re.sub(
            r'<!-- BEGIN WAYBACK TOOLBAR INSERT -->.*?<!-- END WAYBACK TOOLBAR INSERT -->',
            '', text, flags=re.DOTALL
        )
        text = re.sub(
            r'<script[^>]*>.*?__wm\.init\(.*?\).*?</script>',
            '', text, flags=re.DOTALL
        )
        text = re.sub(
            r'<script[^>]*src="[^"]*/(wombat|wbhack|analytics|client-rewrite)[^"]*\.js"[^>]*></script>',
            '', text, flags=re.DOTALL
        )
        text = re.sub(
            r'<link[^>]*href="[^"]*/_static/[^"]*"[^>]*/?>',
            '', text, flags=re.DOTALL
        )
        text = re.sub(
            r'<div\s+id="wm-ipp-base"[^>]*>.*?</div>\s*</div>\s*</div>',
            '', text, flags=re.DOTALL
        )

        return text.encode("utf-8")

    def _rewrite_urls(self, content, year, content_type):
        if "text/html" not in content_type and "text/css" not in content_type:
            return content

        try:
            text = content.decode("utf-8", errors="replace")
        except Exception:
            return content

        text = re.sub(
            r'(https?://web\.archive\.org)?/web/\d{1,14}[a-z_]*/?(https?://)',
            r'\2',
            text
        )

        return text.encode("utf-8")

    def _send_not_archived(self, host, year):
        """Freundliche Seite wenn die Wayback Machine keinen Snapshot hat."""

        # Naechstes/vorheriges verfuegbares Jahr vorschlagen
        suggestions = ""
        for delta in [-1, -2, 1, 2, -5, 5]:
            alt_year = year + delta
            if 1996 <= alt_year <= 2025:
                suggestions += (
                    f'<a href="http://chronosurf.local/set?year={alt_year}">'
                    f'Try {alt_year}</a>  '
                )

        body = f"""<!DOCTYPE html>
<html><head><title>CHRONOSURF - Not Archived</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: #06080a; color: #c9d1d9; font-family: 'Consolas', monospace;
       min-height: 100vh; display: flex; align-items: center; justify-content: center;
       text-align: center; padding: 2rem; }}
.container {{ max-width: 500px; }}
.code {{ font-size: 5rem; font-weight: 700; color: #ff6b35;
         text-shadow: 0 0 30px rgba(255,107,53,0.3); line-height: 1; }}
h1 {{ font-size: 1.2rem; color: #ff6b35; margin: 1rem 0 0.5rem;
      letter-spacing: 2px; }}
.site {{ color: #58a6ff; font-size: 1.1rem; margin: 0.5rem 0; }}
.year {{ color: #00ff41; font-weight: 700; }}
.msg {{ color: #8b949e; font-size: 0.9rem; line-height: 1.6;
        margin: 1.5rem 0; }}
.ascii {{ color: #30363d; font-size: 0.7rem; line-height: 1.2;
          margin: 1.5rem 0; }}
.actions {{ margin-top: 1.5rem; display: flex; flex-direction: column;
            gap: 0.8rem; align-items: center; }}
a {{ color: #58a6ff; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.btn {{ display: inline-block; padding: 0.5rem 1.5rem;
        border: 1px solid #58a6ff; border-radius: 4px;
        color: #58a6ff; font-family: inherit; font-size: 0.8rem;
        letter-spacing: 1px; }}
.btn:hover {{ background: #58a6ff; color: #06080a; text-decoration: none; }}
.alts {{ margin-top: 1rem; font-size: 0.8rem; color: #8b949e; }}
.alts a {{ color: #00ff41; margin: 0 0.3rem; padding: 0.2rem 0.5rem;
           border: 1px solid #30363d; border-radius: 2px; }}
.alts a:hover {{ border-color: #00ff41; text-decoration: none; }}
</style></head>
<body>
<div class="container">
<pre class="ascii">
     _  _    ___  _  _
    | || |  / _ \\| || |
    | || |_| | | | || |_
    |__   _| | | |__   _|
       | | | |_| |  | |
       |_|  \\___/   |_|
</pre>
<h1>NOT ARCHIVED</h1>
<div class="site">{host}</div>
<div class="msg">
    This site was not archived by the Wayback Machine
    in <span class="year">{year}</span>.<br>
    It may not have existed yet, or was not crawled.
</div>
<div class="actions">
    <a href="http://192.168.4.1:8080/" class="btn">BACK TO CHRONOSURF</a>
    <a href="http://chronosurf.local/set?year={year}">Change year</a>
</div>
<div class="alts">
    Try another year: {suggestions}
</div>
</div>
</body></html>"""

        content = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_error(self, code, message):
        body = f"""<!DOCTYPE html>
<html><head><title>CHRONOSURF - Fehler</title>
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
<p><a href="http://192.168.4.1:8080/">Zurueck zum Portal</a></p>
</div></body></html>"""

        content = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class ThreadedHTTPServer(HTTPServer):
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
    print(f"CHRONOSURF Wayback-Proxy laeuft auf Port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProxy beendet.")
        server.shutdown()


if __name__ == "__main__":
    main()
