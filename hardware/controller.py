#!/usr/bin/env python3
"""
CHRONOSURF - Hardware Controller

Steuert den Rotary Encoder, I2C LCD 20x4 und Button.
Synchronisiert sich mit dem Web-Portal ueber die gemeinsame State-Datei.

Das State-File hat folgendes Format (geschrieben vom Portal):
{
  "clients": {
    "AA:BB:CC:DD:EE:FF": {"year": 1999, "active": true, "ip": "..."},
    ...
  },
  "global_year": 1999
}

Der Hardware-Controller:
- Zeigt auf dem LCD: gewaehltes Jahr, Anzahl aktiver Surfer, letztes Event
- Rotary Encoder aendert das global_year (Vorauswahl fuer neue Clients)
- Button-Druck hat keine connect/disconnect Funktion mehr (das machen
  die Clients selbst), sondern bestaetigt das Jahr als Default

Hardware:
  - Rotary Encoder KY-040: CLK=GPIO17, DT=GPIO18, Button=GPIO27
  - I2C LCD 20x4 (HD44780 + PCF8574): I2C Bus 1, Adresse 0x27
  - Passiver Buzzer: GPIO22 (56k Modem-Sound)
"""

import json
import signal
import sys
import time
import threading
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    from RPLCD.i2c import CharLCD
    HW_AVAILABLE = True
except ImportError:
    HW_AVAILABLE = False
    print("WARNING: Hardware libraries not available (simulation mode)")

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).parent))
from buzzer import (
    setup as buzzer_setup, play_dialup_sound, play_disconnect_sound,
    play_click_sound, play_async, cleanup as buzzer_cleanup
)

# Konfiguration
STATE_FILE = Path("/tmp/chronosurf_state.json")
MIN_YEAR = 1996
MAX_YEAR = 2025
DEFAULT_YEAR = 1999

# GPIO Pins (BCM)
PIN_CLK = 17
PIN_DT = 18
PIN_BTN = 27

# LCD
LCD_I2C_ADDR = 0x27
LCD_I2C_PORT = 1
LCD_COLS = 20
LCD_ROWS = 4

# Custom characters
CHAR_BLOCK   = (0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F)
CHAR_HALF    = (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10)
CHAR_ARROW_R = (0x00, 0x04, 0x06, 0x1F, 0x1F, 0x06, 0x04, 0x00)
CHAR_ARROW_L = (0x00, 0x04, 0x0C, 0x1F, 0x1F, 0x0C, 0x04, 0x00)
CHAR_CONN    = (0x00, 0x0E, 0x11, 0x04, 0x0A, 0x00, 0x04, 0x00)

# Zustand
current_year = DEFAULT_YEAR
active_count = 0
active_clients = []     # [{year, id_short}, ...]
last_event = ""         # z.B. "A3:F2 -> 2001"
display_lock = threading.Lock()
last_clk_state = None
lcd = None


def get_epoch_name(year):
    """Returns short epoch name for a year."""
    if year <= 1999: return "90s"
    if year <= 2004: return "Y2K"
    if year <= 2009: return "WEB2.0"
    if year <= 2015: return "SOCIAL"
    return "MODERN"


def read_state():
    """Liest das per-MAC State-File und extrahiert Gesamtbild."""
    global current_year, active_count, active_clients, last_event
    try:
        data = json.loads(STATE_FILE.read_text())

        # global_year als Default-Anzeige
        current_year = data.get("global_year", DEFAULT_YEAR)

        # Aktive Clients zaehlen
        clients = data.get("clients", {})
        active_clients = []
        for mac, info in clients.items():
            if info.get("active", False):
                active_clients.append({
                    "year": info.get("year", DEFAULT_YEAR),
                    "id": mac[-5:],  # Letzte 5 Zeichen der MAC
                })
        active_count = len(active_clients)

    except (FileNotFoundError, json.JSONDecodeError):
        current_year = DEFAULT_YEAR
        active_count = 0
        active_clients = []


def write_global_year(year):
    """Schreibt nur das global_year in die State-Datei (ohne Clients zu aendern)."""
    global current_year
    current_year = max(MIN_YEAR, min(MAX_YEAR, year))

    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
        else:
            data = {"clients": {}, "global_year": DEFAULT_YEAR}
    except (json.JSONDecodeError, FileNotFoundError):
        data = {"clients": {}, "global_year": DEFAULT_YEAR}

    data["global_year"] = current_year
    STATE_FILE.write_text(json.dumps(data, indent=2))


