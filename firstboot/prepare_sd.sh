#!/bin/bash
# CHRONOSURF - SD-Karten Vorbereitung
#
# Dieses Script auf dem Mac/PC ausfuehren nachdem die DietPi SD-Karte
# gemountet ist. Es patcht dietpi.txt und kopiert das Boot-Script.
#
# Verwendung:
#   bash prepare_sd.sh /Volumes/boot
#
# Unter Linux:
#   bash prepare_sd.sh /mnt/boot
#
set -e

BOOT_DIR="${1:-}"

if [ -z "$BOOT_DIR" ]; then
    echo ""
    echo "CHRONOSURF - SD Card Setup"
    echo "=========================="
    echo ""
    echo "Verwendung: bash prepare_sd.sh <boot-partition-pfad>"
    echo ""
    echo "Beispiele:"
    echo "  Mac:   bash prepare_sd.sh /Volumes/boot"
    echo "  Linux: bash prepare_sd.sh /mnt/boot"
    echo ""

    # Auto-Detect auf Mac
    if [ -d "/Volumes/boot" ]; then
        echo "Gefunden: /Volumes/boot"
        BOOT_DIR="/Volumes/boot"
        read -p "Diesen Pfad verwenden? [Y/n] " yn
        if [ "$yn" = "n" ] || [ "$yn" = "N" ]; then
            exit 1
        fi
    elif [ -d "/Volumes/bootfs" ]; then
        echo "Gefunden: /Volumes/bootfs"
        BOOT_DIR="/Volumes/bootfs"
        read -p "Diesen Pfad verwenden? [Y/n] " yn
        if [ "$yn" = "n" ] || [ "$yn" = "N" ]; then
            exit 1
        fi
    else
        echo "Keine Boot-Partition gefunden. Bitte Pfad angeben."
        exit 1
    fi
fi

DIETPI_TXT="$BOOT_DIR/dietpi.txt"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$DIETPI_TXT" ]; then
    echo "FEHLER: $DIETPI_TXT nicht gefunden!"
    echo "Ist die DietPi SD-Karte gemountet?"
    exit 1
fi

echo ""
echo "CHRONOSURF - SD Card Setup"
echo "=========================="
echo "Boot-Partition: $BOOT_DIR"
echo ""

# --- dietpi.txt patchen ---
echo "[1/2] Patche dietpi.txt..."

patch_value() {
    local key="$1"
    local value="$2"
    local file="$DIETPI_TXT"

    if grep -q "^${key}=" "$file" 2>/dev/null; then
        # Bestehenden Wert ersetzen
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
        echo "  ${key}=${value} (geaendert)"
    else
        # Zeile hinzufuegen falls nicht vorhanden
        echo "${key}=${value}" >> "$file"
        echo "  ${key}=${value} (hinzugefuegt)"
    fi
}

patch_value "AUTO_SETUP_AUTOMATED" "1"
patch_value "AUTO_SETUP_GLOBAL_PASSWORD" "chronosurf"
patch_value "AUTO_SETUP_NET_ETHERNET_ENABLED" "1"
patch_value "AUTO_SETUP_NET_WIFI_ENABLED" "1"
patch_value "AUTO_SETUP_SSH_SERVER_INDEX" "-2"
patch_value "SOFTWARE_DISABLE_SSH_PASSWORD_LOGINS" "0"
patch_value "AUTO_SETUP_NET_HOSTNAME" "chronosurf"
patch_value "CONFIG_SERIAL_CONSOLE_ENABLE" "0"
patch_value "AUTO_SETUP_LOCALE" "de_DE.UTF-8"
patch_value "AUTO_SETUP_TIMEZONE" "Europe/Berlin"

# Backup-Dateien von sed aufraeumen
rm -f "${DIETPI_TXT}.bak"

# --- Automation Script kopieren ---
echo ""
echo "[2/2] Kopiere Automation_Custom_Script.sh..."
cp "$SCRIPT_DIR/Automation_Custom_Script.sh" "$BOOT_DIR/Automation_Custom_Script.sh"
chmod +x "$BOOT_DIR/Automation_Custom_Script.sh"
echo "  -> $BOOT_DIR/Automation_Custom_Script.sh"

echo ""
echo "=========================="
echo "SD-Karte ist bereit!"
echo "=========================="
echo ""
echo "Naechste Schritte:"
echo "  1. SD-Karte auswerfen"
echo "  2. In den Raspberry Pi einsetzen"
echo "  3. Ethernet-Kabel anschliessen"
echo "  4. Strom anschliessen"
echo "  5. Warten (~5-10 Minuten)"
echo "  6. WLAN 'CHRONOSURF' erscheint"
echo ""
echo "SSH-Zugang:"
echo "  ssh root@chronosurf.local"
echo "  Passwort: chronosurf"
echo ""
