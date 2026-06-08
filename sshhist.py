"""Mine shell history for frequently-used SSH connections.

The honest source ranking:
  * shell history (~/.bash_history, ~/.zsh_history) — the only place that
    records HOW OFTEN you connect, so it's what "common" is built from. zsh
    lines carry an epoch timestamp (": <ts>:<elapsed>;cmd"); bash optionally
    writes "#<ts>" lines when HISTTIMEFORMAT is set.
  * ~/.ssh/config — named Host aliases (configured targets, no frequency).
  * ~/.ssh/known_hosts — every host you've reached, BUT it's hashed by default
    (HashKnownHosts), so hostnames usually can't be recovered. Reported as a
    flag, not parsed.

`collect()` returns a frequency-ranked list of {user, host, port, target,
count, last_used, source}.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Optional

# ssh option letters that consume the following token as their argument.
_OPTS_WITH_ARG = set("bcDeFIiLlmOoPpQRSWw")

_SSH_PROGS = {"ssh", "scp", "sftp"}


def _history_paths() -> list[str]:
    home = os.path.expanduser("~")
    paths = [
        os.environ.get("HISTFILE", ""),
        os.path.join(home, ".zsh_history"),
        os.path.join(home, ".bash_history"),
        os.path.join(home, ".local", "share", "zsh", "history"),
    ]
    seen, out = set(), []
    for p in paths:
        if p and p not in seen and os.path.isfile(p):
            seen.add(p)
            out.append(p)
    return out


def _iter_commands(path: str):
    """Yield (command_str, timestamp|None) from a bash or zsh history file."""
    pending_ts: Optional[int] = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.rstrip("\n")
                # zsh extended: ": <ts>:<elapsed>;<command>"
                m = re.match(r"^: (\d+):\d+;(.*)$", line)
                if m:
                    yield m.group(2), int(m.group(1))
                    continue
                # bash HISTTIMEFORMAT marker line: "#<epoch>"
                m = re.match(r"^#(\d{9,})$", line)
                if m:
                    pending_ts = int(m.group(1))
                    continue
                if line.strip():
                    yield line, pending_ts
                pending_ts = None
    except OSError:
        return


def _split_subcommands(cmd: str) -> list[str]:
    """Split a command line on ; | && || so we catch ssh anywhere in a chain."""
    return [c.strip() for c in re.split(r"&&|\|\||[;|]", cmd) if c.strip()]


def _parse_target(host_token: str) -> Optional[dict]:
    """Turn 'user@host', 'host', or scp's 'user@host:/path' into parts."""
    tok = host_token.split(":", 1)[0]      # drop scp/sftp :path suffix
    if not tok or tok.startswith("-"):
        return None
    user = ""
    host = tok
    if "@" in tok:
        user, host = tok.split("@", 1)
    if not host or "/" in host:
        return None
    # crude sanity: a host has a dot, or is a short alias/hostname (no spaces)
    if not re.match(r"^[A-Za-z0-9_.\-]+$", host):
        return None
    return {"user": user, "host": host}


def _parse_ssh(tokens: list[str]) -> Optional[dict]:
    """Parse tokens after the program name into {user, host, port}."""
    prog = tokens[0]
    rest = tokens[1:]
    port = ""
    user = ""
    positionals: list[str] = []
    i = 0
    while i < len(rest):
        t = rest[i]
        if t.startswith("-") and len(t) >= 2:
            flag = t[1]
            # capture port (-p for ssh/sftp, -P for scp) and user (-l)
            val = t[2:] if len(t) > 2 else (rest[i + 1] if i + 1 < len(rest) else "")
            consumes = (flag in _OPTS_WITH_ARG) and len(t) == 2
            if flag in ("p", "P"):
                port = val
            elif flag == "l":
                user = val
            i += 2 if consumes else 1
            continue
        positionals.append(t)
        i += 1

    target = None
    if prog == "scp":
        # remote endpoint is the token carrying a ':' (host:path); a transfer
        # between two local paths has none, so it's skipped.
        for t in positionals:
            if ":" in t:
                target = _parse_target(t)
                if target:
                    break
    else:  # ssh, and sftp (which may be 'sftp user@host' or 'sftp host:path')
        for t in positionals:
            target = _parse_target(t)
            if target:
                break

    if not target:
        return None
    return {
        "user": target["user"] or user,
        "host": target["host"],
        "port": port or "22",
    }


def _ssh_config_hosts(path: str) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cur = None
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                key, _, val = s.partition(" ")
                k = key.lower()
                if k == "host":
                    for alias in val.split():
                        if "*" in alias or "?" in alias:
                            continue
                        cur = {"alias": alias, "host": alias, "user": "", "port": "22"}
                        out.append(cur)
                elif cur and k == "hostname":
                    cur["host"] = val.strip()
                elif cur and k == "user":
                    cur["user"] = val.strip()
                elif cur and k == "port":
                    cur["port"] = val.strip()
    except OSError:
        pass
    return out


def collect(history_paths: Optional[list[str]] = None,
            ssh_config: Optional[str] = None,
            known_hosts: Optional[str] = None) -> dict:
    home = os.path.expanduser("~")
    paths = history_paths if history_paths is not None else _history_paths()
    ssh_config = ssh_config if ssh_config is not None else os.path.join(home, ".ssh", "config")
    known_hosts = known_hosts if known_hosts is not None else os.path.join(home, ".ssh", "known_hosts")

    agg: dict[str, dict] = {}

    def bump(user, host, port, ts, source):
        key = f"{user}@{host}" if user else host
        e = agg.get(key)
        if not e:
            e = {"user": user, "host": host, "port": port or "22",
                 "target": key, "count": 0, "last_used": None,
                 "source": source}
            agg[key] = e
        e["count"] += 1
        if port and port != "22":
            e["port"] = port
        if ts and (e["last_used"] is None or ts > e["last_used"]):
            e["last_used"] = ts

    for p in paths:
        for cmd, ts in _iter_commands(p):
            if "ssh" not in cmd and "scp" not in cmd and "sftp" not in cmd:
                continue
            for sub in _split_subcommands(cmd):
                try:
                    tokens = shlex.split(sub)
                except ValueError:
                    continue
                if not tokens or tokens[0] not in _SSH_PROGS:
                    continue
                parsed = _parse_ssh(tokens)
                if parsed:
                    bump(parsed["user"], parsed["host"], parsed["port"], ts, "history")

    # config aliases: surface as count-0 entries if not already seen via history
    config_hosts = _ssh_config_hosts(ssh_config)
    for h in config_hosts:
        key = f"{h['user']}@{h['host']}" if h["user"] else h["host"]
        if key not in agg and h["alias"] not in agg:
            agg[key] = {"user": h["user"], "host": h["host"], "port": h["port"],
                        "target": key, "count": 0, "last_used": None,
                        "source": "config", "alias": h["alias"]}

    conns = sorted(agg.values(),
                   key=lambda e: (-e["count"], -(e["last_used"] or 0), e["host"]))

    kh_hashed = False
    try:
        with open(known_hosts, encoding="utf-8", errors="replace") as f:
            head = f.readline().strip()
            kh_hashed = head.startswith("|1|") or head.startswith("|2|")
    except OSError:
        pass

    return {
        "connections": conns,
        "history_files": [os.path.basename(p) for p in paths],
        "known_hosts_hashed": kh_hashed,
        "note": ("known_hosts is hashed (HashKnownHosts) — host names can't be "
                 "recovered from it; ranking comes from shell history."
                 if kh_hashed else ""),
    }