def setup_gpio():
    """Initialisiert die GPIO-Pins."""
    global last_clk_state

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    GPIO.setup(PIN_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    last_clk_state = GPIO.input(PIN_CLK)

    GPIO.add_event_detect(PIN_CLK, GPIO.BOTH, callback=rotary_callback, bouncetime=2)
    GPIO.add_event_detect(PIN_BTN, GPIO.FALLING, callback=button_callback, bouncetime=300)


def rotary_callback(channel):
    """Callback fuer Rotary Encoder Drehung - aendert global_year."""
    global current_year, last_clk_state

    clk_state = GPIO.input(PIN_CLK)
    dt_state = GPIO.input(PIN_DT)

    if clk_state != last_clk_state:
        if dt_state != clk_state:
            current_year = min(MAX_YEAR, current_year + 1)
        else:
            current_year = max(MIN_YEAR, current_year - 1)

        last_clk_state = clk_state
        play_click_sound()
        update_display()


def button_callback(channel):
    """Button-Druck: Setzt das global_year (Default fuer neue Portal-Besucher)."""
    time.sleep(0.05)
    if GPIO.input(PIN_BTN) != GPIO.LOW:
        return

    write_global_year(current_year)
    print(f"Global year set to {current_year}")

    # Kurze Bestaetigung auf dem Display
    if HW_AVAILABLE and lcd is not None:
        with display_lock:
            _lcd_write_line(3, f" \x04 SET: {current_year} {get_epoch_name(current_year):>8s}")
        time.sleep(1)
    update_display()


def setup_display():
    """Initialisiert das I2C LCD 20x4."""
    try:
        display = CharLCD(
            i2c_expander='PCF8574',
            address=LCD_I2C_ADDR,
            port=LCD_I2C_PORT,
            cols=LCD_COLS,
            rows=LCD_ROWS,
            dotsize=8,
            auto_linebreaks=False,
        )
    except Exception:
        display = CharLCD(
            i2c_expander='PCF8574',
            address=0x3F,
            port=LCD_I2C_PORT,
            cols=LCD_COLS,
            rows=LCD_ROWS,
            dotsize=8,
            auto_linebreaks=False,
        )

    display.create_char(0, CHAR_BLOCK)
    display.create_char(1, CHAR_HALF)
    display.create_char(2, CHAR_ARROW_R)
    display.create_char(3, CHAR_ARROW_L)
    display.create_char(4, CHAR_CONN)

    display.backlight_enabled = True
    display.clear()
    return display


def _timeline_bar(year):
    """Erzeugt einen 20-Zeichen Zeitstrahl-Balken."""
    pos = int(((year - MIN_YEAR) / (MAX_YEAR - MIN_YEAR)) * 18)
    bar = "\x03"
    for i in range(18):
        if i == pos:
            bar += "\x00"
        elif i < pos:
            bar += "-"
        else:
            bar += "\xA5"
    bar += "\x02"
    return bar


def update_display():
    """Aktualisiert die LCD-Anzeige."""
    if not HW_AVAILABLE:
        epoch = get_epoch_name(current_year)
        print(f"\r[LCD]  CHRONOSURF  surfers:{active_count}", end="")
        print(f"\n       <<< {current_year} >>> {epoch:>6s}", end="")
        bar_pos = (current_year - MIN_YEAR) * 18 // (MAX_YEAR - MIN_YEAR)
        bar = f"[{'=' * bar_pos}>{'-' * (18 - bar_pos)}]"
        print(f"\n       {bar}", end="")
        if active_count > 0:
            surfers = ", ".join(f"{c['id']}:{c['year']}" for c in active_clients[:3])
            print(f"\n       \x04 {surfers}", end="", flush=True)
        else:
            print(f"\n         No surfers online", end="", flush=True)
        print("\033[4A", end="")
        return

    with display_lock:
        try:
            epoch = get_epoch_name(current_year)
            timeline = _timeline_bar(current_year)

            # Zeile 1: Header + Surfer-Count
            if active_count > 0:
                line1 = f"CHRONOSURF  \x04{active_count} online"
            else:
                line1 = "CHRONOSURF"

            # Zeile 2: Jahr + Epoche
            line2 = f"  <<< {current_year} >>> {epoch:>6s}"

            # Zeile 3: Timeline
            line3 = timeline

            # Zeile 4: Aktive Surfer oder "Waiting..."
            if active_count > 0:
                # Zeige aktive Surfer: "A3:F2>01 B4:C1>99"
                parts = []
                for c in active_clients[:2]:
                    yr_short = str(c["year"])[2:]
                    parts.append(f"{c['id']}>{yr_short}")
                line4 = " ".join(parts)
            else:
                line4 = "  Waiting for surfers"

            lcd.home()
            lcd.write_string(line1[:LCD_COLS].ljust(LCD_COLS))
            lcd.cursor_pos = (1, 0)
            lcd.write_string(line2[:LCD_COLS].ljust(LCD_COLS))
            lcd.cursor_pos = (2, 0)
            lcd.write_string(line3[:LCD_COLS].ljust(LCD_COLS))
            lcd.cursor_pos = (3, 0)
            lcd.write_string(line4[:LCD_COLS].ljust(LCD_COLS))

        except Exception as e:
            print(f"LCD error: {e}")


def _lcd_write_line(row, text):
    """Schreibt eine Zeile auf das LCD (padded auf 20 Zeichen)."""
    lcd.cursor_pos = (row, 0)
    lcd.write_string(text[:LCD_COLS].ljust(LCD_COLS))


def _lcd_scroll_up(new_line):
    """Scrollt alle Zeilen eins hoch und schreibt neue Zeile unten."""
    _lcd_scroll_up._buf = getattr(_lcd_scroll_up, '_buf', [''] * LCD_ROWS)
    _lcd_scroll_up._buf.pop(0)
    _lcd_scroll_up._buf.append(new_line)
    for i, line in enumerate(_lcd_scroll_up._buf):
        _lcd_write_line(i, line)


def _boot_type(text, delay=0.04):
    """Tippt Text zeichenweise in die unterste Zeile."""
    _lcd_scroll_up._buf = getattr(_lcd_scroll_up, '_buf', [''] * LCD_ROWS)
    _lcd_scroll_up._buf.pop(0)
    _lcd_scroll_up._buf.append('')

    for i in range(LCD_ROWS - 1):
        _lcd_write_line(i, _lcd_scroll_up._buf[i])

    current = ''
    for ch in text[:LCD_COLS]:
        current += ch
        lcd.cursor_pos = (LCD_ROWS - 1, 0)
        lcd.write_string(current)
        time.sleep(delay)

    _lcd_scroll_up._buf[LCD_ROWS - 1] = text


def show_boot_screen():
    """Terminal-style Boot-Sequenz wie im Web-UI."""
    if not HW_AVAILABLE:
        boot_lines = [
            "CHRONOSURF BIOS 1.0",
            "(c) Temporal Net Inc",
            "",
            "Detecting HW...",
            " CPU: BCM2837  [OK]",
            " RAM: 1024MB   [OK]",
            " ETH: 100Mbps  [OK]",
            " WLAN: AP mode [OK]",
            " I2C: LCD 20x4 [OK]",
            " GPIO: Encoder [OK]",
            " GPIO: Buzzer  [OK]",
            "",
            "Init temporal sys...",
            " Wayback: CONNECTED",
            " Nodes: 735B pages",
            " Range: 1996 - 2025",
            "",
            "> READY.",
            "> SURF THE TIMELINE.",
        ]
        for line in boot_lines:
            print(f"[BOOT] {line}")
            time.sleep(0.06)
        return

    _lcd_scroll_up._buf = [''] * LCD_ROWS
    lcd.clear()

    boot_sequence = [
        ("CHRONOSURF BIOS 1.0", "type", 0.3),
        ("(c)Temporal Net Inc.", "line", 0.4),
        ("", "line", 0.2),
        ("Detecting HW...", "type", 0.3),
        (" CPU: BCM2837  [OK]", "line", 0.15),
        (" RAM: 1024MB   [OK]", "line", 0.1),
        (" ETH: 100Mbps  [OK]", "line", 0.15),
        (" WLAN: AP mode [OK]", "line", 0.15),
        (" I2C: LCD@0x27 [OK]", "line", 0.1),
        (" GPIO: Encoder [OK]", "line", 0.1),
        (" GPIO: Buzzer  [OK]", "line", 0.15),
        ("", "line", 0.2),
        ("Init temporal sys..", "type", 0.3),
        (" Wayback: CONNECTED", "line", 0.2),
        (" 735 billion pages", "line", 0.15),
        (" Range: 1996 - 2025", "line", 0.2),
        ("", "line", 0.15),
        ("> READY.", "type", 0.3),
        (">SURF THE TIMELINE.", "type", 0.5),
    ]

    for text, mode, delay_after in boot_sequence:
        if mode == "type":
            _boot_type(text, delay=0.03)
        else:
            _lcd_scroll_up(text)
        time.sleep(delay_after)


def show_surfer_connected(mac_short, year):
    """Animation wenn ein Surfer sich ueber das Web-Portal verbindet."""
    if not HW_AVAILABLE or lcd is None:
        print(f"[LCD] SURFER CONNECTED: {mac_short} -> {year}")
        return

    with display_lock:
        # Kurze Animation: Flash-Nachricht auf dem Display
        _lcd_write_line(3, f"\x04 {mac_short} > {year} ONLINE")
    time.sleep(1.5)
    update_display()


def show_surfer_disconnected(mac_short, year):
    """Animation wenn ein Surfer sich trennt."""
    if not HW_AVAILABLE or lcd is None:
        print(f"[LCD] SURFER DISCONNECTED: {mac_short}")
        return

    with display_lock:
        _lcd_write_line(3, f"  {mac_short} OFFLINE")
    time.sleep(1)
    update_display()


def poll_state_changes():
    """Ueberwacht die State-Datei und reagiert auf Aenderungen."""
    global active_count, active_clients, current_year
    last_mtime = 0
    prev_active_macs = set()

    while True:
        try:
            if STATE_FILE.exists():
                mtime = STATE_FILE.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime

                    # Vorherigen Zustand merken
                    old_active_macs = prev_active_macs.copy()
                    old_year = current_year

                    # Neuen Zustand lesen
                    read_state()

                    # Aktive MACs ermitteln
                    now_active_macs = set()
                    mac_year_map = {}
                    try:
                        data = json.loads(STATE_FILE.read_text())
                        for mac, info in data.get("clients", {}).items():
                            if info.get("active", False):
                                now_active_macs.add(mac)
                                mac_year_map[mac] = info.get("year", DEFAULT_YEAR)
                    except Exception:
                        pass

                    # Neue Verbindungen erkennen
                    new_connections = now_active_macs - old_active_macs
                    lost_connections = old_active_macs - now_active_macs

                    for mac in new_connections:
                        year = mac_year_map.get(mac, current_year)
                        mac_short = mac[-5:]
                        print(f"NEW SURFER: {mac_short} -> {year}")
                        play_async(play_dialup_sound)
                        show_surfer_connected(mac_short, year)

                    for mac in lost_connections:
                        mac_short = mac[-5:]
                        print(f"SURFER LEFT: {mac_short}")
                        play_async(play_disconnect_sound)
                        show_surfer_disconnected(mac_short, current_year)

                    prev_active_macs = now_active_macs

                    # Display updaten wenn sich was geaendert hat
                    # (auch ohne connect/disconnect, z.B. Jahreswechsel)
                    if not new_connections and not lost_connections:
                        if current_year != old_year or active_count != len(old_active_macs):
                            update_display()

        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(1)


def cleanup(signum=None, frame=None):
    """Aufraeumen beim Beenden."""
    buzzer_cleanup()
    if HW_AVAILABLE:
        GPIO.cleanup()
        if lcd is not None:
            lcd.clear()
            lcd.cursor_pos = (0, 0)
            lcd.write_string("   CHRONOSURF       ")
            lcd.cursor_pos = (1, 0)
            lcd.write_string("    Shutdown...     ")
            lcd.backlight_enabled = False
    print("\nHardware controller stopped.")
    sys.exit(0)


def main():
    global lcd

    print("CHRONOSURF - Hardware Controller")

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    read_state()

    if HW_AVAILABLE:
        print("Initializing hardware...")
        lcd = setup_display()

        show_boot_screen()
        time.sleep(2)

        buzzer_setup()
        setup_gpio()
        print("GPIO, LCD and buzzer initialized.")
    else:
        print("Simulation mode (no hardware detected)")
        lcd = None

    update_display()

    poll_thread = threading.Thread(target=poll_state_changes, daemon=True)
    poll_thread.start()

    print(f"Running. Year: {current_year}, Active surfers: {active_count}")
    print("Rotate encoder = select default year, press = confirm.")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
