"""
CHRONOSURF - RGB LED Controller

Common-Cathode RGB LED an GPIO 23 (R), 24 (G), 25 (B).
GND der LED an einen GND-Pin.

Farben pro Epoche:
  90s:    Gruen  (Phosphor-Terminal)
  Y2K:    Cyan   (Matrix-Blau)
  Web2.0: Orange (warm)
  Social: Blau   (Twitter-Blau)
  Modern: Weiss  (clean)

Effekte:
  - Statisch: Epochenfarbe
  - Pulsieren: Surfer verbunden
  - Flash: Neuer Connect / Disconnect
  - Fade: Jahreswechsel
"""

import time
import threading

try:
    import RPi.GPIO as GPIO
    HW_AVAILABLE = True
except ImportError:
    HW_AVAILABLE = False

# GPIO Pins (BCM)
PIN_R = 23
PIN_G = 24
PIN_B = 25

# PWM Frequenz
PWM_FREQ = 200

# Farben pro Epoche: (R%, G%, B%) - Werte 0-100
EPOCH_COLORS = {
    "90s":    (0, 100, 25),    # Phosphor-Gruen
    "Y2K":    (0, 80, 100),    # Cyan
    "WEB2.0": (100, 55, 0),    # Orange
    "SOCIAL": (10, 50, 100),   # Blau
    "MODERN": (80, 90, 100),   # Weiss-Blau
}

# Spezial-Farben
COLOR_OFF     = (0, 0, 0)
COLOR_CONNECT = (0, 100, 0)     # Gruen Flash
COLOR_DISCONNECT = (100, 0, 0)  # Rot Flash
COLOR_BOOT    = (0, 0, 100)     # Blau

_pwm_r = None
_pwm_g = None
_pwm_b = None
_current_color = COLOR_OFF
_pulse_thread = None
_pulse_running = False
_lock = threading.Lock()


def setup():
    """Initialisiert die RGB-LED Pins als PWM."""
    global _pwm_r, _pwm_g, _pwm_b
    if not HW_AVAILABLE:
        return

    GPIO.setup(PIN_R, GPIO.OUT)
    GPIO.setup(PIN_G, GPIO.OUT)
    GPIO.setup(PIN_B, GPIO.OUT)

    _pwm_r = GPIO.PWM(PIN_R, PWM_FREQ)
    _pwm_g = GPIO.PWM(PIN_G, PWM_FREQ)
    _pwm_b = GPIO.PWM(PIN_B, PWM_FREQ)

    _pwm_r.start(0)
    _pwm_g.start(0)
    _pwm_b.start(0)


def _set_raw(r, g, b):
    """Setzt die PWM-Werte direkt (0-100)."""
    if not HW_AVAILABLE:
        return
    if _pwm_r:
        _pwm_r.ChangeDutyCycle(r)
    if _pwm_g:
        _pwm_g.ChangeDutyCycle(g)
    if _pwm_b:
        _pwm_b.ChangeDutyCycle(b)


def set_color(r, g, b):
    """Setzt eine statische Farbe."""
    global _current_color
    _stop_pulse()
    _current_color = (r, g, b)
    _set_raw(r, g, b)
    if not HW_AVAILABLE:
        print(f"  [LED] R={r:>3d} G={g:>3d} B={b:>3d}")


def set_epoch(epoch_name):
    """Setzt die Farbe passend zur Epoche."""
    color = EPOCH_COLORS.get(epoch_name, EPOCH_COLORS["MODERN"])
    set_color(*color)


def off():
    """LED aus."""
    set_color(0, 0, 0)


# --- Effekte ---

def flash(r, g, b, times=3, on_time=0.1, off_time=0.1):
    """Blitzt eine Farbe mehrmals auf, kehrt dann zur vorherigen zurueck."""
    _stop_pulse()
    prev = _current_color

    def _flash():
        for _ in range(times):
            _set_raw(r, g, b)
            time.sleep(on_time)
            _set_raw(0, 0, 0)
            time.sleep(off_time)
        # Vorherige Farbe wiederherstellen
        _set_raw(*prev)

    t = threading.Thread(target=_flash, daemon=True)
    t.start()


def flash_connect():
    """Gruenes Blitzen bei neuem Surfer."""
    flash(*COLOR_CONNECT, times=4, on_time=0.12, off_time=0.08)


def flash_disconnect():
    """Rotes Blitzen bei Disconnect."""
    flash(*COLOR_DISCONNECT, times=2, on_time=0.2, off_time=0.15)


def _stop_pulse():
    """Stoppt den Puls-Effekt."""
    global _pulse_running
    _pulse_running = False


def start_pulse(r, g, b, speed=1.0):
    """Pulsiert eine Farbe (fuer aktive Verbindung)."""
    global _pulse_running, _pulse_thread, _current_color

    _stop_pulse()
    if _pulse_thread and _pulse_thread.is_alive():
        _pulse_thread.join(timeout=0.5)

    _current_color = (r, g, b)
    _pulse_running = True

    def _pulse():
        import math
        t = 0
        while _pulse_running:
            # Sinusfoermiges Pulsieren: 40% bis 100% Helligkeit
            brightness = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * speed))
            _set_raw(
                r * brightness,
                g * brightness,
                b * brightness,
            )
            t += 0.05
            time.sleep(0.03)
        # Auf statische Farbe zuruecksetzen
        _set_raw(*_current_color)

    _pulse_thread = threading.Thread(target=_pulse, daemon=True)
    _pulse_thread.start()


def pulse_epoch(epoch_name, speed=1.0):
    """Pulsiert in der Epochenfarbe."""
    color = EPOCH_COLORS.get(epoch_name, EPOCH_COLORS["MODERN"])
    start_pulse(*color, speed=speed)


def fade_to(r, g, b, duration=0.5, steps=20):
    """Weiches Ueberblenden zur neuen Farbe."""
    _stop_pulse()
    prev = _current_color

    def _fade():
        global _current_color
        for i in range(steps + 1):
            t = i / steps
            cr = prev[0] + (r - prev[0]) * t
            cg = prev[1] + (g - prev[1]) * t
            cb = prev[2] + (b - prev[2]) * t
            _set_raw(cr, cg, cb)
            time.sleep(duration / steps)
        _current_color = (r, g, b)

    t = threading.Thread(target=_fade, daemon=True)
    t.start()


def fade_to_epoch(epoch_name, duration=0.5):
    """Weiches Ueberblenden zur Epochenfarbe."""
    color = EPOCH_COLORS.get(epoch_name, EPOCH_COLORS["MODERN"])
    fade_to(*color, duration=duration)


def boot_animation():
    """LED-Animation waehrend Boot-Sequenz."""
    if not HW_AVAILABLE:
        print("  [LED] Boot animation")
        return

    # Blau aufblitzen
    _set_raw(*COLOR_BOOT)
    time.sleep(0.3)

    # Durch alle Epochenfarben faden
    for epoch in ["90s", "Y2K", "WEB2.0", "SOCIAL", "MODERN"]:
        color = EPOCH_COLORS[epoch]
        _set_raw(*color)
        time.sleep(0.25)

    # Kurz aus
    _set_raw(0, 0, 0)
    time.sleep(0.1)


def cleanup():
    """Aufraeumen."""
    _stop_pulse()
    if HW_AVAILABLE:
        _set_raw(0, 0, 0)
        if _pwm_r:
            _pwm_r.stop()
        if _pwm_g:
            _pwm_g.stop()
        if _pwm_b:
            _pwm_b.stop()
