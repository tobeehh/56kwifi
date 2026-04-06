# CHRONOSURF - Verkabelungsanleitung / Wiring Guide

## Bauteile

| # | Bauteil                        | Bezugsquelle       |
|---|--------------------------------|--------------------|
| 1 | Raspberry Pi 3 Model B         | -                  |
| 2 | I2C LCD 20x4 (HD44780 + PCF8574 Backpack) | z.B. AZ-Delivery |
| 3 | KY-040 Rotary Encoder           | z.B. AZ-Delivery  |
| 4 | Passiver Buzzer (3.3V)          | z.B. AZ-Delivery  |
| 5 | Ethernet-Kabel                  | -                  |
| 6 | Micro-USB Netzteil 5V/2.5A     | -                  |
| 7 | microSD-Karte (mind. 8GB)      | -                  |
| 8 | Jumperkabel Female-Female       | -                  |

## Pin-Belegung Raspberry Pi 3

```
                    Raspberry Pi 3 GPIO Header
                    (Ansicht von oben, USB-Ports rechts)

                         3V3 [1]  [2]  5V
                  SDA  GPIO2 [3]  [4]  5V
                  SCL  GPIO3 [5]  [6]  GND
                       GPIO4 [7]  [8]  GPIO14
                         GND [9]  [10] GPIO15
             ENC_CLK GPIO17 [11] [12] GPIO18  ENC_DT
             ENC_BTN GPIO27 [13] [14] GND
                      GPIO22 [15] [16] GPIO23
                         3V3 [17] [18] GPIO24
                      GPIO10 [19] [20] GND
                       GPIO9 [21] [22] GPIO25
                      GPIO11 [23] [24] GPIO8
                         GND [25] [26] GPIO7
                       GPIO0 [27] [28] GPIO1
                       GPIO5 [29] [30] GND
                       GPIO6 [31] [32] GPIO12
                      GPIO13 [33] [34] GND
                      GPIO19 [35] [36] GPIO16
                      GPIO26 [37] [38] GPIO20
                         GND [39] [40] GPIO21

    Belegte Pins:
    [3]  GPIO2/SDA  --> LCD SDA
    [5]  GPIO3/SCL  --> LCD SCL
    [11] GPIO17     --> Encoder CLK
    [12] GPIO18     --> Encoder DT
    [13] GPIO27     --> Encoder SW (Button)
    [15] GPIO22     --> Buzzer Signal
```

## Verkabelung

### 1. LCD 20x4 (I2C Backpack)

Das LCD hat auf der Rueckseite ein kleines PCF8574 I2C-Board
mit 4 Pins: GND, VCC, SDA, SCL.

```
    LCD 20x4 (Rueckseite)          Raspberry Pi
    ┌──────────────────┐
    │  PCF8574 Backpack │
    │                   │
    │  GND ─────────────────────── Pin 9  (GND)
    │  VCC ─────────────────────── Pin 2  (5V)
    │  SDA ─────────────────────── Pin 3  (GPIO2 / SDA)
    │  SCL ─────────────────────── Pin 5  (GPIO3 / SCL)
    │                   │
    └──────────────────┘

    I2C-Adresse: 0x27 (Standard) oder 0x3F (PCF8574A)
    Pruefen mit: i2cdetect -y 1
```

**Hinweis:** Das LCD laeuft mit 5V, die I2C-Leitungen sind
aber 3.3V-tolerant ueber den PCF8574. Kein Level-Shifter noetig.

### 2. Rotary Encoder (KY-040)

```
    KY-040 Encoder                 Raspberry Pi
    ┌─────────────┐
    │  ┌───────┐  │
    │  │  Dreh- │  │
    │  │  knopf │  │
    │  └───────┘  │
    │             │
    │  GND ────────────────────── Pin 14 (GND)
    │   +  ────────────────────── Pin 17 (3V3)
    │  SW  ────────────────────── Pin 13 (GPIO27)  Button
    │  DT  ────────────────────── Pin 12 (GPIO18)  Richtung
    │  CLK ────────────────────── Pin 11 (GPIO17)  Takt
    │             │
    └─────────────┘

    Drehung im Uhrzeigersinn  = Jahr +1
    Drehung gegen Uhrzeiger   = Jahr -1
    Druecken                  = Jahr bestaetigen
```

