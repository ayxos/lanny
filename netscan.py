"""Cross-platform network discovery (Linux, macOS, Windows).

Strategy:
  * `psutil` for interface IPv4 + netmask + MAC, identical across OSes.
  * Default gateway:
      - Linux:   /proc/net/route (no extra deps)
      - macOS:   `route -n get default`
      - Windows: `ipconfig` parse (and a socket-trick fallback)
  * Liveness: concurrent system `ping` with OS-correct flags.
  * MAC for remote hosts: parse `arp -a` (works on all three OSes).
  * Reverse DNS: socket.gethostbyaddr with short timeout.
"""
from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Iterator, Optional

import psutil

from oui import lookup_vendor

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


# ---------- helpers ----------

def _run(cmd: list[str], timeout: float = 5.0) -> str:
    try:
        kw = {}
        if IS_WIN:
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
            **kw,
        )
        return (out.stdout or "") + (out.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _normalize_mac(mac: str) -> str:
    """Normalize various MAC formats to 'aa:bb:cc:dd:ee:ff'."""
    if not mac:
        return ""
    hexstr = re.sub(r"[^0-9a-fA-F]", "", mac).lower()
    if len(hexstr) != 12:
        return ""
    return ":".join(hexstr[i:i+2] for i in range(0, 12, 2))


# ---------- network info ----------

@dataclass
class NetInfo:
    interface: str
    ip: str
    mac: str
    netmask: str
    cidr: str
    gateway: str
    network: str
    broadcast: str
    host_count: int


def _default_gateway() -> tuple[str, str]:
    """Return (gateway_ip, interface_name) or ('','')."""
    if IS_LINUX:
        try:
            with open("/proc/net/route") as f:
                next(f, None)
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[1] == "00000000":
                        gw_hex = parts[2]
                        gw = ".".join(str(int(gw_hex[i:i+2], 16)) for i in (6, 4, 2, 0))
                        return gw, parts[0]
        except OSError:
            pass

    if IS_MAC:
        out = _run(["route", "-n", "get", "default"])
        gw = re.search(r"gateway:\s+(\S+)", out)
        iface = re.search(r"interface:\s+(\S+)", out)
        if gw and iface:
            return gw.group(1), iface.group(1)

    if IS_WIN:
        # Pull from `ipconfig` — find the first adapter with a Default Gateway.
        out = _run(["ipconfig"])
        current_iface = ""
        for line in out.splitlines():
            head = re.match(r"^([A-Za-z].+adapter\s+(.+?)):", line)
            if head:
                current_iface = head.group(2).strip()
                continue
            m = re.search(r"Default Gateway[. ]*:\s*(\d+\.\d+\.\d+\.\d+)", line)
            if m:
                return m.group(1), current_iface

    # Last-ditch fallback: connect-trick to infer local IP, then guess /24
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local = s.getsockname()[0]
        s.close()
        gw = local.rsplit(".", 1)[0] + ".1"
        return gw, ""
    except OSError:
        return "", ""


def detect_network() -> Optional[NetInfo]:
    gw, iface_hint = _default_gateway()
    if not gw:
        return None
    gw_obj = ipaddress.IPv4Address(gw)

    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()

    # Find the interface whose subnet contains the gateway and that is UP.
    for iface, snics in addrs.items():
        if iface in stats and not stats[iface].isup:
            continue
        ip4 = None
        mac = ""
        for s in snics:
            fam = s.family
            if fam == socket.AF_INET:
                ip4 = (s.address, s.netmask)
            elif (IS_WIN and fam == getattr(psutil, "AF_LINK", -1)) \
                 or (not IS_WIN and fam == getattr(psutil, "AF_LINK", 17)) \
                 or fam == getattr(psutil, "AF_LINK", None):
                mac = _normalize_mac(s.address)
        if not ip4 or not ip4[0] or not ip4[1]:
            continue
        addr, mask = ip4
        try:
            net = ipaddress.IPv4Network(f"{addr}/{mask}", strict=False)
        except ValueError:
            continue
        if gw_obj in net:
            return NetInfo(
                interface=iface,
                ip=addr,
                mac=mac,
                netmask=mask,
                cidr=str(net),
                gateway=gw,
                network=str(net.network_address),
                broadcast=str(net.broadcast_address),
                host_count=max(net.num_addresses - 2, 0),
            )
    return None


# ---------- pinging ----------

def _ping_cmd(ip: str) -> list[str]:
    if IS_WIN:
        return ["ping", "-n", "1", "-w", "800", ip]
    if IS_MAC:
        return ["ping", "-c", "1", "-W", "800", ip]
    # Linux
    return ["ping", "-c", "1", "-W", "1", "-w", "2", ip]


def ping_host(ip: str) -> bool:
    try:
        kw = {}
        if IS_WIN:
            kw["creationflags"] = 0x08000000
        out = subprocess.run(
            _ping_cmd(ip), capture_output=True, text=True, timeout=3, **kw,
        )
        if out.returncode != 0:
            return False
        # Windows returns 0 even when host is unreachable — verify the output.
        if IS_WIN:
            return "TTL=" in out.stdout or "ttl=" in out.stdout
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------- ARP / neighbor table ----------

def read_arp_table() -> dict[str, str]:
    """Map ip -> mac across OSes by parsing `arp -a` / `ip neigh`."""
    table: dict[str, str] = {}

    if IS_LINUX:
        out = _run(["ip", "neigh", "show"])
        for line in out.splitlines():
            m = re.match(r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+\S+\s+lladdr\s+([0-9a-f:]{17})", line)
            if m:
                table[m.group(1)] = m.group(2).lower()
        if not table:
            try:
                with open("/proc/net/arp") as f:
                    next(f, None)
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                            table[parts[0]] = parts[3].lower()
            except OSError:
                pass

    if IS_MAC:
        out = _run(["arp", "-a"])
        # "? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]"
        for line in out.splitlines():
            m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\) at ([0-9a-fA-F:]+)", line)
            if m:
                mac = _normalize_mac(m.group(2))
                if mac:
                    table[m.group(1)] = mac

    if IS_WIN:
        out = _run(["arp", "-a"])
        # "  192.168.1.1     aa-bb-cc-dd-ee-ff     dynamic"
        for line in out.splitlines():
            m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s+(dynamic|static)",
                         line)
            if m:
                mac = _normalize_mac(m.group(2))
                if mac:
                    table[m.group(1)] = mac

    return table


