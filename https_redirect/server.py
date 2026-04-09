#!/usr/bin/env python3
"""
CHRONOSURF - HTTPS Redirect Server

Faengt alle HTTPS-Anfragen ab und leitet sie an die Wayback Machine weiter.

Wenn ein Client https://yahoo.com aufruft:
1. DNS-Hijacking leitet yahoo.com -> 192.168.4.1
2. Dieser Server antwortet auf Port 443 mit Self-Signed Cert
3. Browser zeigt Zertifikatswarnung (einmalig akzeptieren)
4. Server liest den Host-Header
5. Sendet 302 Redirect zu https://web.archive.org/web/YEAR/http://yahoo.com
6. Browser folgt dem Redirect direkt zum echten Archive

Das Jahr kommt aus dem State-File (pro MAC-Adresse).
Das Zertifikat wird beim ersten Start generiert.
"""

import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

STATE_FILE = Path("/tmp/chronosurf_state.json")
CERT_DIR = Path("/opt/chronosurf/https_redirect/certs")
CERT_FILE = CERT_DIR / "chronosurf.crt"
KEY_FILE = CERT_DIR / "chronosurf.key"
DEFAULT_YEAR = 1999

# Bypass: diese Domains werden NICHT an Wayback geleitet
# (chronosurf selbst + archive.org damit der Redirect zum Wayback funktioniert)
BYPASS_DOMAINS = {
    "chronosurf.local",
    "192.168.4.1",
}


# Cache: {(url, target_ts): (result_url_or_None, cache_time)}
_availability_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 3600  # 1h


def _query_availability(url, target_ts):
    """Ein einzelner Availability-API-Aufruf."""
    try:
        api_url = (
            "https://archive.org/wayback/available"
            f"?url={urllib.parse.quote(url, safe='')}"
            f"&timestamp={target_ts}"
        )
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "CHRONOSURF/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        closest = data.get("archived_snapshots", {}).get("closest")
        if closest and closest.get("available"):
            result = closest.get("url", "")
            # Wayback gibt oft http:// URLs zurueck - wir brauchen https://
            # sonst geht der Browser auf Port 80 und landet im iptables redirect
            if result.startswith("http://web.archive.org/"):
                result = "https://" + result[len("http://"):]
            # :80 aus der archivierten URL entfernen (browser-inkompatibel)
            result = result.replace(":80/", "/")
            return result
    except Exception as e:
        print(f"Availability API error for {url}: {e}", file=sys.stderr)
    return None


def find_closest_snapshot(url, year):
    """
    Fragt die Wayback Availability API nach dem naechstgelegenen Snapshot.
    Probiert mehrere URL-Varianten falls die erste nichts findet.

    Returns: Vollstaendige Wayback-URL mit exaktem Timestamp oder None.
    """
    target_ts = f"{year}0601000000"
    cache_key = (url, target_ts)

    with _cache_lock:
        cached = _availability_cache.get(cache_key)
        if cached and (time.time() - cached[1]) < CACHE_TTL:
            return cached[0]

    # URL-Varianten extrahieren
    # "http://example.com/path" -> host="example.com", path="/path"
    stripped = url.replace("http://", "").replace("https://", "")
    if "/" in stripped:
        host, path = stripped.split("/", 1)
        path = "/" + path
    else:
        host, path = stripped, ""

    # Domain ohne "www."
    bare_host = host[4:] if host.startswith("www.") else host
    www_host = "www." + bare_host

    # Probiere mehrere Varianten nacheinander
    # Trailing-Slash spielt eine Rolle bei der Wayback API!
    variants = [
        f"http://{host}{path}",            # Original
        f"http://{host}{path}/",           # Original + Slash
        f"http://{www_host}{path}",        # Mit www
        f"http://{www_host}{path}/",       # Mit www + Slash
        f"http://{bare_host}{path}",       # Ohne www
        f"http://{bare_host}{path}/",      # Ohne www + Slash
        host + path,                       # Ohne Protokoll
        bare_host,                         # Root-Domain ohne www
        www_host,                          # Root-Domain mit www
    ]

    # Duplikate entfernen, Reihenfolge beibehalten
    seen = set()
    variants = [v for v in variants if v not in seen and not seen.add(v)]

    result = None
    for variant in variants:
        result = _query_availability(variant, target_ts)
        if result:
            print(f"Found snapshot via variant '{variant}' -> {result}",
                  file=sys.stderr)
            break

    # Cachen (auch Failures fuer kurze Zeit)
    with _cache_lock:
        _availability_cache[cache_key] = (result, time.time())
        if len(_availability_cache) > 500:
            oldest = sorted(_availability_cache.items(), key=lambda x: x[1][1])[:100]
            for k, _ in oldest:
                del _availability_cache[k]

    return result


def _get_mac_for_ip(ip):
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
    """Liest das Jahr fuer eine Client-IP aus dem State."""
    mac = _get_mac_for_ip(client_ip)
    try:
        data = json.loads(STATE_FILE.read_text())
        client = data.get("clients", {}).get(mac, {})
        if client.get("active", False):
            return client.get("year", DEFAULT_YEAR)
        return data.get("global_year", DEFAULT_YEAR)
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_YEAR


