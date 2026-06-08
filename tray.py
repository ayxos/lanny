"""Lanny tray launcher (Windows tray / macOS menubar / Linux indicator).

What it does:
  * Starts the Flask backend on 127.0.0.1:<PORT> in a daemon thread.
  * Shows a tray icon. Its menu reveals live network info
    (interface, your IP, gateway, subnet, host count, last-scan count).
  * "Open scanner" launches the web UI in the default browser.
  * "Quick scan" runs a scan in the background and updates the device count.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from typing import Optional

from PIL import Image, ImageDraw

import app as web_app
import netscan

# pystray's import touches the system tray backend (X11 on Linux, NSApp on
# macOS, the shell on Windows). On a headless Linux box (no DISPLAY) it raises
# at import time, so we defer it and fall back to web-only mode.
try:
    import pystray
    from pystray import Menu, MenuItem as Item
    _TRAY_OK = True
    _TRAY_ERR = ""
except Exception as _e:  # pragma: no cover - environment-dependent
    pystray = None  # type: ignore[assignment]
    _TRAY_OK = False
    _TRAY_ERR = f"{type(_e).__name__}: {_e}"


PORT = int(os.environ.get("LANNY_PORT") or os.environ.get("FING_PORT", "5050"))
HOST = "127.0.0.1"

_state = {
    "net": None,                  # Optional[netscan.NetInfo]
    "last_scan_count": None,      # Optional[int]
    "last_scan_at": None,         # Optional[float]
    "scanning": False,
}


# ---------- icon ----------

def make_icon(active: bool = False) -> Image.Image:
    """64×64 RGBA wifi-arc icon. Lights up green when scanning."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (0, 195, 137, 255) if active else (235, 235, 235, 255)
    cx, cy = size // 2, size // 2 + 10
    for r in (22, 14, 6):
        d.arc((cx - r, cy - r, cx + r, cy + r),
              start=210, end=330, fill=color, width=5)
    d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=color)
    return img


# ---------- background flask ----------

def start_flask() -> None:
    t = threading.Thread(
        target=web_app.run, kwargs={"host": HOST, "port": PORT}, daemon=True,
    )
    t.start()
    # Wait briefly so the first browser hit succeeds.
    for _ in range(40):
        try:
            with socket.create_connection((HOST, PORT), timeout=0.1):
                return
        except OSError:
            time.sleep(0.1)


# ---------- helpers ----------

def refresh_network() -> None:
    _state["net"] = netscan.detect_network()


def _net_field(field: str) -> str:
    n = _state["net"]
    if not n:
        return "—"
    return str(getattr(n, field, "—"))


def _last_scan_label() -> str:
    c, when = _state["last_scan_count"], _state["last_scan_at"]
    if c is None or when is None:
        return "Last scan: never"
    ago = int(time.time() - when)
    return f"Last scan: {c} device(s), {ago}s ago"


def open_scanner(icon=None, item=None) -> None:
    webbrowser.open(f"http://{HOST}:{PORT}/")


def quick_scan(icon: "pystray.Icon", item=None) -> None:
    if _state["scanning"]:
        return
    _state["scanning"] = True
    icon.icon = make_icon(active=True)
    icon.update_menu()

    def worker():
        try:
            refresh_network()
            n = _state["net"]
            if not n:
                return
            count = 0
            for ev in netscan.scan_network_stream(n):
                if ev["type"] == "device":
                    count += 1
            _state["last_scan_count"] = count
            _state["last_scan_at"] = time.time()
        finally:
            _state["scanning"] = False
            icon.icon = make_icon(active=False)
            icon.update_menu()

    threading.Thread(target=worker, daemon=True).start()


def quit_app(icon: "pystray.Icon", item=None) -> None:
    icon.stop()
    os._exit(0)


# ---------- menu (dynamic via callable labels) ----------

def build_menu():
    assert _TRAY_OK  # only called when pystray is available
    # Each line refreshes the cached NetInfo before the first row reads.
    def refresh_then_iface(_):
        refresh_network()
        return f"Interface: {_net_field('interface')}"

    return Menu(
        Item(refresh_then_iface, None, enabled=False),
        Item(lambda _: f"Your IP:   {_net_field('ip')}", None, enabled=False),
        Item(lambda _: f"Gateway:   {_net_field('gateway')}", None, enabled=False),
        Item(lambda _: f"Subnet:    {_net_field('cidr')}", None, enabled=False),
        Item(lambda _: f"Hosts:     {_net_field('host_count')}", None, enabled=False),
        Menu.SEPARATOR,
        Item(lambda _: _last_scan_label(), None, enabled=False),
        Menu.SEPARATOR,
        Item(
            lambda _: "Scanning…" if _state["scanning"] else "Quick scan",
            quick_scan,
            enabled=lambda _: not _state["scanning"],
        ),
        Item("Open scanner", open_scanner, default=True),
        Menu.SEPARATOR,
        Item("Quit", quit_app),
    )


# ---------- entry ----------

def _print_banner() -> None:
    n = _state["net"]
    print("=" * 58)
    print("  Lanny — LAN scanner")
    print(f"  Web UI:  http://{HOST}:{PORT}/")
    if n:
        print(f"  Network: {n.cidr}  gateway={n.gateway}  iface={n.interface}")
    print("=" * 58)


def run_webonly() -> None:
    """Fallback for environments where a tray icon can't be created."""
    print(f"[tray] disabled ({_TRAY_ERR or 'no system tray available'}) "
          "— running web-only.")
    refresh_network()
    _print_banner()
    # web_app.run() blocks — bind to all interfaces so it's reachable.
    web_app.run(host="0.0.0.0", port=PORT)


def main() -> None:
    if not _TRAY_OK or os.environ.get("LANNY_NO_TRAY") or os.environ.get("FING_NO_TRAY"):
        run_webonly()
        return

    start_flask()
    refresh_network()
    _print_banner()

    icon = pystray.Icon(
        "lanny",
        icon=make_icon(),
        title="Lanny — LAN scanner",
        menu=build_menu(),
    )
    icon.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
