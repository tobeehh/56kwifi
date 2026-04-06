#!/usr/bin/env python3
"""
CHRONOSURF - Hardware Controller

Zwei Rotary Encoder mit integriertem Pushbutton:
  - Encoder 1 (YEAR):  CLK=GPIO17, DT=GPIO18, BTN=GPIO27
  - Encoder 2 (SPEED): CLK=GPIO5,  DT=GPIO6,  BTN=GPIO13
  - I2C LCD 20x4 (HD44780 + PCF8574): I2C Bus 1, Adresse 0x27
  - Passiver Buzzer: GPIO22
  - RGB LED (common cathode): R=GPIO23, G=GPIO24, B=GPIO25

Encoder 1 stellt das Jahr ein (1996-2025), Button bestaetigt.
Encoder 2 stellt die Geschwindigkeit ein (56k..full), Button bestaetigt.
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
from rgb_led import (
    setup as led_setup, set_epoch as led_set_epoch,
    pulse_epoch as led_pulse_epoch, fade_to_epoch as led_fade_epoch,
    flash_connect as led_flash_connect, flash_disconnect as led_flash_disconnect,
    boot_animation as led_boot, off as led_off, cleanup as led_cleanup
)

# Konfiguration
STATE_FILE = Path("/tmp/chronosurf_state.json")
MIN_YEAR = 1996
MAX_YEAR = 2025
DEFAULT_YEAR = 1999

# --- GPIO Pins (BCM) ---
# Encoder 1: Jahr
PIN_YEAR_CLK = 17
PIN_YEAR_DT  = 18
PIN_YEAR_BTN = 27

# Encoder 2: Speed
PIN_SPEED_CLK = 5
PIN_SPEED_DT  = 6
PIN_SPEED_BTN = 13

# Buzzer
PIN_BUZZER = 22

# LCD
LCD_I2C_ADDR = 0x27
LCD_I2C_PORT = 1
LCD_COLS = 20
LCD_ROWS = 4

# Speed-Presets (gleiche Reihenfolge wie in throttle.py)
SPEED_LIST = [
    ("56k",    "56k Modem",    56),
    ("isdn",   "ISDN 128k",   128),
    ("dsl384", "DSL 384k",    384),
    ("dsl1",   "DSL 1000",    1000),
    ("dsl6",   "DSL 6000",    6000),
    ("dsl16",  "DSL 16000",   16000),
    ("full",   "FULL SPEED",  0),
]

# Custom characters
CHAR_BLOCK   = (0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F)
CHAR_ARROW_R = (0x00, 0x04, 0x06, 0x1F, 0x1F, 0x06, 0x04, 0x00)
CHAR_ARROW_L = (0x00, 0x04, 0x0C, 0x1F, 0x1F, 0x0C, 0x04, 0x00)
CHAR_CONN    = (0x00, 0x0E, 0x11, 0x04, 0x0A, 0x00, 0x04, 0x00)
CHAR_GAUGE   = (0x00, 0x0E, 0x15, 0x17, 0x11, 0x0E, 0x00, 0x00)  # Speed gauge

# Zustand
current_year = DEFAULT_YEAR
current_speed_idx = 0  # Index in SPEED_LIST
active_count = 0
active_clients = []
display_lock = threading.Lock()
last_year_clk = None
last_speed_clk = None
lcd = None


def get_epoch_name(year):
    if year <= 1999: return "90s"
    if year <= 2004: return "Y2K"
    if year <= 2009: return "WEB2.0"
    if year <= 2015: return "SOCIAL"
    return "MODERN"


def get_speed_key():
    return SPEED_LIST[current_speed_idx][0]


def get_speed_label():
    return SPEED_LIST[current_speed_idx][1]


def get_speed_kbit():
    return SPEED_LIST[current_speed_idx][2]


# --- State I/O ---

def read_state():
    """Liest das per-MAC State-File."""
    global current_year, current_speed_idx, active_count, active_clients
    try:
        data = json.loads(STATE_FILE.read_text())
        current_year = data.get("global_year", DEFAULT_YEAR)

        # Global speed aus State lesen
        global_speed = data.get("global_speed", "56k")
        for i, (key, _, _) in enumerate(SPEED_LIST):
            if key == global_speed:
                current_speed_idx = i
                break

        clients = data.get("clients", {})
        active_clients = []
        for mac, info in clients.items():
            if info.get("active", False):
                active_clients.append({
                    "year": info.get("year", DEFAULT_YEAR),
                    "id": mac[-5:],
                    "speed": info.get("speed", "full"),
                })
        active_count = len(active_clients)

    except (FileNotFoundError, json.JSONDecodeError):
        current_year = DEFAULT_YEAR
        current_speed_idx = 0
        active_count = 0
        active_clients = []


def write_global_state():
    """Schreibt global_year und global_speed in die State-Datei."""
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
        else:
            data = {"clients": {}, "global_year": DEFAULT_YEAR}
    except (json.JSONDecodeError, FileNotFoundError):
        data = {"clients": {}, "global_year": DEFAULT_YEAR}

    data["global_year"] = current_year
    data["global_speed"] = get_speed_key()
    STATE_FILE.write_text(json.dumps(data, indent=2))


# --- GPIO Setup ---

def setup_gpio():
    global last_year_clk, last_speed_clk

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Encoder 1: Year
    GPIO.setup(PIN_YEAR_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_YEAR_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_YEAR_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Encoder 2: Speed
    GPIO.setup(PIN_SPEED_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_SPEED_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_SPEED_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    last_year_clk = GPIO.input(PIN_YEAR_CLK)
    last_speed_clk = GPIO.input(PIN_SPEED_CLK)

    # Interrupts
    GPIO.add_event_detect(PIN_YEAR_CLK, GPIO.BOTH, callback=year_rotary_cb, bouncetime=2)
    GPIO.add_event_detect(PIN_YEAR_BTN, GPIO.FALLING, callback=year_button_cb, bouncetime=300)
    GPIO.add_event_detect(PIN_SPEED_CLK, GPIO.BOTH, callback=speed_rotary_cb, bouncetime=2)
    GPIO.add_event_detect(PIN_SPEED_BTN, GPIO.FALLING, callback=speed_button_cb, bouncetime=300)


# --- Encoder 1: Year ---

def year_rotary_cb(channel):
    global current_year, last_year_clk

    clk = GPIO.input(PIN_YEAR_CLK)
    dt = GPIO.input(PIN_YEAR_DT)

    if clk != last_year_clk:
        if dt != clk:
            current_year = min(MAX_YEAR, current_year + 1)
        else:
            current_year = max(MIN_YEAR, current_year - 1)
        last_year_clk = clk
        play_click_sound()
        led_fade_epoch(get_epoch_name(current_year), duration=0.2)
        update_display()


def year_button_cb(channel):
    time.sleep(0.05)
    if GPIO.input(PIN_YEAR_BTN) != GPIO.LOW:
        return

    write_global_state()
    print(f"YEAR SET: {current_year}")

    if HW_AVAILABLE and lcd is not None:
        with display_lock:
            _lcd_write_line(3, f" \x04 YEAR SET: {current_year}")
        time.sleep(1)
    update_display()


# --- Encoder 2: Speed ---

def speed_rotary_cb(channel):
    global current_speed_idx, last_speed_clk

    clk = GPIO.input(PIN_SPEED_CLK)
    dt = GPIO.input(PIN_SPEED_DT)

    if clk != last_speed_clk:
        if dt != clk:
            current_speed_idx = min(len(SPEED_LIST) - 1, current_speed_idx + 1)
        else:
            current_speed_idx = max(0, current_speed_idx - 1)
        last_speed_clk = clk
        play_click_sound()
        update_display()


def speed_button_cb(channel):
    time.sleep(0.05)
    if GPIO.input(PIN_SPEED_BTN) != GPIO.LOW:
        return

    write_global_state()
    print(f"SPEED SET: {get_speed_label()}")

    if HW_AVAILABLE and lcd is not None:
        with display_lock:
            _lcd_write_line(3, f" \x04 SPEED: {get_speed_label()}")
        time.sleep(1)
    update_display()


# --- Display ---

def setup_display():
    try:
        display = CharLCD(
            i2c_expander='PCF8574', address=LCD_I2C_ADDR,
            port=LCD_I2C_PORT, cols=LCD_COLS, rows=LCD_ROWS,
            dotsize=8, auto_linebreaks=False,
        )
    except Exception:
        display = CharLCD(
            i2c_expander='PCF8574', address=0x3F,
            port=LCD_I2C_PORT, cols=LCD_COLS, rows=LCD_ROWS,
            dotsize=8, auto_linebreaks=False,
        )

    display.create_char(0, CHAR_BLOCK)
    display.create_char(1, CHAR_ARROW_R)
    display.create_char(2, CHAR_ARROW_L)
    display.create_char(3, CHAR_CONN)
    display.create_char(4, CHAR_GAUGE)

    display.backlight_enabled = True
    display.clear()
    return display


def _timeline_bar(year):
    pos = int(((year - MIN_YEAR) / (MAX_YEAR - MIN_YEAR)) * 18)
    bar = "\x02"
    for i in range(18):
        bar += "\x00" if i == pos else ("-" if i < pos else "\xA5")
    bar += "\x01"
    return bar


def _speed_bar():
    """Erzeugt einen Speed-Balken mit Marker."""
    pos = current_speed_idx
    total = len(SPEED_LIST) - 1
    # 12 Zeichen fuer den Balken
    bar_len = 12
    marker_pos = int((pos / total) * (bar_len - 1)) if total > 0 else 0
    bar = ""
    for i in range(bar_len):
        bar += "\x00" if i == marker_pos else ("-" if i < marker_pos else "\xA5")
    return bar


def update_display():
    if not HW_AVAILABLE:
        epoch = get_epoch_name(current_year)
        spd = get_speed_label()
        print(f"\r[LCD] CHRONOSURF  \x04{active_count}", end="")
        print(f"\n      {current_year} {epoch:<6s}  {spd:>8s}", end="")
        bar_pos = (current_year - MIN_YEAR) * 18 // (MAX_YEAR - MIN_YEAR)
        bar = f"[{'=' * bar_pos}>{'-' * (18 - bar_pos)}]"
        print(f"\n      {bar}", end="")
        if active_count > 0:
            surfers = " ".join(f"{c['id'][-2:]}>{str(c['year'])[2:]}" for c in active_clients[:3])
            print(f"\n      {surfers}", end="", flush=True)
        else:
            print(f"\n      Waiting for surfers", end="", flush=True)
        print("\033[4A", end="")
        return

    with display_lock:
        try:
            epoch = get_epoch_name(current_year)
            spd_label = get_speed_label()
            kbit = get_speed_kbit()
            timeline = _timeline_bar(current_year)

            # Zeile 1: Jahr + Epoche + Surfer-Count
            if active_count > 0:
                line1 = f"{current_year} {epoch:<6s} \x03{active_count} online"
            else:
                line1 = f"{current_year} {epoch:<6s}  CHRNOSURF"

            # Zeile 2: Timeline
            line2 = timeline

            # Zeile 3: Speed-Anzeige
            spd_bar = _speed_bar()
            if kbit > 0:
                kbit_str = f"{kbit}k" if kbit < 1000 else f"{kbit // 1000}M"
                line3 = f"\x04{spd_bar} {kbit_str:>4s}"
            else:
                line3 = f"\x04{spd_bar}  MAX"

            # Zeile 4: Aktive Surfer oder Label
            if active_count > 0:
                parts = []
                for c in active_clients[:3]:
                    yr_short = str(c["year"])[2:]
                    spd = c.get("speed", "full")
                    if spd == "full":
                        parts.append(f"{c['id'][-2:]}>{yr_short}")
                    else:
                        parts.append(f"{c['id'][-2:]}>{yr_short}@{spd}")
                line4 = " ".join(parts)
            else:
                line4 = " Surf the Timeline"

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


# --- LCD Helpers ---

def _lcd_write_line(row, text):
    lcd.cursor_pos = (row, 0)
    lcd.write_string(text[:LCD_COLS].ljust(LCD_COLS))


def _lcd_scroll_up(new_line):
    _lcd_scroll_up._buf = getattr(_lcd_scroll_up, '_buf', [''] * LCD_ROWS)
    _lcd_scroll_up._buf.pop(0)
    _lcd_scroll_up._buf.append(new_line)
    for i, line in enumerate(_lcd_scroll_up._buf):
        _lcd_write_line(i, line)


def _boot_type(text, delay=0.04):
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
    if not HW_AVAILABLE:
        for line in [
            "CHRONOSURF BIOS 1.0", "(c) Temporal Net Inc", "",
            "Detecting HW...",
            " CPU: BCM2837  [OK]", " RAM: 1024MB   [OK]",
            " ETH: 100Mbps  [OK]", " WLAN: AP mode [OK]",
            " I2C: LCD@0x27 [OK]", " ENC1: Year    [OK]",
            " ENC2: Speed   [OK]", " GPIO: Buzzer  [OK]", "",
            "Init temporal sys...", " Wayback: CONNECTED",
            " Range: 1996 - 2025", "",
            "> READY.", "> SURF THE TIMELINE.",
        ]:
            print(f"[BOOT] {line}")
            time.sleep(0.06)
        return

    _lcd_scroll_up._buf = [''] * LCD_ROWS
    lcd.clear()

    for text, mode, delay in [
        ("CHRONOSURF BIOS 1.0", "type", 0.3),
        ("(c)Temporal Net Inc.", "line", 0.4),
        ("", "line", 0.2),
        ("Detecting HW...", "type", 0.3),
        (" CPU: BCM2837  [OK]", "line", 0.15),
        (" RAM: 1024MB   [OK]", "line", 0.1),
        (" ETH: 100Mbps  [OK]", "line", 0.15),
        (" WLAN: AP mode [OK]", "line", 0.15),
        (" I2C: LCD@0x27 [OK]", "line", 0.1),
        (" ENC1: Year    [OK]", "line", 0.1),
        (" ENC2: Speed   [OK]", "line", 0.1),
        (" GPIO: Buzzer  [OK]", "line", 0.15),
        ("", "line", 0.2),
        ("Init temporal sys..", "type", 0.3),
        (" Wayback: CONNECTED", "line", 0.2),
        (" 735 billion pages", "line", 0.15),
        (" Range: 1996 - 2025", "line", 0.2),
        ("", "line", 0.15),
        ("> READY.", "type", 0.3),
        (">SURF THE TIMELINE.", "type", 0.5),
    ]:
        if mode == "type":
            _boot_type(text, delay=0.03)
        else:
            _lcd_scroll_up(text)
        time.sleep(delay)


# --- Surfer Events ---

def show_surfer_connected(mac_short, year):
    if not HW_AVAILABLE or lcd is None:
        print(f"[LCD] SURFER CONNECTED: {mac_short} -> {year}")
        return
    with display_lock:
        _lcd_write_line(3, f"\x03 {mac_short} > {year} ONLINE")
    time.sleep(1.5)
    update_display()


def show_surfer_disconnected(mac_short, year):
    if not HW_AVAILABLE or lcd is None:
        print(f"[LCD] SURFER DISCONNECTED: {mac_short}")
        return
    with display_lock:
        _lcd_write_line(3, f"  {mac_short} OFFLINE")
    time.sleep(1)
    update_display()


# --- State Polling ---

def poll_state_changes():
    global active_count, active_clients, current_year
    last_mtime = 0
    prev_active_macs = set()

    while True:
        try:
            if STATE_FILE.exists():
                mtime = STATE_FILE.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    old_active_macs = prev_active_macs.copy()
                    old_year = current_year

                    read_state()

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

                    new_connections = now_active_macs - old_active_macs
                    lost_connections = old_active_macs - now_active_macs

                    for mac in new_connections:
                        year = mac_year_map.get(mac, current_year)
                        led_flash_connect()
                        play_async(play_dialup_sound)
                        show_surfer_connected(mac[-5:], year)

                    for mac in lost_connections:
                        led_flash_disconnect()
                        play_async(play_disconnect_sound)
                        show_surfer_disconnected(mac[-5:], current_year)

                    prev_active_macs = now_active_macs

                    # LED-Status aktualisieren
                    epoch = get_epoch_name(current_year)
                    if active_count > 0:
                        led_pulse_epoch(epoch, speed=1.5)
                    else:
                        led_set_epoch(epoch)

                    if not new_connections and not lost_connections:
                        if current_year != old_year or active_count != len(old_active_macs):
                            update_display()

        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(1)


# --- Lifecycle ---

def cleanup(signum=None, frame=None):
    led_cleanup()
    buzzer_cleanup()
    if HW_AVAILABLE:
        GPIO.cleanup()
        if lcd is not None:
            lcd.clear()
            _lcd_write_line(0, "   CHRONOSURF")
            _lcd_write_line(1, "    Shutdown...")
            lcd.backlight_enabled = False
    print("\nHardware controller stopped.")
    sys.exit(0)


def main():
    global lcd

    print("CHRONOSURF - Hardware Controller")
    print("  Encoder 1 (YEAR):  GPIO17/18/27")
    print("  Encoder 2 (SPEED): GPIO5/6/13")

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    read_state()

    if HW_AVAILABLE:
        print("Initializing hardware...")
        lcd = setup_display()
        led_setup()
        led_boot()
        show_boot_screen()
        time.sleep(2)
        buzzer_setup()
        setup_gpio()
        led_set_epoch(get_epoch_name(current_year))
        print("GPIO, LCD and buzzer initialized.")
    else:
        print("Simulation mode (no hardware detected)")
        lcd = None

    update_display()

    poll_thread = threading.Thread(target=poll_state_changes, daemon=True)
    poll_thread.start()

    print(f"Running. Year: {current_year}, Speed: {get_speed_label()}, Surfers: {active_count}")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
