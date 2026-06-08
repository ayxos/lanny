"""Live traffic monitor (a lightweight, honest 'sniffer').

What this CAN do, reliably and without root:
  * enumerate THIS host's active TCP/UDP connections via psutil, every tick,
  * attribute each to its owning process,
  * classify the flow by service/protocol (HTTPS, DNS, SSH, ...),
  * resolve the remote host (reverse DNS, cached).

What it CANNOT do (physics of a switched LAN, not a bug):
  * see other devices' traffic — a switch only forwards their frames to their
    own ports; capturing that needs port-mirroring or a tap (Wireshark has the
    same limitation),
  * label flows as "ajax/XHR" — that's a browser-layer concept and HTTPS
    payloads are encrypted, so on the wire we only know the service/protocol.

`stream()` yields a snapshot of current connections each interval.
"""
from __future__ import annotations

import socket
import time
from typing import Iterator, Optional

import psutil

# remote-port -> service label
SERVICES = {
    20: "FTP-data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 67: "DHCP", 68: "DHCP", 80: "HTTP", 110: "POP3",
    123: "NTP", 137: "NetBIOS", 138: "NetBIOS", 139: "NetBIOS",
    143: "IMAP", 161: "SNMP", 443: "HTTPS", 445: "SMB", 465: "SMTPS",
    587: "SMTP", 631: "IPP", 853: "DNS-over-TLS", 993: "IMAPS",
    995: "POP3S", 1883: "MQTT", 1900: "SSDP/UPnP", 3306: "MySQL",
    3389: "RDP", 5060: "SIP", 5353: "mDNS", 5900: "VNC", 8080: "HTTP",
    8443: "HTTPS", 8883: "MQTTS", 9100: "Printer", 32400: "Plex",
}

_dns_cache: dict[str, str] = {}


def _service(raddr, laddr) -> str:
    for a in (raddr, laddr):
        if a and a.port in SERVICES:
            return SERVICES[a.port]
    p = raddr.port if raddr else (laddr.port if laddr else 0)
    return f"port {p}" if p else "—"


def _rdns(ip: str) -> str:
    if not ip or ip in ("127.0.0.1", "0.0.0.0", "::1"):
        return ""
    if ip in _dns_cache:
        return _dns_cache[ip]
    socket.setdefaulttimeout(0.3)
    try:
        name = socket.gethostbyaddr(ip)[0]
    except OSError:
        name = ""
    finally:
        socket.setdefaulttimeout(None)
    _dns_cache[ip] = name
    return name


def snapshot() -> list[dict]:
    """One pass over the host's current inet connections."""
    rows: list[dict] = []
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError):
        return rows

    # pid -> process name (one lookup per pid per snapshot)
    pnames: dict[int, str] = {}

    for c in conns:
        proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
        laddr = c.laddr if c.laddr else None
        raddr = c.raddr if c.raddr else None
        # skip pure listeners with no peer for a cleaner "activity" view
        if not raddr and c.status == psutil.CONN_LISTEN:
            continue

        pid = c.pid or 0
        if pid and pid not in pnames:
            try:
                pnames[pid] = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pnames[pid] = "?"
        rows.append({
            "proto": proto,
            "service": _service(raddr, laddr),
            "local": f"{laddr.ip}:{laddr.port}" if laddr else "",
            "remote": f"{raddr.ip}:{raddr.port}" if raddr else "",
            "remote_ip": raddr.ip if raddr else "",
            "remote_host": _rdns(raddr.ip) if raddr else "",
            "status": c.status,
            "pid": pid,
            "process": pnames.get(pid, ""),
        })

    # stable-ish ordering: active first, then by process
    rows.sort(key=lambda r: (r["status"] != "ESTABLISHED", r["process"], r["remote"]))
    return rows


def stream(interval: float = 2.0, max_ticks: int = 1800) -> Iterator[dict]:
    """Yield {type:'snapshot', items, ts, count} every `interval` seconds.

    Stops when the client disconnects (broken pipe) or max_ticks is hit."""
    tick = 0
    while tick < max_ticks:
        items = snapshot()
        yield {"type": "snapshot", "count": len(items), "items": items,
               "tick": tick}
        tick += 1
        time.sleep(interval)
