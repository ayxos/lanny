"""Tiny JSON-file store for devices the user saved for Wake-on-LAN.

A device only shows up in a scan while it's awake — so to wake it *later*
(when it's asleep and invisible to the scanner) we must remember its IP/MAC
now. This persists that list to ~/.lanny/devices.json.

Saved entries are keyed by normalized MAC (the WoL target).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Optional

import netscan

_LOCK = threading.Lock()


def _dir() -> str:
    base = os.environ.get("LANNY_HOME") or os.path.join(
        os.path.expanduser("~"), ".lanny")
    return base


def _path() -> str:
    return os.path.join(_dir(), "devices.json")


def _read() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def _write(data: dict) -> None:
    os.makedirs(_dir(), exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _path())


def list_saved() -> list[dict]:
    with _LOCK:
        data = _read()
    return sorted(data.values(), key=lambda d: d.get("name", "").lower())


def save_device(mac: str, ip: str = "", name: str = "",
                kind: str = "") -> Optional[dict]:
    """Add or update a saved device. Returns the stored entry, or None if the
    MAC is invalid (a real MAC is required to send a WoL packet)."""
    nmac = netscan._normalize_mac(mac)
    if not nmac:
        return None
    with _LOCK:
        data = _read()
        existing = data.get(nmac, {})
        entry = {
            "mac": nmac,
            "ip": ip or existing.get("ip", ""),
            "name": name or existing.get("name", "") or (ip or nmac),
            "kind": kind or existing.get("kind", "device"),
            "added": existing.get("added") or int(time.time()),
        }
        data[nmac] = entry
        _write(data)
    return entry


def remove_device(mac: str) -> bool:
    nmac = netscan._normalize_mac(mac)
    if not nmac:
        return False
    with _LOCK:
        data = _read()
        if nmac in data:
            del data[nmac]
            _write(data)
            return True
    return False
