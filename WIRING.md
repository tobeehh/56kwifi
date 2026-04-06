# CHRONOSURF - Verkabelungsanleitung / Wiring Guide

## Bauteile

| # | Bauteil                                    | Hinweis            |
|---|--------------------------------------------|--------------------|
| 1 | Raspberry Pi 3 Model B                     | -                  |
| 2 | I2C LCD 20x4 (HD44780 + PCF8574 Backpack)  | z.B. AZ-Delivery   |
| 3 | KY-040 Rotary Encoder mit Pushbutton (x2)  | 1x Jahr, 1x Speed  |
| 4 | Passiver Buzzer (3.3V)                     | NICHT aktiv!       |
| 5 | Ethernet-Kabel                              | Internet-Uplink    |
| 6 | Micro-USB Netzteil 5V/2.5A                 | -                  |
| 7 | microSD-Karte (mind. 8GB)                  | DietPi Image       |
| 8 | Jumperkabel Female-Female                   | ca. 16 Stueck      |

## Pin-Belegung Raspberry Pi 3

```
                    Raspberry Pi 3 GPIO Header
                    (Ansicht von oben, USB-Ports rechts)

                         3V3 [1]  [2]  5V           <- LCD VCC
                  SDA  GPIO2 [3]  [4]  5V
                  SCL  GPIO3 [5]  [6]  GND
                       GPIO4 [7]  [8]  GPIO14
                         GND [9]  [10] GPIO15
     YEAR_CLK  GPIO17 [11] [12] GPIO18  YEAR_DT
     YEAR_BTN  GPIO27 [13] [14] GND
       BUZZER  GPIO22 [15] [16] GPIO23  LED_R
                         3V3 [17] [18] GPIO24  LED_G
                      GPIO10 [19] [20] GND     LED_GND
                       GPIO9 [21] [22] GPIO25  LED_B
                      GPIO11 [23] [24] GPIO8
                         GND [25] [26] GPIO7
                       GPIO0 [27] [28] GPIO1
    SPEED_CLK   GPIO5 [29] [30] GND
    SPEED_DT    GPIO6 [31] [32] GPIO12
    SPEED_BTN  GPIO13 [33] [34] GND
                      GPIO19 [35] [36] GPIO16
                      GPIO26 [37] [38] GPIO20
                         GND [39] [40] GPIO21

    Belegte Pins (12 Stueck):
    [2]  5V         --> LCD VCC
    [3]  GPIO2/SDA  --> LCD SDA
    [5]  GPIO3/SCL  --> LCD SCL
    [9]  GND        --> LCD GND, Buzzer -, gemeinsam
    [11] GPIO17     --> Encoder 1 CLK  (Jahr)
    [12] GPIO18     --> Encoder 1 DT   (Jahr)
    [13] GPIO27     --> Encoder 1 SW   (Jahr bestaetigen)
    [15] GPIO22     --> Buzzer +
    [16] GPIO23     --> RGB LED Red
    [17] 3V3        --> Encoder 1 VCC, Encoder 2 VCC
    [18] GPIO24     --> RGB LED Green
    [20] GND        --> RGB LED GND (Kathode)
    [22] GPIO25     --> RGB LED Blue
    [29] GPIO5      --> Encoder 2 CLK  (Speed)
    [31] GPIO6      --> Encoder 2 DT   (Speed)
    [33] GPIO13     --> Encoder 2 SW   (Speed bestaetigen)
```

## Verkabelung

### 1. LCD 20x4 (I2C Backpack)

Das LCD hat auf der Rueckseite ein PCF8574 I2C-Board
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

### 2. Encoder 1 - JAHR (KY-040 mit Pushbutton)