### 3. Passiver Buzzer

```
    Passiver Buzzer                Raspberry Pi
    ┌───────────┐
    │    (+)    │
    │  Buzzer  ─── + (lang) ────── Pin 15 (GPIO22)
    │          ─── - (kurz) ────── Pin 9  (GND)
    │           │
    └───────────┘

    WICHTIG: PASSIVEN Buzzer verwenden (nicht aktiv)!
    - Passiv: braucht PWM-Signal -> kann Toene erzeugen
    - Aktiv: piept nur auf einer Frequenz

    Unterscheidung: Passiver Buzzer hat keine Elektronik
    auf der Platine und piept NICHT wenn man einfach 3.3V
    anlegt. Aktiver piept sofort.
```

## Gesamtuebersicht

```
                        ┌──────────────────────┐
                        │    Raspberry Pi 3     │
                        │                       │
     ┌──────────┐      │  Pin 2  (5V) ─────────┤──── LCD VCC
     │ Ethernet ├──────┤  Pin 9  (GND) ────────┤──┬─ LCD GND
     │  Kabel   │      │  Pin 3  (SDA) ────────┤──┤─ LCD SDA
     └──────────┘      │  Pin 5  (SCL) ────────┤──┤─ LCD SCL
                        │                       │  │
                        │  Pin 17 (3V3) ────────┤──┤─ Encoder +
                        │  Pin 14 (GND) ────────┤──┤─ Encoder GND
                        │  Pin 11 (GPIO17) ─────┤──┤─ Encoder CLK
     ┌──────────┐      │  Pin 12 (GPIO18) ─────┤──┤─ Encoder DT
     │  WiFi    │      │  Pin 13 (GPIO27) ─────┤──┤─ Encoder SW
     │ Antenne  │      │                       │  │
     │ (intern) │      │  Pin 15 (GPIO22) ─────┤──┤─ Buzzer +
     └──────────┘      │  Pin 9  (GND) ────────┤──┘─ Buzzer -
                        │                       │
                        │  microSD + USB Power  │
                        └──────────────────────┘

    Anzahl benoetigter Kabel: 11 (Female-Female Jumper)
    GND kann geteilt werden (Pins 9, 14, 25, etc. sind alle GND)
```

## Anschluss-Reihenfolge

1. **Pi ausschalten** und Stromversorgung trennen
2. LCD anschliessen (4 Kabel: 5V, GND, SDA, SCL)
3. Encoder anschliessen (5 Kabel: 3V3, GND, CLK, DT, SW)
4. Buzzer anschliessen (2 Kabel: GPIO22, GND)
5. Ethernet-Kabel einstecken (Internet-Uplink)
6. microSD mit DietPi einsetzen
7. Stromversorgung anschliessen

## Testen

Nach dem Booten:

```bash
# I2C pruefen - LCD sollte auf 0x27 oder 0x3F erscheinen
i2cdetect -y 1

# Erwartete Ausgabe:
#      0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
# 20: -- -- -- -- -- -- -- 27 -- -- -- -- -- -- -- --

# GPIO testen (Encoder)
# Drehen/Druecken und auf der Konsole schauen:
python3 /opt/chronosurf/hardware/controller.py

# Buzzer testen
python3 /opt/chronosurf/hardware/buzzer.py
```

## Troubleshooting

| Problem | Loesung |
|---------|---------|
| LCD bleibt dunkel | Kontrast-Poti auf der Rueckseite drehen |
| LCD zeigt nur Bloecke | Kontrast zu hoch -> Poti zurueckdrehen |
| `i2cdetect` zeigt nichts | I2C nicht aktiviert: `dietpi-config` -> Advanced -> I2C |
| LCD auf 0x3F statt 0x27 | Ist ok, wird automatisch erkannt |
| Encoder springt/zaehlt doppelt | Bouncetime in controller.py erhoehen |
| Buzzer piept nur einmal | Aktiven statt passiven Buzzer erwischt |
| Kein WiFi-AP sichtbar | `sudo systemctl status hostapd` pruefen |
