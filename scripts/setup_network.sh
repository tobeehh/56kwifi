#!/bin/bash
# CHRONOSURF - Network Setup
# Supports both DietPi and Raspberry Pi OS
set -e

AP_INTERFACE="wlan0"
INET_INTERFACE="eth0"
AP_IP="192.168.4.1"
AP_SUBNET="192.168.4.0/24"
DHCP_RANGE_START="192.168.4.10"
DHCP_RANGE_END="192.168.4.100"
SSID="CHRONOSURF"
WPA_PASSPHRASE="surfthetimeline"
HOSTNAME="chronosurf"

echo "=== CHRONOSURF - Network Setup ==="

# Detect OS
IS_DIETPI=false
if [ -f /boot/dietpi/.version ] || [ -f /etc/dietpi-release ] || command -v dietpi-software &>/dev/null; then
    IS_DIETPI=true
    echo "  OS: DietPi"
else
    echo "  OS: Raspberry Pi OS / Debian"
fi

# ============================================
# [1/7] Pakete
# ============================================
echo "  [1/7] Installing network packages..."
apt-get install -y -qq hostapd dnsmasq iptables avahi-daemon 2>/dev/null || true

# ============================================
# [2/7] Hostname (mDNS)
# ============================================
echo "  [2/7] Setting hostname to '${HOSTNAME}'..."
hostnamectl set-hostname "$HOSTNAME" 2>/dev/null || echo "$HOSTNAME" > /etc/hostname

# /etc/hosts aktualisieren
if grep -q "127.0.1.1" /etc/hosts 2>/dev/null; then
    sed -i "s/127.0.1.1.*/127.0.1.1\t${HOSTNAME}/" /etc/hosts
else
    echo "127.0.1.1	${HOSTNAME}" >> /etc/hosts
fi

# Avahi konfigurieren
cat > /etc/avahi/avahi-daemon.conf << AVAHI
[server]
host-name=chronosurf
domain-name=local
use-ipv4=yes
use-ipv6=no
allow-interfaces=wlan0,eth0

[publish]
publish-addresses=yes
publish-hinfo=yes
publish-workstation=no

[reflector]
enable-reflector=no

[rlimits]
AVAHI

systemctl enable avahi-daemon 2>/dev/null || true
systemctl restart avahi-daemon 2>/dev/null || true

# ============================================
# [3/7] WiFi-Chip aktivieren + wpa_supplicant deaktivieren
# ============================================
echo "  [3/7] Enabling WiFi chip, disabling wpa_supplicant..."

# DietPi deaktiviert WiFi per dtoverlay - das muss raus
BOOT_CONFIG=""
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    BOOT_CONFIG="/boot/config.txt"
fi

if [ -n "$BOOT_CONFIG" ]; then
    sed -i '/dtoverlay=disable-wifi/d' "$BOOT_CONFIG"
    echo "  -> Removed disable-wifi overlay from $BOOT_CONFIG"
fi

# DietPi dietpi.txt: WiFi aktivieren
if [ -f /boot/dietpi.txt ]; then
    sed -i 's/AUTO_SETUP_NET_WIFI_ENABLED=0/AUTO_SETUP_NET_WIFI_ENABLED=1/' /boot/dietpi.txt
fi

# brcmfmac Treiber beim Boot laden (Pi 3B+ braucht das explizit)
if ! grep -q "^brcmfmac" /etc/modules 2>/dev/null; then
    echo "brcmfmac" >> /etc/modules
fi
modprobe brcmfmac 2>/dev/null || true

# Warten bis wlan0 erscheint
echo -n "  Waiting for wlan0"
for i in $(seq 1 10); do
    if ip link show wlan0 &>/dev/null; then
        echo " OK"
        break
    fi
    echo -n "."
    sleep 1
done

if ! ip link show wlan0 &>/dev/null; then
    echo " WARN: wlan0 not found (may need reboot)"