```
    KY-040 Encoder 1               Raspberry Pi
    ┌─────────────┐
    │  ┌───────┐  │
    │  │ YEAR  │  │
    │  │ Knopf │  │
    │  └───────┘  │
    │             │
    │  GND ────────────────────── Pin 14 (GND)
    │   +  ────────────────────── Pin 17 (3V3)
    │  SW  ────────────────────── Pin 13 (GPIO27)  Druecken = bestaetigen
    │  DT  ────────────────────── Pin 12 (GPIO18)  Drehrichtung
    │  CLK ────────────────────── Pin 11 (GPIO17)  Taktgeber
    │             │
    └─────────────┘

    Drehen im Uhrzeigersinn  = Jahr +1
    Drehen gegen Uhrzeiger   = Jahr -1
    Druecken                 = Jahr als Default setzen
```

### 3. Encoder 2 - SPEED (KY-040 mit Pushbutton)

```
    KY-040 Encoder 2               Raspberry Pi
    ┌─────────────┐
    │  ┌───────┐  │
    │  │ SPEED │  │
    │  │ Knopf │  │
    │  └───────┘  │
    │             │
    │  GND ────────────────────── Pin 34 (GND)
    │   +  ────────────────────── Pin 17 (3V3)  <- geteilt mit Enc. 1
    │  SW  ────────────────────── Pin 33 (GPIO13)  Druecken = bestaetigen
    │  DT  ────────────────────── Pin 31 (GPIO6)   Drehrichtung
    │  CLK ────────────────────── Pin 29 (GPIO5)   Taktgeber
    │             │
    └─────────────┘

    Drehen im Uhrzeigersinn  = schneller (56k > ISDN > DSL > ... > FULL)
    Drehen gegen Uhrzeiger   = langsamer
    Druecken                 = Speed als Default setzen

    Speed-Stufen:
    56k Modem (56 kbit/s) -> ISDN (128k) -> DSL 384k ->
    DSL 1000 -> DSL 6000 -> DSL 16000 -> FULL SPEED
```

### 4. RGB LED (Common Cathode, 4 Pins)

```
    RGB LED                        Raspberry Pi
    ┌───────────┐
    │   (    )  │
    │  R G B K  │     K = Kathode (laengstes Bein = GND)
    │  │ │ │ │  │
    └──┼─┼─┼─┼──┘
       │ │ │ │
       │ │ │ └──── GND ────────── Pin 20 (GND)
       │ │ └────── B ──────────── Pin 22 (GPIO25)
       │ └──────── G ──────────── Pin 18 (GPIO24)
       └────────── R ──────────── Pin 16 (GPIO23)

    WICHTIG: Common CATHODE (GND gemeinsam, nicht VCC)!
    Das laengste Bein ist GND (Kathode).
    Die drei kurzen Beine sind R, G, B.

    Pin-Reihenfolge (von der flachen Seite gesehen):
    R - GND(lang) - G - B

    Farben pro Epoche:
    90s    = Gruen     (Phosphor-Terminal)
    Y2K    = Cyan      (Matrix)
    Web2.0 = Orange    (warm)
    Social = Blau      (Twitter)
    Modern = Weiss     (clean)

    Effekte:
    - Statisch: zeigt aktuelle Epoche
    - Pulsierend: Surfer sind verbunden
    - Gruen-Flash: neuer Surfer connected
    - Rot-Flash: Surfer disconnected
    - Fade: sanfter Uebergang bei Jahreswechsel
    - Boot: faehrt durch alle Epochenfarben
```

