#!/usr/bin/env python3
"""
CHRONOSURF - Hardware Controller

Zwei Rotary Encoder mit integriertem Pushbutton:
  - Rotary Encoder (YEAR): CLK=GPIO18, DT=GPIO17, BTN=GPIO27
  - Rotary Encoder (INFO): CLK=GPIO5,  DT=GPIO6,  BTN=GPIO13
  - I2C LCD 20x4 (HD44780 + PCF8574): I2C Bus 1, Adresse 0x27
  - Passiver Buzzer: GPIO22

Der zweite Encoder schaltet durch System-Info-Screens:
  system  - CPU Load, RAM, Temperatur
  network - Ethernet/WiFi IPs
  clients - Aktive Surfer mit ihrem Jahr
  uptime  - System- und Controller-Uptime
  wayback - Wayback Machine Info

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

# Konfiguration
STATE_FILE = Path("/tmp/chronosurf_state.json")
MIN_YEAR = 1996
MAX_YEAR = 2025
DEFAULT_YEAR = 1999

# --- GPIO Pins (BCM) ---
# Encoder 1: Jahr
PIN_YEAR_CLK = 18
PIN_YEAR_DT  = 17
PIN_YEAR_BTN = 27

# Buzzer
PIN_BUZZER = 22

# Info Encoder (zweiter Encoder fuer System-Infos)
PIN_INFO_CLK = 5
PIN_INFO_DT  = 6
PIN_INFO_BTN = 13

# LCD
LCD_I2C_ADDR = 0x27
LCD_I2C_PORT = 1
LCD_COLS = 20
LCD_ROWS = 4

# Custom characters
CHAR_BLOCK   = (0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F, 0x1F)
CHAR_ARROW_R = (0x00, 0x04, 0x06, 0x1F, 0x1F, 0x06, 0x04, 0x00)
CHAR_ARROW_L = (0x00, 0x04, 0x0C, 0x1F, 0x1F, 0x0C, 0x04, 0x00)
CHAR_CONN    = (0x00, 0x0E, 0x11, 0x04, 0x0A, 0x00, 0x04, 0x00)
CHAR_GAUGE   = (0x00, 0x0E, 0x15, 0x17, 0x11, 0x0E, 0x00, 0x00)  # Speed gauge

# Info-Modus
INFO_SCREENS = ["system", "network", "clients", "uptime", "wayback"]
info_mode_active = False
info_screen_idx = 0

# Zustand
current_year = DEFAULT_YEAR
active_count = 0
active_clients = []
display_lock = threading.Lock()
last_year_clk = None
last_info_clk = None
boot_time = time.time()
lcd = None


def get_epoch_name(year):
    if year <= 1999: return "90s"
    if year <= 2004: return "Y2K"
    if year <= 2009: return "WEB2.0"
    if year <= 2015: return "SOCIAL"
    return "MODERN"


# --- State I/O ---

def read_state():
    """Liest das per-MAC State-File."""
    global current_year, active_count, active_clients
    try:
        data = json.loads(STATE_FILE.read_text())
        current_year = data.get("global_year", DEFAULT_YEAR)

        clients = data.get("clients", {})
        active_clients = []
        for mac, info in clients.items():
            if info.get("active", False):
                active_clients.append({
                    "year": info.get("year", DEFAULT_YEAR),
                    "id": mac[-5:],
                })
        active_count = len(active_clients)

    except (FileNotFoundError, json.JSONDecodeError):
        current_year = DEFAULT_YEAR
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
    STATE_FILE.write_text(json.dumps(data, indent=2))


# --- GPIO Setup ---

def setup_gpio():
    global last_year_clk, last_info_clk

    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Year Encoder
    GPIO.setup(PIN_YEAR_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_YEAR_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_YEAR_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Info Encoder
    GPIO.setup(PIN_INFO_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_INFO_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_INFO_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    last_year_clk = GPIO.input(PIN_YEAR_CLK)
    last_info_clk = GPIO.input(PIN_INFO_CLK)


def poll_encoders():
    """Polling-Thread fuer beide Encoder und Buttons."""
    global current_year, last_year_clk, last_info_clk
    global info_mode_active, info_screen_idx

    last_year_btn = 1
    last_info_btn = 1

    while True:
        # --- Year Encoder ---
        clk = GPIO.input(PIN_YEAR_CLK)
        if clk != last_year_clk:
            last_year_clk = clk
            if clk == 0:
                dt = GPIO.input(PIN_YEAR_DT)
                if dt != clk:
                    current_year = min(MAX_YEAR, current_year + 1)
                else:
                    current_year = max(MIN_YEAR, current_year - 1)
                play_click_sound()
                # Jahreswechsel verlaesst den Info-Modus
                info_mode_active = False
                update_display()

        # --- Year Button: DIAL IN mit Modem-Sound ---
        btn = GPIO.input(PIN_YEAR_BTN)
        if btn == 0 and last_year_btn == 1:
            write_global_state()
            print(f"DIAL IN: {current_year}")
            # Modem-Sound + LCD-Animation
            play_async(play_dialup_sound)
            show_dialin_animation()
            update_display()
        last_year_btn = btn

        # --- Info Encoder ---
        clk = GPIO.input(PIN_INFO_CLK)
        if clk != last_info_clk:
            last_info_clk = clk
            if clk == 0:
                dt = GPIO.input(PIN_INFO_DT)
                info_mode_active = True
                if dt != clk:
                    info_screen_idx = (info_screen_idx + 1) % len(INFO_SCREENS)
                else:
                    info_screen_idx = (info_screen_idx - 1) % len(INFO_SCREENS)
                play_click_sound()
                update_display()

        # --- Info Button: togglet Info-Modus ---
        btn = GPIO.input(PIN_INFO_BTN)
        if btn == 0 and last_info_btn == 1:
            info_mode_active = not info_mode_active
            print(f"Info mode: {info_mode_active}")
            update_display()
        last_info_btn = btn

        time.sleep(0.001)


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


# --- Info-Modus: Screens ---

def _get_ip(iface):
    """Liest die IP-Adresse eines Interfaces."""
    try:
        import subprocess
        r = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", iface],
            capture_output=True, text=True, timeout=1
        )
        for line in r.stdout.split("\n"):
            if "inet " in line:
                return line.split("inet ")[1].split("/")[0]
    except Exception:
        pass
    return "---"


def _format_uptime(seconds):
    """Formatiert Sekunden als 'Xd Yh Zm'."""
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    m = int((seconds % 3600) // 60)
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _info_lines_system():
    """System-Info Screen."""
    try:
        with open("/proc/loadavg", "r") as f:
            load = f.read().split()[0]
    except Exception:
        load = "?"

    try:
        with open("/proc/meminfo", "r") as f:
            mem = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1])
        mem_used = (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) // 1024
        mem_total = mem.get("MemTotal", 0) // 1024
    except Exception:
        mem_used = mem_total = 0

    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = int(f.read().strip()) / 1000
    except Exception:
        temp = 0

    return [
        "[ SYSTEM ]",
        f"Load:  {load}",
        f"RAM:   {mem_used}/{mem_total}MB",
        f"Temp:  {temp:.1f}C",
    ]


def _info_lines_network():
    """Netzwerk-Info Screen."""
    eth = _get_ip("eth0")
    wlan = _get_ip("wlan0")
    return [
        "[ NETWORK ]",
        f"eth0:  {eth}",
        f"wlan0: {wlan}",
        f"SSID:  CHRONOSURF",
    ]


def _info_lines_clients():
    """Aktive Clients Screen."""
    lines = [f"[ SURFERS: {active_count} ]"]
    for c in active_clients[:3]:
        lines.append(f" {c['id']} > {c['year']}")
    while len(lines) < 4:
        lines.append("")
    return lines


def _info_lines_uptime():
    """Uptime Screen."""
    ctrl_up = _format_uptime(time.time() - boot_time)
    try:
        with open("/proc/uptime", "r") as f:
            sys_up = _format_uptime(float(f.read().split()[0]))
    except Exception:
        sys_up = "?"
    return [
        "[ UPTIME ]",
        f"System: {sys_up}",
        f"Ctrl:   {ctrl_up}",
        f"Boot:   OK",
    ]


def _info_lines_wayback():
    """Wayback Machine Info Screen."""
    return [
        "[ WAYBACK ]",
        "735+ billion pages",
        "Range: 1996-2025",
        "archive.org",
    ]


INFO_RENDERERS = {
    "system":   _info_lines_system,
    "network":  _info_lines_network,
    "clients":  _info_lines_clients,
    "uptime":   _info_lines_uptime,
    "wayback":  _info_lines_wayback,
}


def _render_info_screen():
    """Rendert den aktuellen Info-Screen auf das LCD."""
    screen_key = INFO_SCREENS[info_screen_idx]
    lines = INFO_RENDERERS[screen_key]()

    if not HW_AVAILABLE:
        print(f"\r[LCD INFO] {lines[0]}")
        for line in lines[1:]:
            print(f"           {line}")
        return

    with display_lock:
        try:
            for i in range(LCD_ROWS):
                text = lines[i] if i < len(lines) else ""
                lcd.cursor_pos = (i, 0)
                lcd.write_string(text[:LCD_COLS].ljust(LCD_COLS))
        except Exception as e:
            print(f"LCD error: {e}")


def update_display():
    # Im Info-Modus: anderen Renderer nutzen
    if info_mode_active:
        _render_info_screen()
        return

    if not HW_AVAILABLE:
        epoch = get_epoch_name(current_year)
        print(f"\r[LCD] CHRONOSURF  \x03{active_count}", end="")
        print(f"\n      {current_year} {epoch}", end="")
        bar_pos = (current_year - MIN_YEAR) * 18 // (MAX_YEAR - MIN_YEAR)
        bar = f"[{'=' * bar_pos}>{'-' * (18 - bar_pos)}]"
        print(f"\n      {bar}", end="")
        if active_count > 0:
            surfers = " ".join(f"{c['id'][-2:]}>{str(c['year'])[2:]}" for c in active_clients[:3])
            print(f"\n      {surfers}", end="", flush=True)
        else:
            print(f"\n      Surf the Timeline", end="", flush=True)
        print("\033[4A", end="")
        return

    with display_lock:
        try:
            epoch = get_epoch_name(current_year)
            timeline = _timeline_bar(current_year)

            # Zeile 1: Header + Surfer-Count
            if active_count > 0:
                line1 = f"CHRONOSURF \x03{active_count} online"
            else:
                line1 = "CHRONOSURF"

            # Zeile 2: Jahr + Epoche
            line2 = f"  <<< {current_year} >>> {epoch:>6s}"

            # Zeile 3: Timeline
            line3 = timeline

            # Zeile 4: Aktive Surfer oder Tagline
            if active_count > 0:
                parts = []
                for c in active_clients[:3]:
                    yr_short = str(c["year"])[2:]
                    parts.append(f"{c['id'][-2:]}>{yr_short}")
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

def show_dialin_animation():
    """Dial-In Animation wenn am Hardware-Encoder ein Jahr bestaetigt wird.
    Passend zum Modem-Sound - laeuft parallel ab."""
    if not HW_AVAILABLE or lcd is None:
        print(f"[LCD] DIAL IN >>> {current_year}")
        return

    with display_lock:
        lcd.clear()

        # Phase 1: Dial
        _lcd_write_line(0, f"DIAL IN >>> {current_year}")
        _lcd_write_line(1, "")
        _lcd_write_line(2, "")
        _lcd_write_line(3, "")
        time.sleep(0.3)

        # Phase 2: Status Messages (parallel zum Modem-Sound)
        status_msgs = [
            "Resolving coords...",
            "Connecting to node..",
            "Baud rate: 56000",
            "Loading epoch data..",
            "Rebuilding DOM...",
        ]

        for i, msg in enumerate(status_msgs):
            _lcd_write_line(1, msg)
            # Progress Bar
            filled = int((i + 1) / len(status_msgs) * LCD_COLS)
            bar = "\x00" * filled + " " * (LCD_COLS - filled)
            _lcd_write_line(2, bar)
            pct = int((i + 1) / len(status_msgs) * 100)
            _lcd_write_line(3, f"          [{pct:>3d}%]")
            time.sleep(0.55)  # Laenger damit Sound mithalten kann

        # Phase 3: Connected!
        _lcd_write_line(0, f"  >>> {current_year} <<<")
        _lcd_write_line(1, "")
        _lcd_write_line(2, "\x00" * LCD_COLS)
        _lcd_write_line(3, "  LINK ESTABLISHED  ")
        time.sleep(1.0)


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
    first_run = True  # Kein Sound beim ersten Einlesen

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

                    # Beim ersten Einlesen: nur State uebernehmen, keine Events
                    if first_run:
                        prev_active_macs = now_active_macs
                        first_run = False
                        update_display()
                        time.sleep(1)
                        continue

                    for mac in new_connections:
                        year = mac_year_map.get(mac, current_year)
                        play_async(play_dialup_sound)
                        show_surfer_connected(mac[-5:], year)

                    for mac in lost_connections:
                        play_async(play_disconnect_sound)
                        show_surfer_disconnected(mac[-5:], current_year)

                    prev_active_macs = now_active_macs

                    if not new_connections and not lost_connections:
                        if current_year != old_year or active_count != len(old_active_macs):
                            update_display()

        except Exception as e:
            print(f"Poll error: {e}")
        time.sleep(1)


# --- Lifecycle ---

def cleanup(signum=None, frame=None):
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
    print("  Encoder 1 (YEAR): GPIO18/17/27")
    print("  Encoder 2 (INFO): GPIO5/6/13")

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    read_state()

    if HW_AVAILABLE:
        print("Initializing hardware...")
        lcd = setup_display()
        show_boot_screen()
        time.sleep(2)
        setup_gpio()
        buzzer_setup()
        print("GPIO, LCD and buzzer initialized.")
    else:
        print("Simulation mode (no hardware detected)")
        lcd = None

    update_display()

    # State-Polling (Web-Portal Sync)
    state_thread = threading.Thread(target=poll_state_changes, daemon=True)
    state_thread.start()

    # Encoder-Polling (statt edge detection - kompatibel mit allen Kernels)
    if HW_AVAILABLE:
        encoder_thread = threading.Thread(target=poll_encoders, daemon=True)
        encoder_thread.start()
        print("Encoder polling started.")

    print(f"Running. Year: {current_year}, Surfers: {active_count}")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
