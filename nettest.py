"""Network health & security checks for the dashboard.

Everything here is best-effort and honest about its limits:
  * speed test  -> real HTTP download/upload against Cloudflare's edge.
  * latency     -> system ping to gateway + public resolvers.
  * dns         -> resolver list, resolution timing, hijack/NXDOMAIN test.
  * security    -> heuristic checks (risky/plaintext open ports on the
                   gateway, DNS hijack) — NOT a CVE scanner or antivirus.
  * wifi        -> channel/signal scan where the OS exposes it (not in WSL).

`run_health_checks()` is a generator that streams results as each check
finishes, then a final aggregate "safety score".
"""
from __future__ import annotations

import os
import re
import socket
import ssl
import time
import urllib.request
from typing import Iterator, Optional

import netscan

_UA = {"User-Agent": "Mozilla/5.0 (Lanny NetTest)"}


def _http_bytes(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


# ---------- latency ----------

def _ping_times(ip: str, count: int = 4) -> list[float]:
    """Return per-reply RTTs in ms parsed from system ping."""
    if netscan.IS_WIN:
        cmd = ["ping", "-n", str(count), ip]
    elif netscan.IS_MAC:
        cmd = ["ping", "-c", str(count), ip]
    else:
        cmd = ["ping", "-c", str(count), "-w", str(count + 2), ip]
    out = netscan._run(cmd, timeout=count + 4)
    return [float(m) for m in re.findall(r"time[=<]\s*([\d.]+)\s*ms", out)]


def latency_check(net) -> dict:
    targets = [("Gateway", net.gateway)] if net and net.gateway else []
    targets += [("Cloudflare (1.1.1.1)", "1.1.1.1"),
                ("Google (8.8.8.8)", "8.8.8.8")]
    results = []
    for label, ip in targets:
        ts = _ping_times(ip)
        if ts:
            avg = sum(ts) / len(ts)
            jitter = (max(ts) - min(ts))
            results.append({"label": label, "ip": ip, "ok": True,
                            "avg_ms": round(avg, 1), "jitter_ms": round(jitter, 1),
                            "loss": round(100 * (1 - len(ts) / 4))})
        else:
            results.append({"label": label, "ip": ip, "ok": False,
                            "avg_ms": None, "jitter_ms": None, "loss": 100})
    return {"targets": results}


# ---------- speed ----------

def speed_check() -> dict:
    """Download + upload throughput against Cloudflare's speed edge."""
    out: dict = {"download_mbps": None, "upload_mbps": None,
                 "latency_ms": None, "error": None}
    try:
        # latency: time a tiny download
        t0 = time.monotonic()
        _http_bytes("https://speed.cloudflare.com/__down?bytes=1000", timeout=10)
        out["latency_ms"] = round((time.monotonic() - t0) * 1000, 1)

        # download ~25 MB
        size = 25_000_000
        t0 = time.monotonic()
        data = _http_bytes(f"https://speed.cloudflare.com/__down?bytes={size}",
                           timeout=40)
        dt = time.monotonic() - t0
        if dt > 0:
            out["download_mbps"] = round(len(data) * 8 / dt / 1e6, 1)

        # upload ~8 MB
        payload = os.urandom(8_000_000)
        req = urllib.request.Request("https://speed.cloudflare.com/__up",
                                     data=payload, headers=_UA, method="POST")
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=40) as r:
            r.read()
        dt = time.monotonic() - t0
        if dt > 0:
            out["upload_mbps"] = round(len(payload) * 8 / dt / 1e6, 1)
    except Exception as e:  # network/HTTP errors -> report, don't crash
        out["error"] = str(e)
    return out


# ---------- dns ----------

def _resolvers() -> list[str]:
    servers: list[str] = []
    if netscan.IS_WIN:
        out = netscan._run(["ipconfig", "/all"])
        servers = re.findall(r"DNS Servers[. ]*:\s*([\d.]+)", out)
    else:
        try:
            with open("/etc/resolv.conf") as f:
                for line in f:
                    m = re.match(r"\s*nameserver\s+([\d.]+)", line)
                    if m:
                        servers.append(m.group(1))
        except OSError:
            pass
    return servers


def dns_check() -> dict:
    resolvers = _resolvers()
    probes = ["cloudflare.com", "google.com", "github.com"]
    results = []
    socket.setdefaulttimeout(3)
    try:
        for host in probes:
            t0 = time.monotonic()
            try:
                ip = socket.gethostbyname(host)
                results.append({"host": host, "ok": True, "ip": ip,
                                "ms": round((time.monotonic() - t0) * 1000, 1)})
            except OSError:
                results.append({"host": host, "ok": False, "ip": None, "ms": None})

        # Hijack test: a guaranteed-nonexistent name should NOT resolve. If a
        # resolver hands back an IP (ad/portal redirect), flag it.
        bogus = "thisdomaindoesnotexist-lanny-test-zzq.com"
        hijacked = False
        try:
            socket.gethostbyname(bogus)
            hijacked = True
        except OSError:
            hijacked = False
    finally:
        socket.setdefaulttimeout(None)

    ok = sum(1 for r in results if r["ok"])
    avg = [r["ms"] for r in results if r["ms"] is not None]
    return {"resolvers": resolvers, "probes": results,
            "avg_ms": round(sum(avg) / len(avg), 1) if avg else None,
            "resolved": ok, "total": len(probes), "hijacked": hijacked}


