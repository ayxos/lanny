"""OUI (MAC vendor) lookup.

Primary source is the full IEEE registry shipped alongside this module as
``oui.tsv`` (~39k entries, ``assignment<TAB>vendor`` per line). Assignments
may be 24-bit (MA-L, 6 hex), 28-bit (MA-M, 7 hex) or 36-bit (MA-S, 9 hex),
so lookups try the longest prefix first. If the file is missing (e.g. a
stripped-down build), we fall back to the small embedded table below.

Refresh the data file with: ``python oui.py --update``
"""
from __future__ import annotations

import os
import sys

OUI_URL = "https://standards-oui.ieee.org/oui/oui.csv"

# Small embedded fallback used only when oui.tsv is unavailable.
OUI: dict[str, str] = {
    # Apple
    "001451": "Apple", "0023df": "Apple", "0050e4": "Apple", "0017f2": "Apple",
    "001ec2": "Apple", "002241": "Apple", "002608": "Apple", "0026bb": "Apple",
    "001d4f": "Apple", "002500": "Apple", "00256c": "Apple", "00264a": "Apple",
    "3c0754": "Apple", "a4c361": "Apple", "f0d1a9": "Apple", "f0db40": "Apple",
    "f4f15a": "Apple", "f81edf": "Apple", "fcfc48": "Apple", "f0f61c": "Apple",
    # Samsung
    "001632": "Samsung", "002566": "Samsung", "0023d7": "Samsung", "0024e9": "Samsung",
    "086698": "Samsung", "1c5a3e": "Samsung", "5440ad": "Samsung", "78f882": "Samsung",
    "a02195": "Samsung", "c8198f": "Samsung", "e85b5b": "Samsung",
    # Google
    "001a11": "Google", "3c5ab4": "Google", "54607b": "Google", "94eb2c": "Google",
    "a4778d": "Google", "f4f5d8": "Google", "f4f5e8": "Google", "f8f005": "Google",
    "d8b8f6": "Google", "20df3f": "Google",
    # Amazon
    "0c47c9": "Amazon", "447dd3": "Amazon", "4c17eb": "Amazon", "68374a": "Amazon",
    "744aa4": "Amazon", "8871e5": "Amazon", "a002dc": "Amazon", "ac63be": "Amazon",
    "f0272d": "Amazon", "fcd2b6": "Amazon",
    # Microsoft
    "0003ff": "Microsoft", "00125a": "Microsoft", "001dd8": "Microsoft",
    "002248": "Microsoft", "0022a6": "Microsoft", "281878": "Microsoft",
    "5cba37": "Microsoft", "7c1e52": "Microsoft", "8851fb": "Microsoft",
    # Intel
    "001111": "Intel", "0015ff": "Intel", "001b21": "Intel", "001e64": "Intel",
    "001ff3": "Intel", "00216b": "Intel", "0022fb": "Intel", "0024d7": "Intel",
    "ac72b8": "Intel", "346f24": "Intel", "9c30b3": "Intel",
    # Networking / routers
    "001839": "Cisco", "0018ba": "Cisco", "001b54": "Cisco", "001bd4": "Cisco",
    "0024c4": "Cisco", "5c83f8": "Cisco", "6c8d65": "Cisco",
    "001eec": "Linksys", "0023a7": "Linksys", "208984": "Linksys",
    "0014bf": "Netgear", "00224d": "Netgear", "10da43": "Netgear",
    "204e7f": "Netgear", "289401": "Netgear", "a040a0": "Netgear",
    "001d0f": "TP-Link", "14cc20": "TP-Link", "60e327": "TP-Link",
    "98ded0": "TP-Link", "a42bb0": "TP-Link", "c46e1f": "TP-Link",
    "002722": "Ubiquiti", "04181b": "Ubiquiti", "245a4c": "Ubiquiti",
    "788a20": "Ubiquiti", "fcecda": "Ubiquiti", "dc9fdb": "Ubiquiti",
    "001cf0": "D-Link", "002191": "D-Link", "0024010": "D-Link",
    "001bfc": "Asus", "002618": "Asus", "1c872c": "Asus", "305a3a": "Asus",
    "50465d": "Asus", "ac220b": "Asus",
    "0009ad": "MikroTik", "4c5e0c": "MikroTik", "6c3b6b": "MikroTik",
    "e48d8c": "MikroTik", "08552e": "MikroTik",
    # Raspberry Pi
    "b827eb": "Raspberry Pi", "dca632": "Raspberry Pi",
    "e45f01": "Raspberry Pi", "28cdc1": "Raspberry Pi",
    "d83add": "Raspberry Pi", "2ccf67": "Raspberry Pi",
    # ESP / IoT chipsets
    "240ac4": "Espressif", "30aea4": "Espressif", "3c61a5": "Espressif",
    "4827e2": "Espressif", "4cebd6": "Espressif", "5ccf7f": "Espressif",
    "84f3eb": "Espressif", "98f4ab": "Espressif", "a020a6": "Espressif",
    "bcddc2": "Espressif", "c45bbe": "Espressif", "e09806": "Espressif",
    "ec64c9": "Espressif", "ecfabc": "Espressif",
    # Smart home
    "1849bf": "Sonos", "5caafd": "Sonos", "94b8c5": "Sonos",
    "001788": "Philips Hue", "00170880": "Philips Hue",
    "ec1bbd": "Philips", "ec1a59": "Belkin", "94103e": "Belkin",
    "ec1c40": "Tuya", "508a06": "Tuya",
    "f0b429": "Nest", "18b430": "Nest",
    "001d0a": "Ring", "fcecda": "Ring",
    # Lenovo / Dell / HP
    "00219b": "Dell", "1866da": "Dell", "0024e8": "Dell",
    "001a4b": "HP", "001f29": "HP", "002655": "HP", "5c8a38": "HP",
    "001a6b": "Lenovo", "00216a": "Lenovo", "60d9c7": "Lenovo",
    # Xiaomi / Huawei
    "186590": "Xiaomi", "8cbeb": "Xiaomi", "f8a45f": "Xiaomi",
    "0034fe": "Huawei", "002568": "Huawei", "001882": "Huawei",
    "488ead": "Huawei", "780cb8": "Huawei",
    # Misc
    "001c42": "Parallels (VM)", "080027": "VirtualBox (VM)",
    "00155d": "Microsoft Hyper-V", "0050569": "VMware", "005056": "VMware",
    "000c29": "VMware", "001c14": "VMware",
}


