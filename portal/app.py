#!/usr/bin/env python3
"""
CHRONOSURF - Captive Portal & Proxy Controller

Web-Portal zur Jahresauswahl. Leitet Web-Traffic ueber die Wayback Machine.
State ist pro MAC-Adresse: Jedes Geraet kann ein eigenes Jahr waehlen.
"""

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, jsonify, make_response
)
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
from throttle import (
    SPEED_PRESETS, EPOCH_SPEEDS,
    set_speed_for_ip, remove_speed_for_ip,
    get_speed_label, get_recommended_speed,
    init_tc,
)

app = Flask(__name__)

# Zustandsdatei fuer alle Clients
STATE_FILE = Path("/tmp/chronosurf_state.json")
STATS_FILE = Path("/tmp/chronosurf_stats.json")
DEFAULT_YEAR = 1999

# Lock fuer thread-sichere Zugriffe
state_lock = threading.Lock()
stats_lock = threading.Lock()

# Favoriten pro Epoche
FAVORITES = {
    "90er": {
        "label": "Die 90er",
        "years": (1996, 1999),
        "sites": [
            {"name": "Yahoo!", "url": "yahoo.com", "desc": "DAS Webportal der 90er"},
            {"name": "GeoCities", "url": "geocities.com", "desc": "Eigene Homepage fuer alle"},
            {"name": "AltaVista", "url": "altavista.com", "desc": "Suchmaschine vor Google"},
            {"name": "Netscape", "url": "netscape.com", "desc": "Der erste grosse Browser"},
            {"name": "Amazon", "url": "amazon.com", "desc": "Damals nur ein Buchladen"},
            {"name": "eBay", "url": "ebay.com", "desc": "Online-Auktionen fuer alle"},
            {"name": "Slashdot", "url": "slashdot.org", "desc": "News for Nerds"},
            {"name": "HotBot", "url": "hotbot.com", "desc": "Wired Magazines Suchmaschine"},
        ]
    },
    "y2k": {
        "label": "Y2K Aera",
        "years": (2000, 2004),
        "sites": [
            {"name": "Google", "url": "google.com", "desc": "Der neue Suchmaschinen-Star"},
            {"name": "Napster", "url": "napster.com", "desc": "Musik-Revolution (RIP)"},
            {"name": "Wikipedia", "url": "wikipedia.org", "desc": "Die freie Enzyklopaedie"},
            {"name": "Heise Online", "url": "heise.de", "desc": "IT-News aus Deutschland"},
            {"name": "eBay.de", "url": "ebay.de", "desc": "3... 2... 1... meins!"},
            {"name": "AOL", "url": "aol.com", "desc": "You've got mail!"},
            {"name": "Spiegel Online", "url": "spiegel.de", "desc": "Nachrichten"},
            {"name": "Newgrounds", "url": "newgrounds.com", "desc": "Flash-Spiele & Animationen"},
        ]
    },
    "web2": {
        "label": "Web 2.0",
        "years": (2005, 2009),
        "sites": [
            {"name": "MySpace", "url": "myspace.com", "desc": "DAS soziale Netzwerk"},
            {"name": "YouTube", "url": "youtube.com", "desc": "Broadcast Yourself"},
            {"name": "Digg", "url": "digg.com", "desc": "Social News vor Reddit"},
            {"name": "StudiVZ", "url": "studivz.net", "desc": "Deutsches Facebook"},
            {"name": "Flickr", "url": "flickr.com", "desc": "Fotos teilen, Web 2.0 Style"},
            {"name": "reddit", "url": "reddit.com", "desc": "The front page of the internet"},
            {"name": "Twitter", "url": "twitter.com", "desc": "140 Zeichen reichen"},
            {"name": "last.fm", "url": "last.fm", "desc": "Musik-Scrobbling"},
        ]
    },
    "social": {
        "label": "Social Media",
        "years": (2010, 2015),
        "sites": [
            {"name": "Facebook", "url": "facebook.com", "desc": "Eine Milliarde Nutzer"},
            {"name": "Instagram", "url": "instagram.com", "desc": "Fotos mit Filtern"},
            {"name": "Tumblr", "url": "tumblr.com", "desc": "Blogs und Memes"},
            {"name": "Pinterest", "url": "pinterest.com", "desc": "Visuelle Inspiration"},
            {"name": "Vine", "url": "vine.co", "desc": "6-Sekunden-Videos (RIP)"},
            {"name": "SoundCloud", "url": "soundcloud.com", "desc": "Musik fuer alle"},
            {"name": "GitHub", "url": "github.com", "desc": "Social Coding"},
            {"name": "Twitch", "url": "twitch.tv", "desc": "Livestreaming"},
        ]
    },
    "modern": {
        "label": "Modern",
        "years": (2016, 2025),
        "sites": [
            {"name": "TikTok", "url": "tiktok.com", "desc": "Kurzvideos"},
            {"name": "Discord", "url": "discord.com", "desc": "Chat fuer Gamer"},
            {"name": "Mastodon", "url": "mastodon.social", "desc": "Dezentrales Social"},
            {"name": "Netflix", "url": "netflix.com", "desc": "Streaming-Gigant"},
            {"name": "Spotify", "url": "spotify.com", "desc": "Musik-Streaming"},
            {"name": "Wikipedia", "url": "wikipedia.org", "desc": "Immer noch da"},
            {"name": "StackOverflow", "url": "stackoverflow.com", "desc": "Antworten fuer Devs"},
            {"name": "YouTube", "url": "youtube.com", "desc": "Jetzt mit 4K und Shorts"},
        ]
    },
}