# ---------- reverse DNS ----------

def reverse_dns(ip: str, timeout: float = 0.5) -> str:
    socket.setdefaulttimeout(timeout)
    try:
        host, _, _ = socket.gethostbyaddr(ip)
        return host
    except (socket.herror, socket.gaierror, OSError):
        return ""
    finally:
        socket.setdefaulttimeout(None)


# ---------- device-type guess ----------

def guess_device_type(vendor: str, hostname: str, ports: list[int]) -> str:
    """Best-effort device class from vendor (OUI), hostname and open ports.

    Returns one of: phone, tablet, laptop, computer, console, tv, printer,
    nas, router, switch, server, iot, vm, device.
    Hostname clues win over vendor clues; vendor wins over ports.
    """
    v = (vendor or "").lower()
    h = (hostname or "").lower()
    ports = ports or []

    def in_host(*keys: str) -> bool:
        return any(k in h for k in keys)

    def in_vendor(*keys: str) -> bool:
        return any(k in v for k in keys)

    # ---- hostname clues (most specific) ----
    if in_host("iphone"):
        return "phone"
    if in_host("ipad"):
        return "tablet"
    if in_host("macbook"):
        return "laptop"
    if in_host("imac", "macmini", "mac-mini", "macpro", "mac-pro", "mac-studio"):
        return "computer"
    if in_host("android", "galaxy", "pixel", "oneplus", "redmi", "huawei"):
        return "phone"
    if in_host("xbox", "playstation", "ps4", "ps5", "nintendo"):
        return "console"
    if in_host("appletv", "apple-tv", "firetv", "fire-tv", "bravia", "roku",
               "chromecast", "shield", "vizio", "smarttv", "-tv", "tv-"):
        return "tv"
    if in_host("printer", "officejet", "deskjet", "laserjet", "epson",
               "canon", "brother"):
        return "printer"
    if in_host("nas", "synology", "diskstation", "qnap", "truenas", "freenas"):
        return "nas"
    if in_host("router", "gateway", "openwrt", "fritz", "dd-wrt"):
        return "router"
    if in_host("switch", "sw-", "-sw"):
        return "switch"
    if in_host("laptop", "notebook", "thinkpad", "latitude", "elitebook"):
        return "laptop"
    if in_host("desktop", "-pc", "pc-", "workstation"):
        return "computer"

    # ---- vendor clues ----
    if in_vendor("sony interactive", "sony computer", "nintendo"):
        return "console"
    if in_vendor("synology", "qnap", "western digital", "buffalo.inc"):
        return "nas"
    if in_vendor("roku", "vizio", "tcl", "skyworth") or \
       (in_vendor("lg electronics") and 8080 in ports):
        return "tv"
    if in_vendor("hewlett", "hp inc", "brother", "canon", "epson", "lexmark",
                 "xerox", "kyocera") and (9100 in ports or 631 in ports):
        return "printer"
    if in_vendor("apple"):
        return "computer"          # bare Apple OUI w/o hostname clue
    if in_vendor("huawei", "xiaomi", "oppo", "vivo", "oneplus", "realme",
                 "motorola mobility"):
        return "phone"
    if in_vendor("samsung"):
        return "phone"             # most consumer Samsung OUIs are phones
    if in_vendor("cisco", "tp-link", "netgear", "ubiquiti", "mikrotik",
                 "asustek comp", "asus", "d-link", "linksys", "aruba", "zyxel",
                 "ruckus", "cambium", "juniper", "tenda", "fortinet",
                 "ruijie", "extreme networks"):
        return "router"
    if in_vendor("raspberry"):
        return "iot"
    if in_vendor("espressif", "tuya", "sonos", "philips", "signify", "nest",
                 "ring", "belkin", "shelly", "ecobee", "lifx", "sengled",
                 "amazon technologies", "google"):
        return "iot"
    if in_vendor("vmware", "virtualbox", "parallels", "hyper-v", "qemu", "xen",
                 "microsoft corp"):
        return "vm"
    if in_vendor("intel", "dell", "lenovo", "micro-star", "gigabyte",
                 "msi", "acer", "razer", "framework"):
        return "computer"

    # ---- open-port clues (only available after a port scan) ----
    if 9100 in ports or 631 in ports:
        return "printer"
    if 32400 in ports or 8060 in ports:
        return "tv"
    if 80 in ports or 443 in ports or 8080 in ports:
        return "server"
    return "device"


