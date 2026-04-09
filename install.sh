#!/bin/bash
# CHRONOSURF - Installation Script
# Optimized for DietPi on Raspberry Pi 3
set -e

INSTALL_DIR="/opt/chronosurf"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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

# Detect OS
IS_DIETPI=false
if [ -f /boot/dietpi/.version ] || [ -f /etc/dietpi-release ] || command -v dietpi-software &>/dev/null; then
    IS_DIETPI=true
    echo "  Detected: DietPi"
else
    echo "  Detected: Raspberry Pi OS / Debian"
fi

# ============================================
# [1/8] System-Pakete
# ============================================
echo "  [1/8] Installing system packages..."
apt-get update -qq

# Core packages (work on both DietPi and Raspberry Pi OS)
apt-get install -y -qq \
    python3 python3-dev gcc \
    hostapd dnsmasq iptables \
    avahi-daemon \
    i2c-tools

# python3-smbus: needed for I2C LCD, may be named differently
apt-get install -y -qq python3-smbus 2>/dev/null || apt-get install -y -qq python3-smbus2 2>/dev/null || true

# pip: DietPi strips it by default
if ! command -v pip3 &>/dev/null; then
    echo "  pip3 not found, installing..."
    if [ "$IS_DIETPI" = true ] && command -v dietpi-software &>/dev/null; then
        # DietPi software ID 130 = Python 3 pip
        dietpi-software install 130
    else
        apt-get install -y -qq python3-pip
    fi
fi

# python3-venv (needed for some pip operations on newer Debian)
apt-get install -y -qq python3-venv 2>/dev/null || true

# ============================================
# [2/8] I2C aktivieren
# ============================================
echo "  [2/8] Enabling I2C..."

# Find the right config.txt path
BOOT_CONFIG=""
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    BOOT_CONFIG="/boot/config.txt"
fi

if [ -n "$BOOT_CONFIG" ]; then
    if ! grep -q "^dtparam=i2c_arm=on" "$BOOT_CONFIG" 2>/dev/null; then
        echo "dtparam=i2c_arm=on" >> "$BOOT_CONFIG"
        echo "  Added I2C to $BOOT_CONFIG"
    fi
fi

# DietPi: also set in dietpi.txt if it exists
if [ -f /boot/dietpi.txt ]; then
    # DietPi uses its own config entries
    if ! grep -q "CONFIG_I2C_STATE=1" /boot/dietpi.txt 2>/dev/null; then
        echo "CONFIG_I2C_STATE=1" >> /boot/dietpi.txt
    fi
fi

# Load I2C module now
if ! grep -q "^i2c-dev" /etc/modules 2>/dev/null; then
    echo "i2c-dev" >> /etc/modules
fi
modprobe i2c-dev 2>/dev/null || true

# ============================================
# [3/8] WiFi-Firmware sicherstellen
# ============================================
echo "  [3/8] Ensuring WiFi firmware..."

# DietPi might not have WiFi firmware installed by default
if [ "$IS_DIETPI" = true ]; then
    # Install wireless firmware for Pi 3 onboard WiFi
    apt-get install -y -qq firmware-brcm80211 2>/dev/null || true
    apt-get install -y -qq wireless-tools wpasupplicant 2>/dev/null || true
fi

# Ensure wlan0 is not blocked
rfkill unblock wifi 2>/dev/null || true

# ============================================
# [4/8] Dateien kopieren
# ============================================
echo "  [4/8] Deploying to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
cp -r portal proxy hardware requirements.txt "${INSTALL_DIR}/"

# ============================================
# [5/8] Python-Abhaengigkeiten
# ============================================
echo "  [5/8] Installing Python dependencies..."

# Try with --break-system-packages first (needed on Bookworm+)
# Fall back to without flag (Bullseye), then to venv as last resort
if pip3 install -r "${INSTALL_DIR}/requirements.txt" --break-system-packages 2>/dev/null; then
    echo "  Python deps installed (system-wide)"
elif pip3 install -r "${INSTALL_DIR}/requirements.txt" 2>/dev/null; then
    echo "  Python deps installed (system-wide, legacy)"
else
    echo "  Using virtualenv as fallback..."
    python3 -m venv "${INSTALL_DIR}/venv"
    "${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"
    # Update service files to use venv python
    for svc in chronosurf-portal chronosurf-proxy chronosurf-hardware; do
        sed -i "s|/usr/bin/python3|${INSTALL_DIR}/venv/bin/python3|g" \
            "${SCRIPT_DIR}/systemd/${svc}.service"
    done
fi

# ============================================
# [6/8] Netzwerk konfigurieren
# ============================================
echo "  [6/8] Configuring network..."
bash "${SCRIPT_DIR}/scripts/setup_network.sh"

# ============================================
# [7/8] Systemd-Services installieren
# ============================================
echo "  [7/8] Installing services..."
cp "${SCRIPT_DIR}/systemd/chronosurf-portal.service" /etc/systemd/system/
cp "${SCRIPT_DIR}/systemd/chronosurf-proxy.service" /etc/systemd/system/
cp "${SCRIPT_DIR}/systemd/chronosurf-hardware.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable chronosurf-portal.service
systemctl enable chronosurf-proxy.service
systemctl enable chronosurf-hardware.service

# ============================================
# [8/8] Performance Optimierungen
# ============================================
echo "  [8/8] Applying performance optimizations..."
bash "${SCRIPT_DIR}/scripts/optimize.sh" 2>&1 | sed 's/^/    /' || true

echo ""
echo "  ================================================"
echo "  INSTALLATION COMPLETE"
echo "  ================================================"
echo ""
echo "  SSID:      CHRONOSURF"
echo "  Password:  surfthetimeline"
echo "  Portal:    http://chronosurf.local"
echo "  IP:        192.168.4.1"
if [ "$IS_DIETPI" = true ]; then
echo ""
echo "  DietPi: If WiFi AP doesn't start, run:"
echo "    dietpi-config  (-> Networking -> WiFi)"
echo "    to ensure onboard WiFi is enabled."
fi
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
