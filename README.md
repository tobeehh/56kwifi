# 56k WiFi Zeitmaschine

Eine Raspberry Pi 3 basierte "Zeitmaschine", die es ermoeglicht, das Internet
vergangener Jahre ueber das Wayback Machine (Internet Archive) zu erleben.

## Funktionsweise

- Der Pi verbindet sich per **Ethernet** mit dem Internet
- Per **WiFi** wird ein Access Point aufgespannt ("Zeitmaschine")
- Jedes verbundene Geraet wird per **Captive Portal** auf die Jahresauswahl geleitet
- Nach Auswahl eines Jahres wird der gesamte HTTP-Traffic ueber die **Wayback Machine** geroutet
- Am Geraet selbst kann das Jahr per **Rotary Encoder** und **SSD1306 Display** eingestellt werden
- Die Zeitmaschine ist per Hostname `zeitmaschine.local` erreichbar

## Hardware

- Raspberry Pi 3
- SSD1306 OLED Display (I2C, 128x64)
- Rotary Encoder (KY-040) mit integriertem Button
- Ethernet-Kabel fuer Internetzugang

### Pin-Belegung (BCM)

| Komponente        | Pin  |
|-------------------|------|
| Rotary CLK        | GPIO 17 |
| Rotary DT         | GPIO 18 |
| Rotary Button     | GPIO 27 |
| SSD1306 SDA       | GPIO 2 (I2C) |
| SSD1306 SCL       | GPIO 3 (I2C) |

## Installation

```bash
sudo bash install.sh
```

## Manueller Start

```bash
# Netzwerk konfigurieren
sudo bash scripts/setup_network.sh

# Portal starten
cd portal && python3 app.py

# Proxy starten
python3 proxy/wayback_proxy.py

# Hardware-Controller starten
python3 hardware/controller.py
```

## Zugriff

- Captive Portal: http://zeitmaschine.local oder http://192.168.4.1
- Direkte Jahresauswahl: http://zeitmaschine.local/set?year=1999