def _get_epoch_for_year(year):
    """Gibt die Epoche fuer ein Jahr zurueck."""
    for key, epoch in FAVORITES.items():
        if epoch["years"][0] <= year <= epoch["years"][1]:
            return key, epoch
    return "90er", FAVORITES["90er"]


def _get_client_ip():
    """Gibt die Client-IP zurueck."""
    return request.remote_addr or "unknown"


def _get_mac_for_ip(ip):
    """Liest die MAC-Adresse aus der ARP-Tabelle fuer eine IP."""
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
    # Fallback: IP als Identifier verwenden
    return ip


def _get_client_id():
    """Gibt die eindeutige Client-ID (MAC oder IP) zurueck."""
    ip = _get_client_ip()
    return _get_mac_for_ip(ip)


# --- State Management (pro MAC) ---

def get_all_states():
    """Liest den gesamten State aller Clients."""
    with state_lock:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except (json.JSONDecodeError, KeyError):
                pass
        return {"clients": {}, "global_year": DEFAULT_YEAR}


def _save_all_states(data):
    """Speichert den gesamten State."""
    with state_lock:
        STATE_FILE.write_text(json.dumps(data, indent=2))


def get_client_state(client_id=None):
    """Liest den State eines bestimmten Clients."""
    if client_id is None:
        client_id = _get_client_id()
    data = get_all_states()
    client = data.get("clients", {}).get(client_id, {})
    return {
        "year": client.get("year", data.get("global_year", DEFAULT_YEAR)),
        "active": client.get("active", False),
        "speed": client.get("speed", data.get("global_speed", "full")),
        "auto_speed": client.get("auto_speed", True),
        "client_id": client_id,
        "connected_since": client.get("connected_since", None),
    }


def set_client_state(year, active=True, client_id=None, speed=None, auto_speed=None):
    """Setzt den State fuer einen Client."""
    if client_id is None:
        client_id = _get_client_id()

    data = get_all_states()
    if "clients" not in data:
        data["clients"] = {}

    now = time.time()
    existing = data["clients"].get(client_id, {})

    # Auto-Speed: bestehenden Wert beibehalten oder Default (an)
    if auto_speed is None:
        auto_speed = existing.get("auto_speed", True)

    # Speed: wenn auto_speed aktiv und kein expliziter Speed, Epoche matchen
    if speed is None:
        if auto_speed:
            epoch_key = _get_epoch_for_year(int(year))[0]
            speed = get_recommended_speed(epoch_key)
        else:
            speed = existing.get("speed", "full")

    client_ip = _get_client_ip()

    data["clients"][client_id] = {
        "year": int(year),
        "active": active,
        "speed": speed,
        "auto_speed": auto_speed,
        "ip": client_ip,
        "connected_since": existing.get("connected_since", now) if active else None,
        "last_seen": now,
    }
    data["global_year"] = int(year)

    _save_all_states(data)

    # Traffic Shaping anwenden
    if active:
        set_speed_for_ip(client_ip, speed)
    else:
        remove_speed_for_ip(client_ip)

    # Statistik tracken
    if active and not existing.get("active", False):
        track_stat(client_id, "connections", year)

    _update_proxy()
    return get_client_state(client_id)