def _data_path() -> str:
    """Locate oui.tsv next to this module (or inside a PyInstaller bundle)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "oui.tsv")


def _load_registry() -> dict[str, str]:
    """Load the full IEEE registry from oui.tsv. Empty dict if unavailable."""
    table: dict[str, str] = {}
    path = _data_path()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                assignment, _, vendor = line.partition("\t")
                vendor = vendor.strip()
                if assignment and vendor:
                    table[assignment.strip().lower()] = vendor
    except OSError:
        pass
    return table


# Loaded once at import; merged over the embedded fallback so the registry
# wins but hand-curated names still resolve if the file is incomplete.
_REGISTRY: dict[str, str] = {**OUI, **_load_registry()}


def lookup_vendor(mac: str) -> str:
    """Return vendor name for a MAC, or '' if unknown."""
    if not mac:
        return ""
    hexstr = mac.lower().replace(":", "").replace("-", "")
    if len(hexstr) < 6:
        return ""
    # Try most-specific assignment first: 36-bit, 28-bit, then 24-bit OUI.
    for n in (9, 7, 6):
        v = _REGISTRY.get(hexstr[:n])
        if v:
            return v
    return ""


def _update() -> int:
    """Download the latest IEEE registry and regenerate oui.tsv."""
    import csv
    import io
    import urllib.request

    print(f"Downloading {OUI_URL} ...", file=sys.stderr)
    with urllib.request.urlopen(OUI_URL, timeout=60) as resp:
        raw = resp.read().decode("utf-8", "replace")
    rows = 0
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oui.tsv")
    reader = csv.reader(io.StringIO(raw))
    next(reader, None)  # header
    with open(out_path, "w", encoding="utf-8") as out:
        for row in reader:
            if len(row) < 3:
                continue
            assignment = row[1].strip().lower()
            vendor = row[2].strip().replace("\t", " ")
            if assignment and vendor:
                out.write(f"{assignment}\t{vendor}\n")
                rows += 1
    print(f"Wrote {rows} entries to {out_path}", file=sys.stderr)
    return rows


if __name__ == "__main__":
    if "--update" in sys.argv:
        _update()
    else:
        print(f"{len(_REGISTRY)} OUI entries loaded.")
