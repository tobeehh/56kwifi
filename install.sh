#!/bin/bash
# CHRONOSURF - Installation Script
set -e

INSTALL_DIR="/opt/chronosurf"

cat << 'BANNER'

   ██████╗██╗  ██╗██████╗  ██████╗ ███╗   ██╗ ██████╗ ███████╗██╗   ██╗██████╗ ███████╗
  ██╔════╝██║  ██║██╔══██╗██╔═══██╗████╗  ██║██╔═══██╗██╔════╝██║   ██║██╔══██╗██╔════╝
  ██║     ███████║██████╔╝██║   ██║██╔██╗ ██║██║   ██║███████╗██║   ██║██████╔╝█████╗
  ██║     ██╔══██║██╔══██╗██║   ██║██║╚██╗██║██║   ██║╚════██║██║   ██║██╔══██╗██╔══╝
  ╚██████╗██║  ██║██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝███████║╚██████╔╝██║  ██║██║
   ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝

                          [ S U R F   T H E   T I M E L I N E ]

BANNER

echo "  Installing..."
echo ""

# Root-Check
if [ "$EUID" -ne 0 ]; then
    echo "  ERROR: Run as root: sudo bash install.sh"
    exit 1
fi

# System-Pakete
echo "  [1/6] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    hostapd dnsmasq iptables \
    avahi-daemon \
    i2c-tools python3-smbus \
    libopenjp2-7 libtiff5

# I2C aktivieren
echo "  [2/6] Enabling I2C..."
if ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt 2>/dev/null; then
    echo "dtparam=i2c_arm=on" >> /boot/config.txt
fi
if ! grep -q "^i2c-dev" /etc/modules 2>/dev/null; then
    echo "i2c-dev" >> /etc/modules
fi
modprobe i2c-dev 2>/dev/null || true

# Dateien kopieren
echo "  [3/6] Deploying to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
cp -r portal proxy hardware requirements.txt "${INSTALL_DIR}/"

# Python-Abhaengigkeiten
echo "  [4/6] Installing Python dependencies..."
pip3 install -r "${INSTALL_DIR}/requirements.txt" --break-system-packages 2>/dev/null \
    || pip3 install -r "${INSTALL_DIR}/requirements.txt"

# Netzwerk konfigurieren
echo "  [5/6] Configuring network..."
bash scripts/setup_network.sh

# Systemd-Services installieren
echo "  [6/6] Installing services..."
cp systemd/chronosurf-portal.service /etc/systemd/system/
cp systemd/chronosurf-proxy.service /etc/systemd/system/
cp systemd/chronosurf-hardware.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable chronosurf-portal.service
systemctl enable chronosurf-proxy.service
systemctl enable chronosurf-hardware.service

echo ""
echo "  ================================================"
echo "  INSTALLATION COMPLETE"
echo "  ================================================"
echo ""
echo "  SSID:      CHRONOSURF"
echo "  Password:  surfthetimeline"
echo "  Portal:    http://chronosurf.local"
echo "  IP:        192.168.4.1"
echo ""
echo "  Reboot to activate:"
echo "    sudo reboot"
echo ""
echo "  After reboot:"
echo "    1. Connect to WiFi 'CHRONOSURF'"
echo "    2. Captive portal opens automatically"
echo "    3. Pick a year and DIAL IN"
echo ""
echo "  Hardware controls:"
echo "    - Rotate encoder = select year"
echo "    - Press button   = connect / disconnect"
echo "    - OLED display   = shows current state"
echo ""
