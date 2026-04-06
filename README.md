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
- **OLED Display** with rotary encoder for hardware control
- **Hostname Access** via `chronosurf.local` (mDNS/Avahi)

## Hardware

| Component         | Connection     |
|--------------------|---------------|
| Rotary Encoder CLK | GPIO 17       |
| Rotary Encoder DT  | GPIO 18       |
| Rotary Button      | GPIO 27       |
| Passive Buzzer     | GPIO 22       |
| SSD1306 SDA        | GPIO 2 (I2C)  |
| SSD1306 SCL        | GPIO 3 (I2C)  |

## Install

```bash
sudo bash install.sh
sudo reboot
```

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
│   ├── controller.py       # Rotary encoder + OLED + button
│   └── buzzer.py           # 56k modem dial-up sound synthesis
└── systemd/                # 3 service files
```