fi

# wpa_supplicant darf wlan0 nicht anfassen, sonst kaempft es mit hostapd
# DietPi und Pi OS nutzen beide systemd wpa_supplicant
systemctl disable wpa_supplicant 2>/dev/null || true
systemctl stop wpa_supplicant 2>/dev/null || true

# Sicherstellen, dass kein wpa_supplicant@wlan0 laeuft
systemctl disable "wpa_supplicant@${AP_INTERFACE}" 2>/dev/null || true
systemctl stop "wpa_supplicant@${AP_INTERFACE}" 2>/dev/null || true

# ============================================
# [4/7] hostapd konfigurieren
# ============================================
echo "  [4/7] Configuring hostapd (WiFi Access Point)..."
cat > /etc/hostapd/hostapd.conf << HOSTAPD
interface=${AP_INTERFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=7
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${WPA_PASSPHRASE}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
HOSTAPD

# hostapd Default-Config
sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || true
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > /etc/default/hostapd

# ============================================
# [5/7] Statische IP fuer wlan0
# ============================================
echo "  [5/7] Configuring static IP for ${AP_INTERFACE}..."

# Methode haengt vom Netzwerk-Backend ab:
# - DietPi default: ifupdown (/etc/network/interfaces)
# - Pi OS default: dhcpcd (/etc/dhcpcd.conf)
# - Neuere DietPi: kann auch NetworkManager nutzen
# Wir konfigurieren BEIDE Wege, der aktive gewinnt.

# --- Methode A: ifupdown (DietPi Standard) ---
mkdir -p /etc/network/interfaces.d

cat > /etc/network/interfaces.d/wlan0 << IFACE
# CHRONOSURF AP interface - managed by hostapd
allow-hotplug ${AP_INTERFACE}
iface ${AP_INTERFACE} inet static
    address ${AP_IP}
    netmask 255.255.255.0
IFACE

echo "  -> /etc/network/interfaces.d/wlan0 created"

# Sicherstellen dass interfaces.d eingebunden wird
if [ -f /etc/network/interfaces ]; then
    if ! grep -q "source-directory /etc/network/interfaces.d" /etc/network/interfaces 2>/dev/null && \
       ! grep -q "source /etc/network/interfaces.d" /etc/network/interfaces 2>/dev/null; then
        echo "" >> /etc/network/interfaces
        echo "source-directory /etc/network/interfaces.d" >> /etc/network/interfaces
    fi
fi

# --- Methode B: dhcpcd (Pi OS Standard) ---
if [ -f /etc/dhcpcd.conf ]; then
    if ! grep -q "interface ${AP_INTERFACE}" /etc/dhcpcd.conf 2>/dev/null; then
        cat >> /etc/dhcpcd.conf << DHCPCD

# CHRONOSURF AP interface
interface ${AP_INTERFACE}
    static ip_address=${AP_IP}/24
    nohook wpa_supplicant
DHCPCD
        echo "  -> /etc/dhcpcd.conf updated"
    fi
fi

# --- Methode C: NetworkManager (falls aktiv) ---
if systemctl is-active --quiet NetworkManager 2>/dev/null; then
    # NetworkManager soll wlan0 ignorieren (hostapd managed)
    cat > /etc/NetworkManager/conf.d/chronosurf.conf << NMCONF
[keyfile]
unmanaged-devices=interface-name:${AP_INTERFACE}
NMCONF
    systemctl reload NetworkManager 2>/dev/null || true
    echo "  -> NetworkManager: wlan0 set to unmanaged"
fi

# ============================================
# [6/7] dnsmasq konfigurieren (DHCP + DNS)
# ============================================
echo "  [6/7] Configuring dnsmasq (DHCP + DNS)..."
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
cat > /etc/dnsmasq.conf << DNSMASQ
# CHRONOSURF - DHCP & DNS for captive portal

# Only listen on AP interface
interface=${AP_INTERFACE}
bind-interfaces

# DHCP range
dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},255.255.255.0,24h
dhcp-option=option:router,${AP_IP}
dhcp-option=option:dns-server,${AP_IP}

