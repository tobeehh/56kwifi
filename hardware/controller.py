#!/usr/bin/env python3
"""
56k WiFi Zeitmaschine - Hardware Controller

Steuert den Rotary Encoder, SSD1306 Display und Button
zur lokalen Jahresauswahl am Geraet.

Hardware:
  - Rotary Encoder KY-040: CLK=GPIO17, DT=GPIO18, Button=GPIO27
  - SSD1306 OLED Display: I2C (SDA=GPIO2, SCL=GPIO3)
"""

import json
import signal
import sys
import time
import threading
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from luma.core.render import canvas
    from PIL import ImageFont, ImageDraw
    HW_AVAILABLE = True
except ImportError:
    HW_AVAILABLE = False
    print("WARNUNG: Hardware-Bibliotheken nicht verfuegbar (Simulation)")

# Konfiguration
STATE_FILE = Path("/tmp/zeitmaschine_state.json")
MIN_YEAR = 1996
MAX_YEAR = 2025
DEFAULT_YEAR = 1999

# GPIO Pins (BCM)
PIN_CLK = 17    # Rotary Encoder CLK
PIN_DT = 18     # Rotary Encoder DT
PIN_BTN = 27    # Rotary Encoder Button

# Display
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64

# Zustand
current_year = DEFAULT_YEAR
is_active = False
display_lock = threading.Lock()
last_clk_state = None


def get_state():
    """Liest den aktuellen Zustand."""
    global current_year, is_active
    try:
        data = json.loads(STATE_FILE.read_text())
        current_year = data.get("year", DEFAULT_YEAR)
        is_active = data.get("active", False)
    except (FileNotFoundError, json.JSONDecodeError):
        current_year = DEFAULT_YEAR
        is_active = False
    return current_year, is_active


def set_state(year, active):
    """Schreibt den Zustand in die gemeinsame Datei."""
    global current_year, is_active
    current_year = max(MIN_YEAR, min(MAX_YEAR, year))
    is_active = active
    state = {"year": current_year, "active": is_active}
    STATE_FILE.write_text(json.dumps(state))


def setup_gpio():
    """Initialisiert die GPIO-Pins."""
    global last_clk_state

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(PIN_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    last_clk_state = GPIO.input(PIN_CLK)

    # Interrupt fuer Rotary Encoder
    GPIO.add_event_detect(PIN_CLK, GPIO.BOTH, callback=rotary_callback, bouncetime=2)

    # Interrupt fuer Button (fallende Flanke = gedrueckt)
    GPIO.add_event_detect(PIN_BTN, GPIO.FALLING, callback=button_callback, bouncetime=300)


def rotary_callback(channel):
    """Callback fuer Rotary Encoder Drehung."""
    global current_year, last_clk_state

    clk_state = GPIO.input(PIN_CLK)
    dt_state = GPIO.input(PIN_DT)

    if clk_state != last_clk_state:
        if dt_state != clk_state:
            # Im Uhrzeigersinn -> Jahr erhoehen
            current_year = min(MAX_YEAR, current_year + 1)
        else:
            # Gegen Uhrzeigersinn -> Jahr verringern
            current_year = max(MIN_YEAR, current_year - 1)

        last_clk_state = clk_state
        update_display()


def button_callback(channel):
    """Callback fuer Button-Druck: Aktiviert/deaktiviert die Zeitreise."""
    global is_active

    # Entprellen
    time.sleep(0.05)
    if GPIO.input(PIN_BTN) != GPIO.LOW:
        return

    is_active = not is_active
    set_state(current_year, is_active)
    update_display()
    print(f"{'AKTIVIERT' if is_active else 'DEAKTIVIERT'}: Jahr {current_year}")


def setup_display():
    """Initialisiert das SSD1306 OLED Display."""
    serial = i2c(port=1, address=0x3C)
    device = ssd1306(serial, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)
    device.contrast(200)
    return device


def update_display():
    """Aktualisiert die Anzeige auf dem OLED Display."""
    if not HW_AVAILABLE:
        print(f"\r[Display] Jahr: {current_year}  "
              f"Status: {'AKTIV' if is_active else 'BEREIT'}  ", end="", flush=True)
        return

    with display_lock:
        try:
            with canvas(device) as draw:
                draw_interface(draw)
        except Exception as e:
            print(f"Display-Fehler: {e}")


def draw_interface(draw):
    """Zeichnet die Benutzeroberflaeche auf das Display."""
    # Titel
    draw.text((20, 0), "ZEITMASCHINE", fill="white")
    draw.line([(0, 12), (127, 12)], fill="white")

    # Jahr gross in der Mitte
    year_str = str(current_year)
    # Einfache grosse Darstellung
    draw.text((25, 18), year_str, fill="white")

    # Pfeile links/rechts
    draw.text((5, 22), "<", fill="white")
    draw.text((115, 22), ">", fill="white")

    # Trennlinie
    draw.line([(0, 42), (127, 42)], fill="white")

    # Status
    if is_active:
        draw.rectangle([(0, 46), (127, 63)], fill="white")
        draw.text((15, 48), "ZEITREISE AKTIV", fill="black")
    else:
        draw.rectangle([(0, 46), (127, 63)], outline="white")
        draw.text((25, 48), "DRUECKE START", fill="white")


def draw_boot_screen(draw):
    """Zeichnet den Boot-Screen."""
    draw.text((10, 5), "56k WiFi", fill="white")
    draw.text((10, 20), "ZEITMASCHINE", fill="white")
    draw.line([(0, 35), (127, 35)], fill="white")
    draw.text((10, 42), "Starte...", fill="white")


def poll_state_changes():
    """Ueberwacht Aenderungen der Zustandsdatei (z.B. vom Web-Portal)."""
    global current_year, is_active
    last_mtime = 0

    while True:
        try:
            if STATE_FILE.exists():
                mtime = STATE_FILE.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    old_year = current_year
                    old_active = is_active
                    get_state()
                    if current_year != old_year or is_active != old_active:
                        update_display()
        except Exception:
            pass
        time.sleep(1)


def cleanup(signum=None, frame=None):
    """Aufraeumen beim Beenden."""
    if HW_AVAILABLE:
        GPIO.cleanup()
        device.hide()
    print("\nHardware-Controller beendet.")
    sys.exit(0)


def main():
    global device

    print("56k WiFi Zeitmaschine - Hardware Controller")

    # Signale abfangen
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Zustand laden
    get_state()

    if HW_AVAILABLE:
        # Hardware initialisieren
        print("Initialisiere Hardware...")
        device = setup_display()

        # Boot-Screen anzeigen
        with canvas(device) as draw:
            draw_boot_screen(draw)
        time.sleep(2)

        setup_gpio()
        print("GPIO und Display initialisiert.")
    else:
        print("Simulation-Modus (keine Hardware erkannt)")
        device = None

    # Initiale Anzeige
    update_display()

    # State-Polling in separatem Thread starten
    poll_thread = threading.Thread(target=poll_state_changes, daemon=True)
    poll_thread.start()

    print(f"Controller laeuft. Jahr: {current_year}, Aktiv: {is_active}")
    print("Drehe am Encoder um das Jahr zu aendern, druecke zum Aktivieren.")

    # Hauptschleife
    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
