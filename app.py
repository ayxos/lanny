"""Flask web UI for the LAN scanner."""
from __future__ import annotations

import ipaddress
import json
import os

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import netscan
import nettest
import sniffer
import store
import sshhist
import sshlaunch

app = Flask(__name__)


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.route("/api/network")
def api_network():
    info = netscan.net_info_dict()
    if not info:
        return jsonify({"error": "could not detect network"}), 500
    return jsonify(info)


@app.route("/api/scan")
def api_scan():
    net = netscan.detect_network()
    if not net:
        return jsonify({"error": "could not detect network"}), 500

    @stream_with_context
    def gen():
        for event in netscan.scan_network_stream(net):
            yield f"data: {json.dumps(event)}\n\n"

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/portscan")
def api_portscan():
    ip = request.args.get("ip", "")
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        return jsonify({"error": "invalid ip"}), 400
    ports = netscan.port_scan(ip)
    return jsonify({
        "ip": ip,
        "open_ports": ports,
        "services": [{"port": p, "service": netscan.service_name(p)} for p in ports],
    })


@app.route("/api/health")
def api_health():
    @stream_with_context
    def gen():
        for event in nettest.run_health_checks():
            yield f"data: {json.dumps(event)}\n\n"

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/sniff")
def api_sniff():
    try:
        interval = max(0.5, min(10.0, float(request.args.get("interval", "2"))))
    except ValueError:
        interval = 2.0

    @stream_with_context
    def gen():
        try:
            for event in sniffer.stream(interval=interval):
                yield f"data: {json.dumps(event)}\n\n"
        except GeneratorExit:
            return

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/wol")
def api_wol():
    mac = request.args.get("mac", "")
    if not netscan._normalize_mac(mac):
        return jsonify({"error": "invalid mac"}), 400
    net = netscan.detect_network()
    broadcast = net.broadcast if net else "255.255.255.255"
    sent = netscan.wake_on_lan(mac, broadcast)
    if not sent:
        return jsonify({"error": "could not send packet", "mac": mac}), 500
    return jsonify({"sent": True, "mac": mac, "broadcast": broadcast})


@app.route("/api/saved", methods=["GET"])
def api_saved_list():
    return jsonify({"devices": store.list_saved()})


@app.route("/api/saved", methods=["POST"])
def api_saved_add():
    body = request.get_json(silent=True) or request.form
    mac = (body.get("mac") or "").strip()
    if not netscan._normalize_mac(mac):
        return jsonify({"error": "a valid MAC address is required"}), 400
    entry = store.save_device(
        mac=mac,
        ip=(body.get("ip") or "").strip(),
        name=(body.get("name") or "").strip(),
        kind=(body.get("kind") or "").strip(),
    )
    return jsonify({"saved": entry})


@app.route("/api/saved", methods=["DELETE"])
def api_saved_remove():
    mac = request.args.get("mac", "")
    ok = store.remove_device(mac)
    return jsonify({"removed": ok}), (200 if ok else 404)


@app.route("/api/ssh-history")
def api_ssh_history():
    return jsonify(sshhist.collect())


@app.route("/api/ssh-launch", methods=["POST"])
def api_ssh_launch():
    # Spawning a terminal is sensitive — only allow it from the local machine.
    if request.remote_addr not in ("127.0.0.1", "::1", "localhost"):
        return jsonify({"error": "ssh launch is allowed from localhost only"}), 403
    body = request.get_json(silent=True) or {}
    try:
        argv = sshlaunch.build_argv(
            host=body.get("host", ""), user=body.get("user", ""),
            port=body.get("port", ""), key=body.get("key", ""))
    except sshlaunch.ValidationError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(sshlaunch.open_terminal(argv))


def run(host: str = "127.0.0.1", port: int = 5050) -> None:
    """Entry point used by the tray launcher."""
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    run(host="0.0.0.0", port=port)
