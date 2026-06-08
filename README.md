# Lanny

A local-first LAN scanner and network toolkit. Discover devices on your network, run health checks, monitor your own traffic, wake machines remotely, and jump into SSH — all from a clean web UI that never phones home.

Inspired by tools like Fing, but built to run entirely on your machine.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg" alt="Cross-platform" />
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT" />
</p>

---

## Features

| | |
|---|---|
| **Device discovery** | Scan your subnet with concurrent ping + ARP lookup. Shows IP, MAC, vendor (OUI), hostname, and device type. |
| **Port scan** | Probe common ports on any discovered host and map them to known services. |
| **Network health** | Speed test, latency to gateway and public DNS, DNS resolver checks, Wi-Fi info (where the OS exposes it), and a heuristic security score. |
| **Traffic monitor** | Live view of *this machine's* active TCP/UDP connections, attributed to processes and classified by protocol. |
| **Wake-on-LAN** | Send magic packets to sleeping devices. Save MAC addresses so you can wake them even when they're offline. |
| **SSH shortcuts** | Mines your shell history for frequently-used SSH targets and can open a terminal session with one click (localhost only). |
| **System tray** | Runs quietly in the menu bar / system tray with quick-scan and open-browser actions. |
| **Dark mode** | Light and dark themes, remembered in the browser. |

Everything runs on `127.0.0.1` — no accounts, no cloud, no telemetry.

---

## Quick start

**Requirements:** Python 3.10+ and the usual system tools (`ping`, `arp`). On Linux you may need `ip` or `arp` in your `PATH`.

### macOS / Linux

```bash
git clone git@github.com:ayxos/lanny.git
cd lanny
./run.sh
```

### Windows

```bat
git clone git@github.com:ayxos/lanny.git
cd lanny
run.bat
```

The launcher creates a `.venv`, installs dependencies on first run, and starts the tray app. Open the UI at:

**http://127.0.0.1:5050**

Or click **Open scanner** from the tray icon.

### Manual setup

```bash
python3 -m venv .venv
source .venv/bin/activate      # .venv\Scripts\activate on Windows
pip install -r requirements.txt
python tray.py                 # tray + web UI
# or
python app.py                  # web UI only (listens on 0.0.0.0:5050)
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `LANNY_PORT` / `FING_PORT` | `5050` | Port for the web UI |
| `LANNY_HOME` | `~/.lanny` | Directory for saved devices and local data |
| `PORT` | `5050` | Port when running `python app.py` directly |

---

## How it works

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────────────┐
│  tray.py    │────▶│   app.py     │────▶│  Browser UI (Flask)     │
│  (pystray)  │     │   (Flask)    │     │  http://127.0.0.1:5050  │
└─────────────┘     └──────┬───────┘     └─────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
     netscan.py       nettest.py        sniffer.py
     (discovery)      (health checks)   (local connections)
          │                │                │
          ▼                ▼                ▼
     sshhist.py        store.py         sshlaunch.py
     (SSH history)     (saved WoL)      (open terminal)
```

- **Discovery** uses `psutil` for interface info and concurrent system `ping` for liveness, then reads the ARP table for MAC addresses and resolves vendor names from a bundled OUI database.
- **Health checks** stream results over Server-Sent Events as each test completes — speed uses Cloudflare's edge, latency uses system ping, DNS checks look for hijacking and NXDOMAIN behaviour.
- **Traffic monitor** lists connections on *your* host via `psutil`. It cannot see other devices' traffic on a switched LAN (that would need port mirroring or a tap — same limitation as Wireshark on a normal network).
- **Saved devices** are stored in `~/.lanny/devices.json` so Wake-on-LAN still works when a machine is asleep and invisible to the scanner.

---

## Building a standalone app

PyInstaller specs are included for macOS and Windows:

```bash
pip install pyinstaller
# from the build/ directory:
./build_mac.sh          # macOS
# or on Windows:
pyinstaller build\lanny.spec
```

The resulting `Lanny` app bundles the web UI, OUI database, and tray launcher — no Python install required on the target machine.

---

## Project layout

```
lanny/
├── app.py              # Flask web server and API routes
├── tray.py             # System tray launcher
├── netscan.py          # Network discovery, port scan, Wake-on-LAN
├── nettest.py          # Health and security checks
├── sniffer.py          # Local connection monitor
├── sshhist.py          # SSH history mining
├── sshlaunch.py        # Open SSH in a terminal (localhost only)
├── store.py            # Saved device persistence
├── oui.py / oui.tsv    # MAC vendor lookup
├── templates/          # Web UI (HTML)
├── static/             # CSS and JavaScript
├── build/              # PyInstaller specs and build scripts
├── run.sh / run.bat    # One-click launchers
└── requirements.txt
```

---

## API overview

All endpoints are served by the local Flask app:

| Endpoint | Method | Description |
|---|---|---|
| `/api/network` | GET | Current interface, IP, gateway, subnet |
| `/api/scan` | GET (SSE) | Stream a full network scan |
| `/api/portscan?ip=` | GET | Port scan a host |
| `/api/health` | GET (SSE) | Stream health check results |
| `/api/sniff?interval=` | GET (SSE) | Stream local connection snapshots |
| `/api/wol?mac=` | GET | Send a Wake-on-LAN packet |
| `/api/saved` | GET/POST/DELETE | Manage saved devices |
| `/api/ssh-history` | GET | Ranked SSH targets from shell history |
| `/api/ssh-launch` | POST | Open SSH in a terminal (localhost only) |

---

## Limitations & notes

- **WSL:** Network scanning and Wi-Fi info are limited inside WSL because it does not have direct access to the host's network interfaces. Run Lanny on the host OS for full functionality.
- **Headless Linux:** If no display server is available, the tray icon is skipped and only the web UI runs.
- **Security checks** are heuristic (open ports on the gateway, DNS hijack tests) — not a replacement for a proper vulnerability scanner or antivirus.
- **SSH launch** is restricted to `127.0.0.1` requests to prevent remote code execution from the network.

---

## License

MIT

---

<p align="center">
  <sub>Local-only · No data leaves your machine</sub>
</p>
