#!/bin/bash
# CHRONOSURF - DietPi Automation Config
#
# ANLEITUNG:
# 1. DietPi Image fuer Raspberry Pi 3 flashen (auf microSD)
# 2. SD-Karte am PC mounten
# 3. Diese Datei als /boot/Automation_Custom_Script.sh auf die SD kopieren
# 4. dietpi.txt anpassen (siehe unten) oder dietpi-wifi.txt erstellen
# 5. SD in den Pi einsetzen, Ethernet anschliessen, booten
# 6. DietPi installiert alles automatisch beim ersten Boot (~5-10 Min)
# 7. Pi startet neu -> CHRONOSURF laeuft!
#
# WICHTIG: Vor dem ersten Boot in /boot/dietpi.txt setzen:
#   AUTO_SETUP_AUTOMATED=1
#   AUTO_SETUP_GLOBAL_PASSWORD=chronosurf
#   AUTO_SETUP_NET_ETHERNET_ENABLED=1
#   AUTO_SETUP_NET_WIFI_ENABLED=1
#   CONFIG_SERIAL_CONSOLE_ENABLE=0
#
# Optional: /boot/dietpi-wifi.txt ist NICHT noetig, da wir WiFi als AP nutzen.

set -e

echo "=========================================="
echo " CHRONOSURF - First Boot Installation"
echo "=========================================="

export DEBIAN_FRONTEND=noninteractive

# I2C aktivieren
/boot/dietpi/func/dietpi-set_hardware i2c enable

# Git installieren und Repo klonen
apt-get update -qq
apt-get install -y -qq git

cd /tmp
git clone https://github.com/tobeehh/56kwifi.git chronosurf
cd chronosurf

# Hauptinstallation ausfuehren
bash install.sh

# Aufraeumen
rm -rf /tmp/chronosurf

echo ""
echo "=========================================="
echo " CHRONOSURF - Installation complete!"
echo " System will reboot now."
echo "=========================================="