# Upstream DNS for real lookups (web.archive.org etc.)
server=8.8.8.8
server=8.8.4.4

# Captive portal detection - redirect to portal IP
address=/connectivitycheck.gstatic.com/${AP_IP}
address=/clients3.google.com/${AP_IP}
address=/captive.apple.com/${AP_IP}
address=/www.apple.com/${AP_IP}
address=/detectportal.firefox.com/${AP_IP}
address=/msftconnecttest.com/${AP_IP}
address=/www.msftconnecttest.com/${AP_IP}
address=/nmcheck.gnome.org/${AP_IP}

# Local hostname
address=/chronosurf.local/${AP_IP}
DNSMASQ

# ============================================
# [7/7] IP-Forwarding und iptables
# ============================================
echo "  [7/7] Configuring IP forwarding and firewall..."

# IP forwarding aktivieren (persistent)
if [ -f /etc/sysctl.conf ]; then
    sed -i 's/^#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf
    # Falls die Zeile gar nicht existiert
    if ! grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf; then
        echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
    fi
fi

# DietPi: auch in dietpi.txt sicherstellen
if [ -f /boot/dietpi.txt ]; then
    if ! grep -q "CONFIG_NET_IP_FORWARD=1" /boot/dietpi.txt 2>/dev/null; then
        echo "CONFIG_NET_IP_FORWARD=1" >> /boot/dietpi.txt
    fi
fi

# Sofort aktivieren
sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true

# iptables-Regeln: NAT + Captive Portal Redirect
iptables -t nat -F
iptables -F FORWARD

# NAT fuer Internetzugang (wlan0 clients -> eth0 -> internet)
iptables -t nat -A POSTROUTING -o ${INET_INTERFACE} -j MASQUERADE
iptables -A FORWARD -i ${INET_INTERFACE} -o ${AP_INTERFACE} -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i ${AP_INTERFACE} -o ${INET_INTERFACE} -j ACCEPT

# HTTP -> Captive Portal (Port 8080)
iptables -t nat -A PREROUTING -i ${AP_INTERFACE} -p tcp --dport 80 -j DNAT --to-destination ${AP_IP}:8080
# HTTPS -> Captive Portal (fuer Detection-Endpoints)
iptables -t nat -A PREROUTING -i ${AP_INTERFACE} -p tcp --dport 443 -j DNAT --to-destination ${AP_IP}:8080

# iptables persistent machen
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4

# iptables beim Boot laden
# DietPi / Debian: nutze iptables-persistent oder rc.local
if ! dpkg -l iptables-persistent &>/dev/null; then
    # Kein iptables-persistent -> restore via rc.local / systemd
    cat > /etc/systemd/system/chronosurf-iptables.service << 'IPTABLES_SVC'
[Unit]
Description=Chronosurf iptables restore
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/sbin/iptables-restore /etc/iptables/rules.v4
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
IPTABLES_SVC
    systemctl daemon-reload
    systemctl enable chronosurf-iptables.service
fi

# Dienste aktivieren
systemctl unmask hostapd 2>/dev/null || true
systemctl enable hostapd
systemctl enable dnsmasq

echo ""
echo "  === Network setup complete ==="
echo "  SSID:      ${SSID}"
echo "  Password:  ${WPA_PASSPHRASE}"
echo "  AP IP:     ${AP_IP}"
echo "  Hostname:  ${HOSTNAME}.local"
if [ "$IS_DIETPI" = true ]; then
echo ""
echo "  DietPi note: onboard WiFi must be enabled via"
echo "  dietpi-config -> Advanced -> WiFi before first use."
fi
echo ""
echo "  Reboot required: sudo reboot"
