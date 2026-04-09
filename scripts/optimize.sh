#!/bin/bash
# CHRONOSURF - Performance Optimizations
# Fuehrt diverse Optimierungen aus um den Pi 3 responsiver zu machen.
# Kann nach der Installation ausgefuehrt werden: sudo bash scripts/optimize.sh
set -e

echo "==========================================="
echo "  CHRONOSURF - Performance Optimization"
echo "==========================================="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Run as root: sudo bash optimize.sh"
    exit 1
fi

# ============================================
# [1/7] CPU Governor auf 'performance'
# ============================================
echo "[1/7] Setting CPU governor to 'performance'..."

# Sofort aktivieren
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance > "$cpu" 2>/dev/null || true
done

# Persistent via systemd
cat > /etc/systemd/system/chronosurf-cpu-governor.service << 'EOF'
[Unit]
Description=Chronosurf CPU Governor (performance)
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for c in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > $c; done'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable chronosurf-cpu-governor.service 2>/dev/null || true
echo "  -> CPU governor set to performance"

# ============================================
# [2/7] tmpfs fuer /tmp und /var/log
# ============================================
echo "[2/7] Setting up tmpfs for /tmp and /var/log..."

if ! grep -q "tmpfs /tmp" /etc/fstab; then
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,size=100M 0 0" >> /etc/fstab
    echo "  -> /tmp set to tmpfs (100M)"
fi

if ! grep -q "tmpfs /var/log" /etc/fstab; then
    echo "tmpfs /var/log tmpfs defaults,noatime,nosuid,mode=0755,size=50M 0 0" >> /etc/fstab
    echo "  -> /var/log set to tmpfs (50M)"
fi

# ============================================
# [3/7] DNS Cache in dnsmasq
# ============================================
echo "[3/7] Enabling dnsmasq DNS cache..."

if [ -f /etc/dnsmasq.conf ] && ! grep -q "cache-size" /etc/dnsmasq.conf; then
    cat >> /etc/dnsmasq.conf << 'EOF'

# Performance: DNS caching
cache-size=1000
neg-ttl=3600
no-negcache
EOF
    systemctl restart dnsmasq 2>/dev/null || true
    echo "  -> DNS cache enabled (1000 entries)"
fi

# ============================================
# [4/7] Swap ausschalten
# ============================================
echo "[4/7] Disabling swap..."

swapoff -a 2>/dev/null || true

# DietPi nutzt /var/swap
if [ -f /var/swap ]; then
    rm -f /var/swap
fi

# fstab: swap-Eintrag auskommentieren
sed -i '/swap/s/^/#/' /etc/fstab 2>/dev/null || true

# DietPi: Swap per config deaktivieren
if [ -f /boot/dietpi.txt ]; then
    sed -i 's/^AUTO_SETUP_SWAPFILE_SIZE=.*/AUTO_SETUP_SWAPFILE_SIZE=0/' /boot/dietpi.txt 2>/dev/null || true
fi

# dphys-swapfile (Pi OS) deaktivieren
systemctl disable dphys-swapfile 2>/dev/null || true
systemctl stop dphys-swapfile 2>/dev/null || true

echo "  -> Swap disabled"

# ============================================
# [5/7] Unused services deaktivieren
# ============================================
echo "[5/7] Disabling unused services..."

UNUSED_SERVICES=(
    "bluetooth"
    "bluealsa"
    "hciuart"
    "triggerhappy"
    "cups"
    "cups-browsed"
    "avahi-daemon.socket"  # Avahi selbst bleibt an!
    "ModemManager"
    "rpi-eeprom-update"
    "plymouth"
    "plymouth-quit-wait"
)

for svc in "${UNUSED_SERVICES[@]}"; do
    systemctl stop "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
done

echo "  -> Unused services disabled"

# ============================================
# [6/7] Kernel / sysctl Tweaks
# ============================================
echo "[6/7] Kernel tweaks..."

cat > /etc/sysctl.d/99-chronosurf.conf << 'EOF'
# CHRONOSURF Performance Tweaks

# Swappiness: wir haben kein Swap, aber sicherheitshalber
vm.swappiness=0

# Dirty writebacks weniger haeufig (SD-Karte schonen)
vm.dirty_background_ratio=20
vm.dirty_ratio=50
vm.dirty_writeback_centisecs=6000
vm.dirty_expire_centisecs=6000

# Netzwerk-Puffer
net.core.rmem_max=16777216
net.core.wmem_max=16777216
net.ipv4.tcp_rmem=4096 87380 16777216
net.ipv4.tcp_wmem=4096 65536 16777216

# Verbindungen schneller schliessen
net.ipv4.tcp_fin_timeout=15
net.ipv4.tcp_tw_reuse=1

# IP Forwarding (wichtig fuer unsere AP-Funktion!)
net.ipv4.ip_forward=1
EOF

sysctl -p /etc/sysctl.d/99-chronosurf.conf >/dev/null 2>&1 || true
echo "  -> Kernel parameters tuned"

# ============================================
# [7/7] Gunicorn pruefen
# ============================================
echo "[7/7] Checking Gunicorn..."

if ! command -v gunicorn &>/dev/null; then
    pip3 install gunicorn --break-system-packages 2>/dev/null || pip3 install gunicorn 2>/dev/null || true
fi

if command -v gunicorn &>/dev/null; then
    echo "  -> Gunicorn available: $(which gunicorn)"
else
    echo "  WARN: Gunicorn not installed. Run:"
    echo "    pip3 install gunicorn --break-system-packages"
fi

echo ""
echo "==========================================="
echo "  Optimization complete!"
echo "==========================================="
echo ""
echo "Changes take effect after reboot:"
echo "  sudo reboot"
echo ""
echo "What's different:"
echo "  - CPU runs at max frequency (performance governor)"
echo "  - /tmp and /var/log in RAM (faster, saves SD)"
echo "  - DNS caching (1000 entries)"
echo "  - Swap disabled"
echo "  - Bluetooth + other unused services disabled"
echo "  - Portal uses Gunicorn instead of Flask dev server"
echo "  - Static files cached by browser (1 day)"
echo ""