def _update_proxy():
    """Aktualisiert die iptables-Regeln fuer den Wayback-Proxy."""
    ap_ip = "192.168.4.1"
    proxy_port = "8888"

    # Pruefen ob mindestens ein Client aktiv ist
    data = get_all_states()
    any_active = any(
        c.get("active", False)
        for c in data.get("clients", {}).values()
    )

    # Alte Proxy-Regel entfernen (falls vorhanden)
    try:
        subprocess.run(
            ["iptables", "-t", "nat", "-D", "PREROUTING",
             "-i", "wlan0", "-p", "tcp", "--dport", "80",
             "-j", "DNAT", "--to-destination", f"{ap_ip}:{proxy_port}"],
            capture_output=True
        )
    except Exception:
        pass

    if any_active:
        # Proxy-Regel NACH der Portal-Ausnahme einfuegen (Position 2)
        # Position 1 = Portal-IP -> :8080 (darf nicht ueberschrieben werden)
        subprocess.run(
            ["iptables", "-t", "nat", "-I", "PREROUTING", "2",
             "-i", "wlan0", "-p", "tcp", "--dport", "80",
             "-j", "DNAT", "--to-destination", f"{ap_ip}:{proxy_port}"],
            capture_output=True
        )


# --- Statistik ---

def get_all_stats():
    """Liest alle Statistiken."""
    with stats_lock:
        if STATS_FILE.exists():
            try:
                return json.loads(STATS_FILE.read_text())
            except (json.JSONDecodeError, KeyError):
                pass
        return {"clients": {}, "total_connections": 0, "total_pages": 0}


def _save_all_stats(data):
    """Speichert alle Statistiken."""
    with stats_lock:
        STATS_FILE.write_text(json.dumps(data, indent=2))


def track_stat(client_id, stat_type, year=None):
    """Trackt eine Statistik-Aktion."""
    data = get_all_stats()

    if client_id not in data["clients"]:
        data["clients"][client_id] = {
            "connections": 0,
            "pages_visited": 0,
            "years_visited": [],
            "first_seen": time.time(),
            "last_seen": time.time(),
            "domains": {},
        }

    client_stats = data["clients"][client_id]
    client_stats["last_seen"] = time.time()

    if stat_type == "connections":
        client_stats["connections"] += 1
        data["total_connections"] += 1
        if year and year not in client_stats["years_visited"]:
            client_stats["years_visited"].append(year)

    elif stat_type == "page":
        client_stats["pages_visited"] += 1
        data["total_pages"] += 1

    elif stat_type == "domain" and year:
        # year wird hier als domain missbraucht
        domain = year
        client_stats["domains"][domain] = client_stats["domains"].get(domain, 0) + 1

    _save_all_stats(data)


def track_page_visit(client_ip, domain):
    """Trackt einen Seitenbesuch (aufgerufen vom Proxy)."""
    mac = _get_mac_for_ip(client_ip)
    track_stat(mac, "page")
    track_stat(mac, "domain", domain)


def _portal_template_vars():
    """Template-Variablen fuer die Hauptseite."""
    state = get_client_state()
    year = state["year"]
    epoch_key, epoch = _get_epoch_for_year(year)
    return {
        "year": year,
        "active": state["active"],
        "speed": state["speed"],
        "auto_speed": state["auto_speed"],
        "client_id": state["client_id"],
        "epoch_key": epoch_key,
        "epoch_label": epoch["label"],
        "favorites": epoch["sites"],
        "all_epochs": {k: v["label"] for k, v in FAVORITES.items()},
        "favorites_data": FAVORITES,
        "speed_presets": SPEED_PRESETS,
        "epoch_speeds": EPOCH_SPEEDS,
    }


# --- Captive Portal Detection Endpoints ---

@app.route("/generate_204")
@app.route("/gen_204")
def android_captive():
    return redirect("http://192.168.4.1:8080/", code=302)


@app.route("/hotspot-detect.html")
@app.route("/library/test/success.html")
def apple_captive():
    """Apple erwartet NICHT 'Success' im Body -> dann zeigt iOS das Portal-Sheet."""
    return render_template("index.html", **_portal_template_vars())


@app.route("/connecttest.txt")
@app.route("/ncsi.txt")
def windows_captive():
    return redirect("http://192.168.4.1:8080/", code=302)


@app.route("/canonical.html")
@app.route("/success.txt")
def firefox_captive():
    return redirect("http://192.168.4.1:8080/", code=302)


# --- Haupt-Routen ---

@app.route("/")
def index():
    """Hauptseite mit Jahresauswahl."""
    return render_template("index.html", **_portal_template_vars())


