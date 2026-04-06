#!/usr/bin/env python3
"""
CHRONOSURF - Hardware Controller

Steuert den Rotary Encoder, I2C LCD 20x4 und Button
zur lokalen Jahresauswahl am Geraet.

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
PIN_CLK = 17    # Rotary Encoder CLK
PIN_DT = 18     # Rotary Encoder DT
PIN_BTN = 27    # Rotary Encoder Button

# LCD: I2C address (0x27 fuer PCF8574, 0x3F fuer PCF8574A)
LCD_I2C_ADDR = 0x27
LCD_I2C_PORT = 1
LCD_COLS = 20
LCD_ROWS = 4

# Custom characters for the LCD
# Block/bar character for the timeline
CHAR_BLOCK = (0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F)
CHAR_HALF  = (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10)
CHAR_ARROW_R = (0x00, 0x04, 0x06, 0x1F, 0x1F, 0x06, 0x04, 0x00)
CHAR_ARROW_L = (0x00, 0x04, 0x0C, 0x1F, 0x1F, 0x0C, 0x04, 0x00)
CHAR_CONN   = (0x00, 0x0E, 0x11, 0x04, 0x0A, 0x00, 0x04, 0x00)  # WiFi icon

# Zustand
current_year = DEFAULT_YEAR
is_active = False
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

    GPIO.add_event_detect(PIN_CLK, GPIO.BOTH, callback=rotary_callback, bouncetime=2)
    GPIO.add_event_detect(PIN_BTN, GPIO.FALLING, callback=button_callback, bouncetime=300)


def rotary_callback(channel):
    """Callback fuer Rotary Encoder Drehung."""
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
    """Callback fuer Button-Druck: Aktiviert/deaktiviert die Zeitreise."""
    global is_active

    time.sleep(0.05)
    if GPIO.input(PIN_BTN) != GPIO.LOW:
        return

    is_active = not is_active
    set_state(current_year, is_active)
    print(f"{'CONNECTED' if is_active else 'DISCONNECTED'}: Year {current_year}")

    if is_active:
        play_async(play_dialup_sound)
        show_connecting_animation()
    else:
        play_async(play_disconnect_sound)
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
        # Fallback: versuche alternative Adresse (PCF8574A)
        display = CharLCD(
            i2c_expander='PCF8574',
            address=0x3F,
            port=LCD_I2C_PORT,
            cols=LCD_COLS,
            rows=LCD_ROWS,
            dotsize=8,
            auto_linebreaks=False,
        )

    # Custom Characters laden
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
    # Position berechnen (0-18, da wir < und > brauchen)
    pos = int(((year - MIN_YEAR) / (MAX_YEAR - MIN_YEAR)) * 18)
    bar = "\x03"  # Left arrow
    for i in range(18):
        if i == pos:
            bar += "\x00"  # Filled block = current position
        elif i < pos:
            bar += "-"
        else:
            bar += "\xA5"  # Middle dot
    bar += "\x02"  # Right arrow
    return bar


def update_display():
    """Aktualisiert die LCD-Anzeige."""
    if not HW_AVAILABLE:
        epoch = get_epoch_name(current_year)
        bar = f"[{'=' * ((current_year - MIN_YEAR) * 18 // (MAX_YEAR - MIN_YEAR))}>"
        bar = bar.ljust(20, '-') + ']'
        print(f"\r[LCD]  CHRONOSURF          ", end="")
        print(f"\n       <<< {current_year} >>> {epoch:>6s}", end="")
        print(f"\n       {bar}", end="")
        if is_active:
            print(f"\n       * CONNECTED         ", end="", flush=True)
        else:
            print(f"\n         Press to dial     ", end="", flush=True)
        print("\033[4A", end="")  # Move cursor back up
        return

    with display_lock:
        try:
            epoch = get_epoch_name(current_year)
            timeline = _timeline_bar(current_year)

            # Zeile 1: Header
            line1 = "  CHRONOSURF".ljust(LCD_COLS)

            # Zeile 2: Jahr + Epoche
            line2 = f"  <<< {current_year} >>> {epoch:>6s}".ljust(LCD_COLS)

            # Zeile 3: Timeline-Balken
            line3 = timeline

            # Zeile 4: Status
            if is_active:
                line4 = " \x04 CONNECTED".ljust(LCD_COLS)
            else:
                line4 = "   Press to dial".ljust(LCD_COLS)

            lcd.home()
            lcd.write_string(line1)
            lcd.cursor_pos = (1, 0)
            lcd.write_string(line2)
            lcd.cursor_pos = (2, 0)
            lcd.write_string(line3)
            lcd.cursor_pos = (3, 0)
            lcd.write_string(line4)

        except Exception as e:
            print(f"LCD error: {e}")


def _lcd_write_line(row, text):
    """Schreibt eine Zeile auf das LCD (padded auf 20 Zeichen)."""
    lcd.cursor_pos = (row, 0)
    lcd.write_string(text[:LCD_COLS].ljust(LCD_COLS))


def _lcd_scroll_up(new_line):
    """Scrollt alle Zeilen eins hoch und schreibt neue Zeile unten."""
    # LCD hat kein Hardware-Scroll, also manuell:
    # Wir nutzen einen Puffer
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

    # Obere Zeilen neu zeichnen
    for i in range(LCD_ROWS - 1):
        _lcd_write_line(i, _lcd_scroll_up._buf[i])

    # Letzte Zeile zeichenweise tippen
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

    # LCD Puffer initialisieren
    _lcd_scroll_up._buf = [''] * LCD_ROWS
    lcd.clear()

    # Boot-Sequenz - jede Zeile scrollt hoch wie ein Terminal
    boot_sequence = [
        # (text, mode, delay_after)
        # mode: 'type' = zeichenweise tippen, 'line' = sofort einblenden
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


def show_connecting_animation():
    """Terminal-style Verbindungsanimation passend zum Web-UI Warp."""
    if not HW_AVAILABLE or lcd is None:
        return

    with display_lock:
        lcd.clear()

        # Phase 1: Dial sequence
        _lcd_write_line(0, f"DIAL IN >>> {current_year}")
        _lcd_write_line(1, "")
        _lcd_write_line(2, "")
        _lcd_write_line(3, "")
        time.sleep(0.3)

        # Phase 2: Status messages (wie im Web-UI Warp-Overlay)
        status_msgs = [
            "Resolving coords...",
            "Connecting to node..",
            "Baud rate: 56000",
            "Loading epoch data..",
            "Rebuilding DOM...",
        ]

        for i, msg in enumerate(status_msgs):
            _lcd_write_line(1, msg)

            # Progress bar auf Zeile 2
            filled = int((i + 1) / len(status_msgs) * LCD_COLS)
            bar = "\x00" * filled + " " * (LCD_COLS - filled)
            _lcd_write_line(2, bar)

            pct = int((i + 1) / len(status_msgs) * 100)
            _lcd_write_line(3, f"          [{pct:>3d}%]")
            time.sleep(0.35)

        # Phase 3: Connected!
        _lcd_write_line(0, f"  >>> {current_year} <<<")
        _lcd_write_line(1, "")
        bar_full = "\x00" * LCD_COLS
        _lcd_write_line(2, bar_full)
        _lcd_write_line(3, "  LINK ESTABLISHED  ")
        time.sleep(0.8)


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
                        if is_active != old_active:
                            if is_active:
                                play_async(play_dialup_sound)
                            else:
                                play_async(play_disconnect_sound)
        except Exception:
            pass
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

    get_state()

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

    print(f"Running. Year: {current_year}, Active: {is_active}")
    print("Rotate encoder to select year, press to connect.")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
