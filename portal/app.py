#!/usr/bin/env python3
"""
56k WiFi Zeitmaschine - Captive Portal & Proxy Controller

Stellt ein Web-Portal bereit, ueber das Nutzer ein Jahr auswaehlen koennen.
Leitet dann den gesamten Web-Traffic ueber die Wayback Machine.
"""

import json
import os
import subprocess
import threading
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, jsonify, make_response
)

app = Flask(__name__)

# Zustandsdatei fuer das aktuell gesetzte Jahr
STATE_FILE = Path("/tmp/zeitmaschine_state.json")
DEFAULT_YEAR = 1999

# Lock fuer thread-sichere Zugriffe
state_lock = threading.Lock()


def get_state():
    """Liest den aktuellen Zustand (gewaehltes Jahr)."""
    with state_lock:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                return data
            except (json.JSONDecodeError, KeyError):
                pass
        return {"year": DEFAULT_YEAR, "active": False}


def set_state(year, active=True):
    """Setzt das Jahr und aktiviert/deaktiviert den Proxy."""
    with state_lock:
        state = {"year": int(year), "active": active}
        STATE_FILE.write_text(json.dumps(state))
    # Proxy-Konfiguration aktualisieren
    _update_proxy(int(year), active)
    return state


def _update_proxy(year, active):
    """Aktualisiert die iptables-Regeln fuer den Wayback-Proxy."""
    ap_ip = "192.168.4.1"
    proxy_port = "8888"

    try:
        # Alte Proxy-Regeln entfernen
        subprocess.run(
            ["iptables", "-t", "nat", "-D", "PREROUTING",
             "-i", "wlan0", "-p", "tcp", "--dport", "80",
             "-j", "DNAT", "--to-destination", f"{ap_ip}:{proxy_port}"],
            capture_output=True
        )
    except Exception:
        pass

    if active:
        # Neue Regel: HTTP-Traffic durch Wayback-Proxy leiten
        subprocess.run(
            ["iptables", "-t", "nat", "-I", "PREROUTING", "1",
             "-i", "wlan0", "-p", "tcp", "--dport", "80",
             "-j", "DNAT", "--to-destination", f"{ap_ip}:{proxy_port}"],
            capture_output=True
        )


# --- Captive Portal Detection Endpoints ---

@app.route("/generate_204")
@app.route("/gen_204")
def android_captive():
    """Android Captive Portal Detection."""
    return redirect("http://zeitmaschine.local/", code=302)


@app.route("/hotspot-detect.html")
@app.route("/library/test/success.html")
def apple_captive():
    """Apple Captive Portal Detection."""
    return redirect("http://zeitmaschine.local/", code=302)


@app.route("/connecttest.txt")
@app.route("/ncsi.txt")
def windows_captive():
    """Windows Captive Portal Detection."""
    return redirect("http://zeitmaschine.local/", code=302)


@app.route("/canonical.html")
@app.route("/success.txt")
def firefox_captive():
    """Firefox Captive Portal Detection."""
    return redirect("http://zeitmaschine.local/", code=302)


# --- Haupt-Routen ---

@app.route("/")
def index():
    """Hauptseite mit Jahresauswahl."""
    state = get_state()
    return render_template("index.html", year=state["year"], active=state["active"])


@app.route("/set", methods=["GET", "POST"])
def set_year():
    """Jahr setzen (per Form oder Query-Parameter)."""
    if request.method == "POST":
        year = request.form.get("year", DEFAULT_YEAR)
    else:
        year = request.args.get("year", DEFAULT_YEAR)

    try:
        year = int(year)
        if year < 1996:
            year = 1996
        if year > 2025:
            year = 2025
    except (ValueError, TypeError):
        year = DEFAULT_YEAR

    state = set_state(year, active=True)
    if request.method == "POST":
        return redirect("/")
    return jsonify(state)


@app.route("/disconnect", methods=["POST"])
def disconnect():
    """Proxy deaktivieren - normales Internet."""
    state = set_state(get_state()["year"], active=False)
    return redirect("/")


@app.route("/status")
def status():
    """API: Aktueller Status als JSON."""
    return jsonify(get_state())


# Alle anderen Routen -> Captive Portal
@app.route("/<path:path>")
def catch_all(path):
    """Fange alle nicht-gematchten Anfragen ab -> Portal."""
    # Wenn Host nicht zeitmaschine.local ist, ist es ein Captive-Portal-Redirect
    host = request.host.split(":")[0]
    if host != "zeitmaschine.local" and host != "192.168.4.1":
        return redirect("http://zeitmaschine.local/", code=302)
    return redirect("/")


if __name__ == "__main__":
    # Initialen Zustand setzen
    if not STATE_FILE.exists():
        set_state(DEFAULT_YEAR, active=False)

    app.run(host="0.0.0.0", port=8080, debug=False)