@app.route("/set", methods=["GET", "POST"])
def set_year():
    """Jahr und Speed setzen (per Form oder Query-Parameter)."""
    if request.method == "POST":
        year = request.form.get("year", DEFAULT_YEAR)
        speed = request.form.get("speed", None)
        auto_speed_val = request.form.get("auto_speed", None)
    else:
        year = request.args.get("year", DEFAULT_YEAR)
        speed = request.args.get("speed", None)
        auto_speed_val = request.args.get("auto_speed", None)

    try:
        year = int(year)
        year = max(1996, min(2025, year))
    except (ValueError, TypeError):
        year = DEFAULT_YEAR

    # Speed validieren
    if speed and speed not in SPEED_PRESETS:
        speed = None

    # Auto-Speed: Checkbox sendet "on" wenn checked, fehlt wenn unchecked
    auto_speed = None
    if auto_speed_val is not None:
        auto_speed = auto_speed_val in ("on", "true", "1")

    # Wenn auto_speed aktiv, speed nicht manuell setzen (wird automatisch gewaehlt)
    if auto_speed:
        speed = None

    state = set_client_state(year, active=True, speed=speed, auto_speed=auto_speed)
    if request.method == "POST":
        return redirect("/")
    return jsonify(state)


@app.route("/set_speed", methods=["POST"])
def set_speed():
    """Speed aendern ohne Jahr zu aendern (fuer laufende Verbindung)."""
    speed = request.form.get("speed", "full")
    if speed not in SPEED_PRESETS:
        speed = "full"

    state = get_client_state()
    # Manueller Speed-Wechsel deaktiviert auto_speed
    set_client_state(state["year"], active=state["active"], speed=speed, auto_speed=False)
    return redirect("/")


@app.route("/set_auto_speed", methods=["POST"])
def set_auto_speed():
    """Auto-Speed Toggle."""
    enabled = request.form.get("auto_speed") in ("on", "true", "1")
    state = get_client_state()
    speed = None  # Wird automatisch gewaehlt wenn auto_speed=True
    set_client_state(state["year"], active=state["active"], speed=speed, auto_speed=enabled)
    return redirect("/")


@app.route("/disconnect", methods=["POST"])
def disconnect():
    """Proxy deaktivieren - normales Internet."""
    state = get_client_state()
    set_client_state(state["year"], active=False)
    return redirect("/")


@app.route("/status")
def status():
    """API: Aktueller Status als JSON."""
    return jsonify(get_client_state())


@app.route("/stats")
def stats_page():
    """Statistik-Seite."""
    stats = get_all_stats()
    states = get_all_states()
    client_id = _get_client_id()
    my_stats = stats.get("clients", {}).get(client_id, {})
    my_state = get_client_state()

    # Alle aktiven Clients zaehlen
    active_clients = [
        {"id": cid, **cdata}
        for cid, cdata in states.get("clients", {}).items()
        if cdata.get("active", False)
    ]

    # Top-Domains des aktuellen Clients
    my_domains = sorted(
        my_stats.get("domains", {}).items(),
        key=lambda x: x[1], reverse=True
    )[:10]

    return render_template(
        "stats.html",
        total_connections=stats.get("total_connections", 0),
        total_pages=stats.get("total_pages", 0),
        client_count=len(stats.get("clients", {})),
        active_clients=active_clients,
        my_stats=my_stats,
        my_domains=my_domains,
        my_state=my_state,
        client_id=client_id,
        epoch_key=_get_epoch_for_year(my_state["year"])[0],
    )


@app.route("/api/track", methods=["POST"])
def api_track():
    """API fuer den Proxy zum Tracken von Seitenbesuchen."""
    data = request.get_json(silent=True)
    if data and "ip" in data and "domain" in data:
        track_page_visit(data["ip"], data["domain"])
    return jsonify({"ok": True})


@app.route("/api/year_for_ip/<ip>")
def api_year_for_ip(ip):
    """API: Gibt das Jahr fuer eine bestimmte IP zurueck (fuer den Proxy)."""
    mac = _get_mac_for_ip(ip)
    state = get_client_state(mac)
    if state["active"]:
        return jsonify({"year": state["year"], "active": True})
    return jsonify({"year": None, "active": False})


# Alle anderen Routen -> Captive Portal
@app.route("/<path:path>")
def catch_all(path):
    host = request.host.split(":")[0]
    if host != "chronosurf.local" and host != "192.168.4.1":
        return redirect("http://192.168.4.1:8080/", code=302)
    return redirect("/")


if __name__ == "__main__":
    if not STATE_FILE.exists():
        _save_all_states({"clients": {}, "global_year": DEFAULT_YEAR})
    if not STATS_FILE.exists():
        _save_all_stats({"clients": {}, "total_connections": 0, "total_pages": 0})

    # Traffic Shaping initialisieren
    init_tc()

    app.run(host="0.0.0.0", port=8080, debug=False)
