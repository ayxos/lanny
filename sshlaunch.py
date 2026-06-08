"""Open the OS terminal app and start an SSH session.

Design choices:
  * We launch the *native terminal* rather than embedding a web shell. An
    in-browser PTY would mean exposing a live shell over HTTP — a serious
    risk for a LAN-reachable app — so the launcher is both safer and simpler.
  * Inputs are validated strictly and the command is built as an argv LIST
    (never a shell string), so a crafted host/user/key can't inject options
    or shell metacharacters.

`build_argv()` returns the ssh command; `command_str()` renders it for the
"copy" button; `open_terminal()` tries to spawn it in a terminal window and
reports honestly whether it could.
"""
from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
from typing import Optional

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


def _is_wsl() -> bool:
    if not IS_LINUX:
        return False
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


IS_WSL = _is_wsl()

# A host/user must be a plain hostname, IP or alias — crucially NOT something
# that ssh would read as an option (leading '-') or a shell would expand.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


class ValidationError(ValueError):
    pass


def validate(host: str, user: str = "", port: str = "",
             key: str = "") -> dict:
    host = (host or "").strip()
    user = (user or "").strip()
    port = (port or "").strip()
    key = (key or "").strip()

    if not _NAME_RE.match(host):
        raise ValidationError("Invalid host (letters, digits, dot, hyphen only).")
    if user and not _NAME_RE.match(user):
        raise ValidationError("Invalid user name.")
    if port:
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            raise ValidationError("Port must be 1–65535.")
    if key:
        if any(c in key for c in "\n\r\x00") or key.startswith("-"):
            raise ValidationError("Invalid key path.")
    return {"host": host, "user": user, "port": port, "key": key}


def build_argv(host: str, user: str = "", port: str = "",
               key: str = "") -> list[str]:
    v = validate(host, user, port, key)
    argv = ["ssh"]
    if v["port"] and v["port"] != "22":
        argv += ["-p", v["port"]]
    if v["key"]:
        argv += ["-i", os.path.expanduser(v["key"])]
    argv.append(f"{v['user']}@{v['host']}" if v["user"] else v["host"])
    return argv


def command_str(argv: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)


def _spawn(cmd: list[str]) -> None:
    subprocess.Popen(cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_terminal(argv: list[str]) -> dict:
    """Try to open a terminal window running `argv`. Returns
    {launched, method, command, error}."""
    cmd_display = command_str(argv)
    result = {"launched": False, "method": "", "command": cmd_display, "error": ""}

    try:
        if IS_MAC:
            script = 'tell application "Terminal" to do script "%s"' % \
                     cmd_display.replace("\\", "\\\\").replace('"', '\\"')
            _spawn(["osascript", "-e", script,
                    "-e", 'tell application "Terminal" to activate'])
            result.update(launched=True, method="Terminal.app")
            return result

        if IS_WSL:
            # Run ssh *inside* WSL but in a Windows terminal window.
            wt = shutil.which("wt.exe")
            if wt:
                _spawn([wt, "wsl.exe", *argv])
                result.update(launched=True, method="Windows Terminal (wsl)")
            else:
                _spawn(["cmd.exe", "/c", "start", "wsl.exe", *argv])
                result.update(launched=True, method="cmd start (wsl)")
            return result

        if IS_WIN:
            wt = shutil.which("wt.exe")
            if wt:
                _spawn([wt, *argv])
                result.update(launched=True, method="Windows Terminal")
            else:
                _spawn(["cmd", "/c", "start", "cmd", "/k", *argv])
                result.update(launched=True, method="cmd")
            return result

        # Linux (with a desktop): find a terminal emulator.
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            result["error"] = ("No graphical display detected — can't open a "
                               "terminal. Copy the command and run it yourself.")
            return result
        # (terminal, args-before-command, joins-as-single-string?)
        candidates = [
            ("x-terminal-emulator", ["-e"], False),
            ("gnome-terminal", ["--"], False),
            ("konsole", ["-e"], False),
            ("xfce4-terminal", ["-x"], False),
            ("kitty", [], False),
            ("alacritty", ["-e"], False),
            ("xterm", ["-e"], False),
        ]
        for term, pre, _ in candidates:
            path = shutil.which(term)
            if path:
                _spawn([path, *pre, *argv])
                result.update(launched=True, method=term)
                return result
        result["error"] = "No terminal emulator found (install one or copy the command)."
        return result
    except OSError as e:
        result["error"] = str(e)
        return result