# ---------- security heuristics ----------

# port -> (label, severity, why)
RISKY_PORTS = {
    23:   ("Telnet", "high", "Unencrypted remote login — credentials sent in clear."),
    21:   ("FTP", "medium", "Often plaintext; check for anonymous access."),
    445:  ("SMB", "high", "File sharing exposed — frequent ransomware/worm target."),
    139:  ("NetBIOS", "medium", "Legacy Windows sharing exposed."),
    3389: ("RDP", "high", "Remote Desktop exposed — common brute-force target."),
    5900: ("VNC", "high", "Remote desktop, often weak/no auth."),
    3306: ("MySQL", "medium", "Database reachable on the network."),
    1900: ("UPnP/SSDP", "medium", "UPnP can auto-open firewall ports."),
    5000: ("UPnP", "low", "UPnP control endpoint exposed."),
    80:   ("HTTP", "low", "Unencrypted admin/web interface."),
}


def security_check(net) -> dict:
    findings: list[dict] = []

    # Scan the gateway/router — the most security-relevant host.
    gw_ports: list[int] = []
    if net and net.gateway:
        gw_ports = netscan.port_scan(net.gateway)
        for p in gw_ports:
            if p in RISKY_PORTS:
                label, sev, why = RISKY_PORTS[p]
                findings.append({"host": net.gateway, "where": "Router",
                                 "port": p, "service": label,
                                 "severity": sev, "detail": why})

    return {"gateway": net.gateway if net else None,
            "gateway_open_ports": gw_ports, "findings": findings}


# ---------- wifi ----------

def wifi_check() -> dict:
    """Channel/signal scan. Returns {available, networks|reason}."""
    nets: list[dict] = []

    if netscan.IS_LINUX:
        out = netscan._run(["nmcli", "-t", "-f",
                            "SSID,CHAN,SIGNAL,SECURITY", "dev", "wifi"], timeout=8)
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0]:
                nets.append({"ssid": parts[0], "channel": parts[1],
                             "signal": parts[2], "security": parts[3] or "open"})

    elif netscan.IS_MAC:
        air = ("/System/Library/PrivateFrameworks/Apple80211.framework/"
               "Versions/Current/Resources/airport")
        out = netscan._run([air, "-s"], timeout=8)
        for line in out.splitlines()[1:]:
            m = re.match(r"\s*(.+?)\s+([0-9a-f:]{17})\s+(-?\d+)\s+(\d+)", line)
            if m:
                nets.append({"ssid": m.group(1).strip(), "channel": m.group(4),
                             "signal": m.group(3), "security": ""})

    elif netscan.IS_WIN:
        out = netscan._run(["netsh", "wlan", "show", "networks", "mode=bssid"],
                           timeout=8)
        ssid = ""
        for line in out.splitlines():
            s = re.match(r"\s*SSID \d+ : (.*)", line)
            if s:
                ssid = s.group(1).strip()
            c = re.search(r"Channel\s*:\s*(\d+)", line)
            sig = re.search(r"Signal\s*:\s*(\d+)%", line)
            if c:
                nets.append({"ssid": ssid, "channel": c.group(1),
                             "signal": sig.group(1) if sig else "", "security": ""})

    if not nets:
        return {"available": False,
                "reason": "No Wi-Fi scan available here (no wireless radio "
                          "exposed — e.g. wired link or WSL/VM)."}
    return {"available": True, "networks": nets}


# ---------- orchestration ----------

def _score(latency, dns, security) -> dict:
    score = 100
    notes = []
    for f in security.get("findings", []):
        sev = f["severity"]
        score -= {"high": 25, "medium": 12, "low": 4}.get(sev, 4)
        notes.append(f"{f['service']} open on {f['where'].lower()} ({sev})")
    if dns.get("hijacked"):
        score -= 20
        notes.append("DNS returns an IP for nonexistent domains (hijack/redirect)")
    if dns.get("resolved", 0) < dns.get("total", 1):
        score -= 10
        notes.append("Some DNS lookups failed")
    gw = next((t for t in latency.get("targets", [])
               if t["label"].startswith("Gateway")), None)
    if gw and not gw["ok"]:
        score -= 10
        notes.append("Gateway not responding to ping")
    score = max(0, min(100, score))
    grade = ("Excellent" if score >= 90 else "Good" if score >= 75 else
             "Fair" if score >= 55 else "At risk")
    return {"score": score, "grade": grade, "notes": notes}


def run_health_checks() -> Iterator[dict]:
    """Stream check results: {type:'check', key, title, data} then 'summary'."""
    net = netscan.detect_network()

    steps = [
        ("latency", "Latency & packet loss", lambda: latency_check(net)),
        ("speed", "Internet speed", speed_check),
        ("dns", "DNS resolution", dns_check),
        ("security", "Router security scan", lambda: security_check(net)),
        ("wifi", "Wi-Fi channels", wifi_check),
    ]
    yield {"type": "start", "total": len(steps)}

    collected: dict = {}
    for key, title, fn in steps:
        yield {"type": "running", "key": key, "title": title}
        try:
            data = fn()
        except Exception as e:
            data = {"error": str(e)}
        collected[key] = data
        yield {"type": "check", "key": key, "title": title, "data": data}

    summary = _score(collected.get("latency", {}),
                     collected.get("dns", {}),
                     collected.get("security", {}))
    yield {"type": "summary", "data": summary}