# Device classes that commonly implement Wake-on-LAN (wired NICs with WoL in
# firmware). True remote detection isn't possible — WoL support lives in the
# NIC/BIOS, not on the wire — so this is an honest best-effort guess.
WOL_LIKELY_KINDS = {"computer", "laptop", "server", "nas", "console"}


def wol_capable(kind: str) -> bool:
    """Best-effort guess of whether a device class supports Wake-on-LAN."""
    return kind in WOL_LIKELY_KINDS


# ---------- wake-on-lan ----------

def wake_on_lan(mac: str, broadcast: str = "255.255.255.255",
                port: int = 9) -> bool:
    """Send a Wake-on-LAN magic packet to `mac` over UDP broadcast.

    The packet is 6 bytes of 0xFF followed by the 6-byte MAC repeated 16×.
    Sent to the subnet broadcast on the usual WoL ports (7 and 9)."""
    hexmac = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(hexmac) != 12:
        return False
    payload = bytes.fromhex("ff" * 6 + hexmac * 16)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for p in {port, 7, 9}:
                s.sendto(payload, (broadcast, p))
        return True
    except OSError:
        return False


# ---------- port scan ----------

COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 139, 143, 443, 445,
                465, 587, 631, 993, 995, 1883, 3306, 3389, 5000,
                5353, 5900, 8080, 8443, 8883, 9100]

SERVICE_NAMES = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 139: "NetBIOS", 143: "IMAP",
    443: "HTTPS", 445: "SMB", 465: "SMTPS", 587: "Submission",
    631: "IPP", 993: "IMAPS", 995: "POP3S", 1883: "MQTT",
    3306: "MySQL", 3389: "RDP", 5000: "UPnP", 5353: "mDNS",
    5900: "VNC", 8080: "HTTP-alt", 8443: "HTTPS-alt",
    8883: "MQTTS", 9100: "Printer",
}


def port_scan(ip: str, ports: list[int] = COMMON_PORTS,
              timeout: float = 0.4) -> list[int]:
    def check(p: int) -> Optional[int]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                if s.connect_ex((ip, p)) == 0:
                    return p
        except OSError:
            return None
        return None

    open_ports: list[int] = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        for r in ex.map(check, ports):
            if r is not None:
                open_ports.append(r)
    return sorted(open_ports)


def service_name(p: int) -> str:
    return SERVICE_NAMES.get(p, "")


# ---------- scan orchestration ----------

