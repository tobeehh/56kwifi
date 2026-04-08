# CHRONOSURF

```
 ██████╗██╗  ██╗██████╗  ██████╗ ███╗   ██╗ ██████╗ ███████╗██╗   ██╗██████╗ ███████╗
██╔════╝██║  ██║██╔══██╗██╔═══██╗████╗  ██║██╔═══██╗██╔════╝██║   ██║██╔══██╗██╔════╝
██║     ███████║██████╔╝██║   ██║██╔██╗ ██║██║   ██║███████╗██║   ██║██████╔╝█████╗
██║     ██╔══██║██╔══██╗██║   ██║██║╚██╗██║██║   ██║╚════██║██║   ██║██╔══██╗██╔══╝
╚██████╗██║  ██║██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝███████║╚██████╔╝██║  ██║██║
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝
```

**Surf the Timeline.** A Raspberry Pi 3 powered time machine that lets you
browse the internet of any year from 1996 to 2025 through the Wayback Machine.

**Recommended base image: [DietPi](https://dietpi.com/)** (minimal Debian,
~130MB RAM idle). Also works on Raspberry Pi OS.

## How It Works

1. Connect to WiFi **"CHRONOSURF"**
2. Captive portal opens automatically
3. Pick a year on the timeline
4. Hit **DIAL IN** — hear the 56k modem sound
5. Browse the web as it was

Each device gets its own year. Multiple time travelers can surf different
eras simultaneously.

## Features

- **Captive Portal** with retro terminal UI and BIOS boot sequence
- **5 Epoch Themes** that change with the selected year:
  - 90s: phosphor-green CRT terminal
  - Y2K: electric blue matrix
  - Web 2.0: warm orange glossy
  - Social: neon on dark blue
  - Modern: minimal dark
- **Interactive Timeline** slider with epoch markers
- **Warp Animation** during connection with progress bar
- **Curated Favorites** per epoch (GeoCities, MySpace, StudiVZ...)
- **56k Modem Sound** via passive buzzer on connect/disconnect
- **Per-Device State** via MAC address (each device = own year)
- **Statistics Page** with global telemetry and personal logbook
- **LCD 20x4 Display** with rotary encoder for hardware control
- **Hostname Access** via `chronosurf.local` (mDNS/Avahi)

## Hardware

| Component              | Connection          |
|------------------------|---------------------|
| Encoder 1 CLK (Year)   | GPIO 17             |
| Encoder 1 DT (Year)    | GPIO 18             |
| Encoder 1 BTN (Year)   | GPIO 27             |
| Encoder 2 CLK (Speed)  | GPIO 5              |
| Encoder 2 DT (Speed)   | GPIO 6              |
| Encoder 2 BTN (Speed)  | GPIO 13             |
| Passive Buzzer          | GPIO 22             |
| LCD 20x4 SDA           | GPIO 2 (I2C SDA)    |
| LCD 20x4 SCL           | GPIO 3 (I2C SCL)    |
| LCD 20x4 I2C Addr      | 0x27 (or 0x3F)      |

## Install

### Quick Setup (empfohlen) - Zero Touch

1. [DietPi Image](https://dietpi.com/) fuer Raspberry Pi 3 auf microSD flashen
2. SD-Karte am PC mounten und auf der Boot-Partition:
   - `dietpi.txt` oeffnen, diese Werte setzen:
     ```
     AUTO_SETUP_AUTOMATED=1
     AUTO_SETUP_GLOBAL_PASSWORD=chronosurf
     AUTO_SETUP_NET_ETHERNET_ENABLED=1
     AUTO_SETUP_NET_WIFI_ENABLED=1
     CONFIG_I2C_STATE=1
     ```
   - `firstboot/Automation_Custom_Script.sh` aus diesem Repo
     nach `/boot/Automation_Custom_Script.sh` kopieren
3. SD einsetzen, Ethernet anschliessen, Strom an
4. Warten (~5-10 Min) - DietPi installiert alles automatisch
5. Pi startet neu - CHRONOSURF laeuft!

### Manuell (DietPi)

1. Flash [DietPi](https://dietpi.com/) for Raspberry Pi 3
2. Boot, connect via Ethernet, complete initial setup
3. Enable WiFi and I2C:
   ```bash
   dietpi-config
   # -> Advanced Options -> WiFi -> On
   # -> Advanced Options -> I2C -> On
   ```
4. Install CHRONOSURF:
   ```bash
   git clone https://github.com/tobeehh/56kwifi.git
   cd 56kwifi
   sudo bash install.sh
   sudo reboot
   ```

### Raspberry Pi OS

```bash
git clone https://github.com/tobeehh/56kwifi.git
cd 56kwifi
sudo bash install.sh
sudo reboot
```

The installer auto-detects DietPi vs Pi OS and adjusts network config
(ifupdown vs dhcpcd), package sources, and pip installation accordingly.

## Access

| What       | Where                                    |
|------------|------------------------------------------|
| Portal     | http://chronosurf.local                  |
| Stats      | http://chronosurf.local/stats            |
| API Status | http://chronosurf.local/status           |
| Set Year   | http://chronosurf.local/set?year=1999    |
| IP         | 192.168.4.1                              |

## Architecture

```
chronosurf/
├── install.sh              # One-command setup
├── requirements.txt        # Python deps
├── scripts/
│   └── setup_network.sh    # WiFi AP, DHCP, DNS, iptables, Avahi
├── portal/
│   ├── app.py              # Flask portal + per-MAC state + stats
│   ├── templates/
│   │   ├── index.html      # Main UI (boot sequence, timeline, favorites)
│   │   └── stats.html      # Statistics dashboard
│   └── static/
│       └── style.css       # 5 epoch themes + animations
├── proxy/
│   └── wayback_proxy.py    # HTTP proxy -> Wayback Machine (per-MAC)
├── hardware/
│   ├── controller.py       # Rotary encoder + LCD 20x4 + button
│   └── buzzer.py           # 56k modem dial-up sound synthesis
└── systemd/                # 3 service files
```