### 5. Passiver Buzzer

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
     ┌─────────────┐   │  Pin 17 (3V3) ────────┤──┤─ Enc.1 + / Enc.2 +
     │  Encoder 1  │   │  Pin 14 (GND) ────────┤──┤─ Enc.1 GND
     │   (YEAR)    │   │  Pin 11 (GPIO17) ─────┤──┤─ Enc.1 CLK
     │  Drehen=    │   │  Pin 12 (GPIO18) ─────┤──┤─ Enc.1 DT
     │  Jahr +/-   │   │  Pin 13 (GPIO27) ─────┤──┤─ Enc.1 SW
     └─────────────┘   │                       │  │
                        │  Pin 34 (GND) ────────┤──┤─ Enc.2 GND
     ┌─────────────┐   │  Pin 29 (GPIO5) ──────┤──┤─ Enc.2 CLK
     │  Encoder 2  │   │  Pin 31 (GPIO6) ──────┤──┤─ Enc.2 DT
     │   (SPEED)   │   │  Pin 33 (GPIO13) ─────┤──┤─ Enc.2 SW
     │  Drehen=    │   │                       │  │
     │  56k..FULL  │   │  Pin 15 (GPIO22) ─────┤──┤─ Buzzer +
     └─────────────┘   │  Pin 9  (GND) ────────┤──┤─ Buzzer -
                        │                       │  │
     ┌──────────┐      │  Pin 16 (GPIO23) ─────┤──┤─ LED Red
     │  Buzzer  │      │  Pin 18 (GPIO24) ─────┤──┤─ LED Green
     └──────────┘      │  Pin 22 (GPIO25) ─────┤──┤─ LED Blue
                        │  Pin 20 (GND) ────────┤──┘─ LED GND
     ┌──────────┐      │                       │
     │ RGB LED  │      │  WiFi (intern)         │
     │ (Epoche) │      │  microSD + USB Power   │
     └──────────┘      └──────────────────────┘

    Anzahl benoetigter Kabel: 20 (Female-Female Jumper)
    3V3 und GND koennen geteilt werden
```

## Anschluss-Reihenfolge

1. **Pi ausschalten** und Stromversorgung trennen
2. LCD anschliessen (4 Kabel: 5V, GND, SDA, SCL)
3. Encoder 1 (YEAR) anschliessen (5 Kabel: 3V3, GND, CLK, DT, SW)
4. Encoder 2 (SPEED) anschliessen (5 Kabel: 3V3*, GND, CLK, DT, SW)
   *3V3 mit Encoder 1 teilen
5. RGB LED anschliessen (4 Kabel: R=GPIO23, G=GPIO24, B=GPIO25, GND)
6. Buzzer anschliessen (2 Kabel: GPIO22, GND)
6. Ethernet-Kabel einstecken (Internet-Uplink)
7. microSD mit DietPi einsetzen
8. Stromversorgung anschliessen

## LCD-Anzeige

```
1999 90s     *2 online   <- Jahr, Epoche, Surfer
◄-----■············►     <- Zeitstrahl (Encoder 1)
⊕------■···· 128k        <- Speed-Balken (Encoder 2)
 F2>99@56k C1>01@isdn    <- Aktive Surfer
```

## Testen

```bash
# I2C pruefen - LCD sollte auf 0x27 oder 0x3F erscheinen
i2cdetect -y 1

# Hardware-Controller starten (zeigt alle Encoder-Events)
python3 /opt/chronosurf/hardware/controller.py

# Buzzer separat testen
python3 /opt/chronosurf/hardware/buzzer.py
```

## Troubleshooting

| Problem | Loesung |
|---------|---------|
| LCD bleibt dunkel | Kontrast-Poti auf der Rueckseite drehen |
| LCD zeigt nur Bloecke | Kontrast zu hoch -> Poti zurueckdrehen |
| `i2cdetect` zeigt nichts | I2C nicht aktiviert: `dietpi-config` -> Advanced -> I2C |
| LCD auf 0x3F statt 0x27 | Ist ok, wird automatisch erkannt |
| Encoder springt/doppelt | Bouncetime in controller.py erhoehen |
| Buzzer piept nur einmal | Aktiven statt passiven Buzzer erwischt |
| Kein WiFi-AP sichtbar | `sudo systemctl status hostapd` pruefen |
| Speed-Encoder tut nichts | Pins pruefen: GPIO5/6/13 (nicht 15/16/17!) |
| Nur ein Encoder geht | GND und 3V3 beider Encoder pruefen |
