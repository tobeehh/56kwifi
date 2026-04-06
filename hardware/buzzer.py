#!/usr/bin/env python3
"""
CHRONOSURF - Modem-Sound Buzzer

Simuliert den klassischen 56k Modem-Einwahlsound ueber einen passiven Buzzer
per PWM auf GPIO 22.

Der Sound besteht aus den authentischen Phasen des V.90 Handshakes:
  1. Freizeichen (Dial Tone)
  2. DTMF-Waehltoene
  3. Klingeln (Ring)
  4. Antwort-Ton (Answer Tone, 2100 Hz)
  5. Handshake-Rauschen (schnelle Frequenzwechsel)
  6. Verbunden-Bestaetigung

Hardware: Passiver Buzzer an GPIO 22 (BCM)
"""

import time
import threading

try:
    import RPi.GPIO as GPIO
    HW_AVAILABLE = True
except ImportError:
    HW_AVAILABLE = False

# GPIO Pin fuer den Buzzer
PIN_BUZZER = 22

# PWM-Objekt
_pwm = None
_lock = threading.Lock()
_playing = False


def setup():
    """Initialisiert den Buzzer-Pin."""
    global _pwm
    if not HW_AVAILABLE:
        return
    GPIO.setup(PIN_BUZZER, GPIO.OUT)
    _pwm = GPIO.PWM(PIN_BUZZER, 440)


def _tone(freq, duration):
    """Spielt einen einzelnen Ton."""
    if not HW_AVAILABLE:
        # Simulation: Frequenz anzeigen
        print(f"  ~ {freq:>5} Hz  ({duration:.2f}s)")
        time.sleep(duration * 0.1)  # Simulation schneller
        return

    if freq == 0:
        _pwm.stop()
        time.sleep(duration)
    else:
        _pwm.ChangeFrequency(freq)
        _pwm.start(50)  # 50% Duty Cycle
        time.sleep(duration)
        _pwm.stop()


def _pause(duration):
    """Stille Pause."""
    if HW_AVAILABLE:
        _pwm.stop()
    time.sleep(duration if HW_AVAILABLE else duration * 0.1)


def play_dialup_sound():
    """
    Spielt den kompletten 56k Modem-Einwahlsound ab.

    Authentische Phasen des Handshakes:
    - Dial tone (350/440 Hz)
    - DTMF dialing
    - Ringing (440/480 Hz)
    - Answer tone (2100 Hz)
    - V.8 bis signal
    - Scrambled training (das ikonische "Rauschen")
    - Connected
    """
    global _playing

    with _lock:
        if _playing:
            return
        _playing = True

    try:
        if not HW_AVAILABLE:
            print("[Buzzer] === 56k Modem-Einwahl ===")

        # --- Phase 1: Freizeichen (Dial Tone) ---
        # Echtes Freizeichen: 350 + 440 Hz gleichzeitig
        # Mit einem Buzzer alternieren wir schnell
        for _ in range(8):
            _tone(350, 0.05)
            _tone(440, 0.05)

        _pause(0.2)

        # --- Phase 2: DTMF Waehltoene ---
        # Simuliert das Waehlen einer Telefonnummer
        dtmf_freqs = [
            (941, 1336),  # 0
            (697, 1209),  # 1
            (697, 1336),  # 2
            (697, 1477),  # 3
            (770, 1209),  # 4
            (770, 1336),  # 5
            (852, 1209),  # 7
            (852, 1477),  # 9
        ]
        for low, high in dtmf_freqs:
            # Schnelles Alternieren zwischen den zwei DTMF-Frequenzen
            for _ in range(3):
                _tone(low, 0.015)
                _tone(high, 0.015)
            _pause(0.04)

        _pause(0.3)

        # --- Phase 3: Klingeln (Ring) ---
        for _ in range(2):
            for _ in range(6):
                _tone(440, 0.04)
                _tone(480, 0.04)
            _pause(0.4)

        # --- Phase 4: Answer Tone (2100 Hz) ---
        # Der Antwort-Ton des entfernten Modems
        _tone(2100, 0.6)
        _pause(0.1)

        # --- Phase 5: V.8 Bis Signal ---
        # Kurze Tonfolge zur Protokoll-Aushandlung
        _tone(1800, 0.1)
        _pause(0.05)
        _tone(1800, 0.1)
        _pause(0.1)

        # --- Phase 6: Handshake / Training ---
        # DAS ikonische Modem-Rauschen
        # Schnelle Frequenzwechsel simulieren die Trainingssignale

        # Phase 6a: Carrier detect - aufsteigende Toene
        for freq in range(600, 2400, 100):
            _tone(freq, 0.02)

        # Phase 6b: Scrambled Binary - das "Kratzen"
        import random
        random.seed(42)  # Reproduzierbar
        for _ in range(40):
            freq = random.choice([980, 1180, 1380, 1580, 1780, 1980, 2180])
            _tone(freq, 0.02)

        # Phase 6c: Equalizer Training - schnelles Hin und Her
        for _ in range(3):
            for freq in [1200, 2400, 1200, 600, 2400, 1800]:
                _tone(freq, 0.025)

        # Phase 6d: Final Training - wird ruhiger
        for freq in [1650, 1650, 1650, 1850, 1850, 1850]:
            _tone(freq, 0.06)

        _pause(0.1)

        # --- Phase 7: Verbunden! ---
        # Bestaetigung: zwei kurze hohe Toene
        _tone(1000, 0.15)
        _pause(0.05)
        _tone(1400, 0.2)

        if not HW_AVAILABLE:
            print("[Buzzer] === VERBUNDEN ===")

    finally:
        if HW_AVAILABLE and _pwm:
            _pwm.stop()
        with _lock:
            _playing = False


def play_disconnect_sound():
    """Kurzer Disconnect-Sound."""
    global _playing

    with _lock:
        if _playing:
            return
        _playing = True

    try:
        _tone(1400, 0.1)
        _tone(1000, 0.1)
        _tone(600, 0.2)
    finally:
        if HW_AVAILABLE and _pwm:
            _pwm.stop()
        with _lock:
            _playing = False


def play_click_sound():
    """Kurzer Klick-Sound fuer Encoder-Drehung."""
    _tone(800, 0.01)
    if HW_AVAILABLE and _pwm:
        _pwm.stop()


def play_async(sound_func):
    """Spielt einen Sound in einem separaten Thread ab."""
    thread = threading.Thread(target=sound_func, daemon=True)
    thread.start()
    return thread


def cleanup():
    """Aufraeumen."""
    if HW_AVAILABLE and _pwm:
        _pwm.stop()


# Standalone-Test
if __name__ == "__main__":
    print("56k Modem-Sound Test")
    print("====================")

    if HW_AVAILABLE:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        setup()

    print("\nSpiele Einwahl-Sound...")
    play_dialup_sound()

    time.sleep(1)

    print("\nSpiele Disconnect-Sound...")
    play_disconnect_sound()

    if HW_AVAILABLE:
        cleanup()
        GPIO.cleanup()

    print("\nFertig!")
