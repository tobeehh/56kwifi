#!/bin/bash
# 56k WiFi Zeitmaschine - Installations-Script
set -e

INSTALL_DIR="/opt/zeitmaschine"

echo "================================================"
echo "  56k WiFi ZEITMASCHINE - Installation"
echo "================================================"
echo ""

# Root-Check
if [ "$EUID" -ne 0 ]; then
    echo "Bitte als root ausfuehren: sudo bash install.sh"
    exit 1
fi

# System-Pakete
echo "[1/6] Installiere System-Pakete..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    hostapd dnsmasq iptables \
    avahi-daemon \
    i2c-tools python3-smbus \
    libopenjp2-7 libtiff5

# I2C aktivieren
echo "[2/6] Aktiviere I2C..."
if ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt 2>/dev/null; then
    echo "dtparam=i2c_arm=on" >> /boot/config.txt
fi
if ! grep -q "^i2c-dev" /etc/modules 2>/dev/null; then
    echo "i2c-dev" >> /etc/modules
fi
modprobe i2c-dev 2>/dev/null || true

# Dateien kopieren
echo "[3/6] Kopiere Dateien nach ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
cp -r portal proxy hardware requirements.txt "${INSTALL_DIR}/"

# Python-Abhaengigkeiten
echo "[4/6] Installiere Python-Abhaengigkeiten..."
pip3 install -r "${INSTALL_DIR}/requirements.txt" --break-system-packages 2>/dev/null \
    || pip3 install -r "${INSTALL_DIR}/requirements.txt"

# Netzwerk konfigurieren
echo "[5/6] Konfiguriere Netzwerk..."
bash scripts/setup_network.sh

# Systemd-Services installieren
echo "[6/6] Installiere Systemd-Services..."
cp systemd/zeitmaschine-portal.service /etc/systemd/system/
cp systemd/zeitmaschine-proxy.service /etc/systemd/system/
cp systemd/zeitmaschine-hardware.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable zeitmaschine-portal.service
systemctl enable zeitmaschine-proxy.service
systemctl enable zeitmaschine-hardware.service

echo ""
echo "================================================"
echo "  Installation abgeschlossen!"
echo "================================================"
echo ""
echo "  WLAN-Name:  Zeitmaschine"
echo "  Passwort:   zeitreise"
echo "  Portal:     http://zeitmaschine.local"
echo "  IP:         192.168.4.1"
echo ""
echo "  Bitte den Pi neu starten:"
echo "    sudo reboot"
echo ""
echo "  Nach dem Neustart:"
echo "    1. Mit WLAN 'Zeitmaschine' verbinden"
echo "    2. Captive Portal oeffnet sich automatisch"
echo "    3. Jahr auswaehlen und Zeitreise starten!"
echo ""
echo "  Oder am Geraet:"
echo "    - Rotary Encoder drehen = Jahr waehlen"
echo "    - Button druecken = Aktivieren/Deaktivieren"
echo ""