def scan_network_stream(net: NetInfo,
                        max_workers: Optional[int] = None) -> Iterator[dict]:
    """Yield discovery events as devices are found.

    Event shapes:
      {"type": "start", "total": N, "network": cidr}
      {"type": "progress", "scanned": k, "total": N, "found": m}
      {"type": "device", "device": {...}}
      {"type": "done", "elapsed_ms": ms, "count": n}
    """
    start = time.monotonic()
    network = ipaddress.IPv4Network(net.cidr, strict=False)
    hosts = [str(h) for h in network.hosts()]
    total = len(hosts)

    if max_workers is None:
        # Windows ping is slower; keep concurrency reasonable everywhere.
        max_workers = 60 if IS_WIN else 96

    yield {"type": "start", "total": total, "network": net.cidr}

    alive: list[str] = []
    scanned = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(ping_host, ip): ip for ip in hosts}
        for fut in as_completed(futures):
            ip = futures[fut]
            scanned += 1
            try:
                if fut.result():
                    alive.append(ip)
            except Exception:
                pass
            if scanned % 8 == 0 or scanned == total:
                yield {"type": "progress", "scanned": scanned,
                       "total": total, "found": len(alive)}

    arp = read_arp_table()

    # Many devices (phones, IoT, firewalled hosts) never answer ICMP but do
    # reply to ARP — pinging the whole subnet populates the neighbor table, so
    # treat any in-subnet ARP entry as a live host too. This is how Fing finds
    # devices that don't respond to ping.
    network_obj = ipaddress.IPv4Network(net.cidr, strict=False)
    alive_set = set(alive)
    for ip in arp:
        if ip in alive_set:
            continue
        try:
            if ipaddress.IPv4Address(ip) in network_obj:
                alive.append(ip)
                alive_set.add(ip)
        except ValueError:
            continue

    # Always include the local host & gateway, even if ICMP is filtered.
    for must in (net.ip, net.gateway):
        if must and must not in alive_set:
            alive.append(must)
            alive_set.add(must)

    def enrich(ip: str) -> dict:
        mac = arp.get(ip) or (net.mac if ip == net.ip else "")
        vendor = lookup_vendor(mac) if mac else ""
        hostname = reverse_dns(ip)
        is_self = ip == net.ip
        is_gateway = ip == net.gateway
        if is_self and not hostname:
            hostname = socket.gethostname()
        # Keep the real device class in `kind`; is_self / is_gateway are
        # surfaced as separate badges by the UI. The gateway is a router.
        if is_gateway:
            kind = "router"
        else:
            kind = guess_device_type(vendor, hostname, [])
            # The scanning host is a computer — its NIC OUI (e.g. a TP-Link
            # Wi-Fi card) can otherwise be misread as networking gear.
            if is_self and kind in ("router", "switch", "iot", "device"):
                kind = "computer"
        return {"ip": ip, "mac": mac, "vendor": vendor, "hostname": hostname,
                "is_self": is_self, "is_gateway": is_gateway, "kind": kind,
                "wol_capable": bool(mac) and not is_self and wol_capable(kind)}

    with ThreadPoolExecutor(max_workers=32) as ex:
        ordered = sorted(alive, key=lambda x: tuple(int(o) for o in x.split(".")))
        for dev in ex.map(enrich, ordered):
            yield {"type": "device", "device": dev}

    yield {"type": "done",
           "elapsed_ms": int((time.monotonic() - start) * 1000),
           "count": len(alive)}


def net_info_dict() -> Optional[dict]:
    n = detect_network()
    return asdict(n) if n else None


if __name__ == "__main__":
    # Quick CLI smoke test: `python netscan.py`
    n = detect_network()
    if not n:
        print("Could not detect network.", file=sys.stderr)
        sys.exit(1)
    print(f"Interface : {n.interface}")
    print(f"Your IP   : {n.ip}  (mac {n.mac})")
    print(f"Gateway   : {n.gateway}")
    print(f"Subnet    : {n.cidr}")
    print(f"Hosts     : {n.host_count}\n")
    for ev in scan_network_stream(n):
        if ev["type"] == "device":
            d = ev["device"]
            print(f"  {d['ip']:<15}  {d['mac'] or '--:--:--:--:--:--':<17}  "
                  f"{d['vendor'] or '':<14}  {d['hostname']}")
        elif ev["type"] == "done":
            print(f"\nDone in {ev['elapsed_ms']/1000:.1f}s — {ev['count']} devices.")