def generate_cert():
    """Generiert ein Self-Signed Zertifikat falls noch keins da ist."""
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    if CERT_FILE.exists() and KEY_FILE.exists():
        return

    print("Generating self-signed certificate...")
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
        "-days", "3650", "-nodes",
        "-keyout", str(KEY_FILE),
        "-out", str(CERT_FILE),
        "-subj", "/CN=chronosurf.local/O=CHRONOSURF/C=US",
        "-addext", "subjectAltName=DNS:*,DNS:chronosurf.local,IP:192.168.4.1",
    ], check=True, capture_output=True)
    print(f"Certificate created: {CERT_FILE}")


class RedirectHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self._redirect()

    def do_POST(self):
        self._redirect()

    def do_HEAD(self):
        self._redirect()

    def _redirect(self):
        host = self.headers.get("Host", "").split(":")[0].lower()
        client_ip = self.client_address[0]

        # Bypass: lokale Domains
        if host in BYPASS_DOMAINS or host == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>CHRONOSURF</h1>")
            return

        year = get_year_for_ip(client_ip)

        # Erst Availability API fragen - findet den naechsten Snapshot
        # auch ueber Jahresgrenzen hinweg und probiert URL-Varianten
        original_url = f"http://{host}{self.path}"
        closest = find_closest_snapshot(original_url, year)

        if not closest:
            # Nichts im Archive gefunden -> schoene Fehlerseite
            self._send_not_archived(host, year)
            return

        wayback_url = closest
        closest_year = closest.split("/web/")[-1][:4] if "/web/" in closest else str(year)

        # HTML-Seite die automatisch weiterleitet
        # (besser als 302 damit die Zertifikatswarnung nur einmal kommt)
        body = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0;url={wayback_url}">
<title>CHRONOSURF - Time Warp</title>
<style>
body {{ background: #06080a; color: #00ff41; font-family: monospace;
       display: flex; align-items: center; justify-content: center;
       min-height: 100vh; text-align: center; }}
h1 {{ font-size: 2rem; text-shadow: 0 0 20px #00ff41; }}
p {{ color: #888; margin-top: 1rem; }}
a {{ color: #00e5ff; }}
.year {{ color: #00ff41; font-weight: 700; font-size: 3rem; }}
</style>
</head><body>
<div>
<h1>WARPING THROUGH TIME</h1>
<p>{host}</p>
<div class="year">{closest_year}</div>
{"<p style='color:#00e5ff;font-size:0.8rem'>closest snapshot to " + str(year) + "</p>" if closest_year != str(year) else ""}
<p>If you are not redirected automatically,<br><a href="{wayback_url}">click here</a></p>
</div>
<script>window.location.href = {wayback_url!r};</script>
</body></html>"""

        content = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_not_archived(self, host, year):
        """Freundliche Seite wenn die Wayback Machine keinen Snapshot hat."""
        body = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>CHRONOSURF - Not Archived</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#06080a;color:#c9d1d9;font-family:monospace;
min-height:100vh;display:flex;align-items:center;justify-content:center;
text-align:center;padding:2rem}}
.box{{max-width:500px}}
.code{{font-size:5rem;font-weight:700;color:#ff6b35;
text-shadow:0 0 30px rgba(255,107,53,0.3);line-height:1}}
h1{{font-size:1.2rem;color:#ff6b35;margin:1rem 0 0.5rem;letter-spacing:2px}}
.site{{color:#58a6ff;font-size:1.1rem;margin:0.5rem 0}}
.year{{color:#00ff41;font-weight:700}}
.msg{{color:#8b949e;font-size:0.9rem;line-height:1.6;margin:1.5rem 0}}
.btn{{display:inline-block;padding:0.6rem 1.5rem;border:1px solid #58a6ff;
border-radius:4px;color:#58a6ff;text-decoration:none;font-size:0.8rem;
letter-spacing:2px;margin-top:1rem}}
.btn:hover{{background:#58a6ff;color:#06080a}}
</style>
</head><body>
<div class="box">
<div class="code">404</div>
<h1>NOT ARCHIVED</h1>
<div class="site">{host}</div>
<div class="msg">
This site was never captured by the Wayback Machine,<br>
or it wasn't online in <span class="year">{year}</span>.
</div>
<a href="http://chronosurf.local/" class="btn">BACK TO CHRONOSURF</a>
</div>
</body></html>"""
        content = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


class ThreadedHTTPServer(HTTPServer):
    allow_reuse_address = True

    def process_request(self, request, client_address):
        thread = threading.Thread(
            target=self._handle, args=(request, client_address), daemon=True
        )
        thread.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except (ssl.SSLError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            print(f"Handler error: {e}", file=sys.stderr)
        finally:
            self.shutdown_request(request)


def main():
    generate_cert()

    port = 443
    server = ThreadedHTTPServer(("0.0.0.0", port), RedirectHandler)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(CERT_FILE), keyfile=str(KEY_FILE))

    server.socket = context.wrap_socket(server.socket, server_side=True)

    print(f"CHRONOSURF HTTPS Redirect Server on port {port}")
    print(f"  Cert: {CERT_FILE}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
