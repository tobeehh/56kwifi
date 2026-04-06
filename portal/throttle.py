"""
CHRONOSURF - Traffic Shaping / Speed Throttle

Drosselt die Bandbreite pro Client-IP via Linux tc (traffic control).
Verwendet HTB (Hierarchical Token Bucket) auf dem wlan0 Interface.

Speed-Presets sind an die jeweilige Epoche angelehnt.
"""

import subprocess
import threading

AP_INTERFACE = "wlan0"

# Speed presets: key -> (label, kbit/s downstream, beschreibung)
SPEED_PRESETS = {
    "56k":    {"label": "56k Modem",   "kbit": 56,    "desc": "Authentisch 1997"},
    "isdn":   {"label": "ISDN",        "kbit": 128,   "desc": "Kanalbuendelung 2000"},
    "dsl384": {"label": "DSL 384k",    "kbit": 384,   "desc": "Erstes DSL 2001"},
    "dsl1":   {"label": "DSL 1000",    "kbit": 1000,  "desc": "Standard DSL 2004"},
    "dsl6":   {"label": "DSL 6000",    "kbit": 6000,  "desc": "Schnelles DSL 2008"},
    "dsl16":  {"label": "DSL 16000",   "kbit": 16000, "desc": "VDSL 2012"},
    "full":   {"label": "Ungedrosselt", "kbit": 0,    "desc": "Volle Geschwindigkeit"},
}

# Empfohlene Geschwindigkeit pro Epoche
EPOCH_SPEEDS = {
    "90er":   "56k",
    "y2k":    "isdn",
    "web2":   "dsl1",
    "social": "dsl6",
    "modern": "full",
}

_lock = threading.Lock()
# Client-IP -> class-id mapping (fuer tc)
_client_classes = {}
_next_class_id = 10
_initialized = False


def _run(cmd):
    """Fuehrt einen Shell-Befehl aus (Fehler werden ignoriert)."""
    subprocess.run(cmd, shell=True, capture_output=True)


def init_tc():
    """Initialisiert die tc qdisc auf dem AP-Interface."""
    global _initialized
    if _initialized:
        return

    with _lock:
        if _initialized:
            return

        # Alte Regeln entfernen
        _run(f"tc qdisc del dev {AP_INTERFACE} root 2>/dev/null")

        # HTB qdisc anlegen
        _run(f"tc qdisc add dev {AP_INTERFACE} root handle 1: htb default 99")

        # Default-Klasse: ungedrosselt (100 Mbit)
        _run(f"tc class add dev {AP_INTERFACE} parent 1: classid 1:99 "
             f"htb rate 100mbit ceil 100mbit")

        _initialized = True


def set_speed_for_ip(client_ip, speed_key):
    """
    Setzt die Bandbreite fuer eine Client-IP.

    Args:
        client_ip: IP-Adresse des Clients
        speed_key: Key aus SPEED_PRESETS (z.B. "56k", "isdn", "full")
    """
    global _next_class_id

    if speed_key not in SPEED_PRESETS:
        speed_key = "full"

    preset = SPEED_PRESETS[speed_key]
    kbit = preset["kbit"]

    init_tc()

    with _lock:
        # Hat der Client bereits eine tc-Klasse?
        if client_ip in _client_classes:
            class_id = _client_classes[client_ip]

            if kbit == 0:
                # Drosselung aufheben: Klasse und Filter entfernen
                _run(f"tc filter del dev {AP_INTERFACE} parent 1: "
                     f"protocol ip prio 1 handle {class_id} fw classid 1:{class_id}")
                _run(f"tc class del dev {AP_INTERFACE} parent 1: "
                     f"classid 1:{class_id}")
                _run(f"iptables -t mangle -D POSTROUTING "
                     f"-d {client_ip} -j MARK --set-mark {class_id}")
                del _client_classes[client_ip]
                return
            else:
                # Klasse aktualisieren (change statt add)
                _run(f"tc class change dev {AP_INTERFACE} parent 1: "
                     f"classid 1:{class_id} htb rate {kbit}kbit ceil {kbit}kbit")
                return

        if kbit == 0:
            # Keine Drosselung noetig
            return

        # Neue tc-Klasse fuer diesen Client
        class_id = _next_class_id
        _next_class_id += 1
        _client_classes[client_ip] = class_id

        # HTB-Klasse mit Bandbreitenlimit
        _run(f"tc class add dev {AP_INTERFACE} parent 1: "
             f"classid 1:{class_id} htb rate {kbit}kbit ceil {kbit}kbit")

        # Paket-Markierung per iptables (mangle) fuer diesen Client
        _run(f"iptables -t mangle -A POSTROUTING "
             f"-d {client_ip} -j MARK --set-mark {class_id}")

        # tc Filter: markierte Pakete -> Klasse zuweisen
        _run(f"tc filter add dev {AP_INTERFACE} parent 1: "
             f"protocol ip prio 1 handle {class_id} fw classid 1:{class_id}")


def remove_speed_for_ip(client_ip):
    """Entfernt alle Drosselungsregeln fuer eine Client-IP."""
    set_speed_for_ip(client_ip, "full")


def cleanup():
    """Entfernt alle tc-Regeln."""
    global _initialized
    _run(f"tc qdisc del dev {AP_INTERFACE} root 2>/dev/null")
    # iptables mangle-Regeln aufraeumen
    with _lock:
        for ip, class_id in _client_classes.items():
            _run(f"iptables -t mangle -D POSTROUTING "
                 f"-d {ip} -j MARK --set-mark {class_id}")
        _client_classes.clear()
    _initialized = False


def get_speed_label(speed_key):
    """Gibt das Label fuer einen Speed-Key zurueck."""
    preset = SPEED_PRESETS.get(speed_key, SPEED_PRESETS["full"])
    return preset["label"]


def get_recommended_speed(epoch_key):
    """Gibt die empfohlene Geschwindigkeit fuer eine Epoche zurueck."""
    return EPOCH_SPEEDS.get(epoch_key, "full")
