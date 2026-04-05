#!/bin/bash
# Netzwerk-Setup: Raspberry Pi als WiFi Access Point mit Captive Portal
set -e

AP_INTERFACE="wlan0"
INET_INTERFACE="eth0"
AP_IP="192.168.4.1"
AP_SUBNET="192.168.4.0/24"
DHCP_RANGE_START="192.168.4.10"
DHCP_RANGE_END="192.168.4.100"
SSID="Zeitmaschine"
WPA_PASSPHRASE="zeitreise"
HOSTNAME="zeitmaschine"

echo "=== 56k WiFi Zeitmaschine - Netzwerk-Setup ==="

# Pakete installieren
echo "[1/6] Installiere benoetigte Pakete..."
apt-get update -qq
apt-get install -y -qq hostapd dnsmasq iptables avahi-daemon

# Hostname setzen fuer mDNS
echo "[2/6] Setze Hostname auf '${HOSTNAME}'..."
hostnamectl set-hostname "$HOSTNAME"
if ! grep -q "${HOSTNAME}" /etc/hosts; then
    sed -i "s/127.0.1.1.*/127.0.1.1\t${HOSTNAME}/" /etc/hosts
fi

# Avahi fuer .local Hostname-Aufloesung konfigurieren
cat > /etc/avahi/avahi-daemon.conf << 'AVAHI'
[server]
host-name=zeitmaschine
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

systemctl enable avahi-daemon
systemctl restart avahi-daemon

# hostapd konfigurieren
echo "[3/6] Konfiguriere hostapd (Access Point)..."
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

# hostapd Default-Config setzen
sed -i 's|^#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || true
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > /etc/default/hostapd

# Statische IP fuer wlan0
echo "[4/6] Konfiguriere statische IP fuer ${AP_INTERFACE}..."
if ! grep -q "interface ${AP_INTERFACE}" /etc/dhcpcd.conf 2>/dev/null; then
    cat >> /etc/dhcpcd.conf << DHCPCD

interface ${AP_INTERFACE}
    static ip_address=${AP_IP}/24
    nohook wpa_supplicant
DHCPCD
fi

# dnsmasq konfigurieren (DHCP + DNS mit Captive-Portal-Redirect)
echo "[5/6] Konfiguriere dnsmasq (DHCP + DNS)..."
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
cat > /etc/dnsmasq.conf << DNSMASQ
# Interface
interface=${AP_INTERFACE}
bind-interfaces

# DHCP
dhcp-range=${DHCP_RANGE_START},${DHCP_RANGE_END},255.255.255.0,24h
dhcp-option=option:router,${AP_IP}
dhcp-option=option:dns-server,${AP_IP}

# DNS: Alle Anfragen an den Pi leiten (Captive Portal)
# Ausnahme: web.archive.org muss aufgeloest werden
server=8.8.8.8
server=8.8.4.4

# Captive Portal Detection - wichtig fuer automatische Erkennung
address=/connectivitycheck.gstatic.com/${AP_IP}
address=/clients3.google.com/${AP_IP}
address=/captive.apple.com/${AP_IP}
address=/www.apple.com/${AP_IP}
address=/detectportal.firefox.com/${AP_IP}
address=/msftconnecttest.com/${AP_IP}
address=/www.msftconnecttest.com/${AP_IP}
address=/nmcheck.gnome.org/${AP_IP}

# Lokaler Hostname
address=/zeitmaschine.local/${AP_IP}
DNSMASQ

# IP-Forwarding und iptables
echo "[6/6] Konfiguriere IP-Forwarding und Firewall..."
sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf
sysctl -w net.ipv4.ip_forward=1

# iptables-Regeln: NAT + Captive Portal Redirect
iptables -t nat -F
iptables -F FORWARD

# NAT fuer Internetzugang
iptables -t nat -A POSTROUTING -o ${INET_INTERFACE} -j MASQUERADE
iptables -A FORWARD -i ${INET_INTERFACE} -o ${AP_INTERFACE} -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i ${AP_INTERFACE} -o ${INET_INTERFACE} -j ACCEPT

# HTTP-Traffic auf Captive Portal umleiten (Port 80 -> Portal auf 8080)
# Ausnahme: Traffic vom Pi selbst und bereits authentifizierte Clients
iptables -t nat -A PREROUTING -i ${AP_INTERFACE} -p tcp --dport 80 -j DNAT --to-destination ${AP_IP}:8080
# HTTPS Captive-Portal-Detection umleiten
iptables -t nat -A PREROUTING -i ${AP_INTERFACE} -p tcp --dport 443 -j DNAT --to-destination ${AP_IP}:8080

# iptables persistent machen
mkdir -p /etc/iptables
iptables-save > /etc/iptables/rules.v4

# Dienste aktivieren
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

echo ""
echo "=== Netzwerk-Setup abgeschlossen ==="
echo "SSID:       ${SSID}"
echo "Passwort:   ${WPA_PASSPHRASE}"
echo "Portal-IP:  ${AP_IP}"
echo "Hostname:   ${HOSTNAME}.local"
echo ""
echo "Bitte den Pi neu starten: sudo reboot"
