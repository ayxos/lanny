// Lanny frontend
const $ = (id) => document.getElementById(id);

const state = {
  devices: [], filter: "", selectedIp: null, scanning: false,
  healthRunning: false,
  sniffRows: [], sniffFilter: "", sniffType: "", sniffES: null,
};

const TYPES = {
  gateway:  { icon: "🛜",  label: "Gateway" },
  router:   { icon: "📡",  label: "Router" },
  switch:   { icon: "🔀",  label: "Switch" },
  phone:    { icon: "📱",  label: "Phone" },
  tablet:   { icon: "📲",  label: "Tablet" },
  laptop:   { icon: "💻",  label: "Laptop" },
  computer: { icon: "🖥️",  label: "Computer" },
  console:  { icon: "🎮",  label: "Game console" },
  tv:       { icon: "📺",  label: "TV / Streamer" },
  printer:  { icon: "🖨️",  label: "Printer" },
  nas:      { icon: "🗄️",  label: "NAS" },
  server:   { icon: "🗄️",  label: "Server" },
  iot:      { icon: "💡",  label: "Smart home / IoT" },
  vm:       { icon: "📦",  label: "Virtual machine" },
  device:   { icon: "🔌",  label: "Unknown device" },
};

function typeInfo(d) {
  return TYPES[d.kind] || TYPES.device;
}

function iconFor(d) {
  return typeInfo(d).icon;
}

function deviceName(d) {
  if (d.hostname) return d.hostname.split(".")[0];
  if (d.vendor) return `${d.vendor} device`;
  return d.ip;
}

function renderNetwork(n) {
  $("ni-iface").textContent = n.interface;
  $("ni-ip").textContent = n.ip;
  $("ni-gw").textContent = n.gateway;
  $("ni-cidr").textContent = n.cidr;
  $("ni-hosts").textContent = n.host_count;
}

function renderDevices() {
  const list = $("devices");
  const f = state.filter.toLowerCase();
  const visible = state.devices.filter(d =>
    !f || d.ip.includes(f) ||
    (d.hostname||"").toLowerCase().includes(f) ||
    (d.vendor||"").toLowerCase().includes(f) ||
    (d.mac||"").toLowerCase().includes(f));

  list.innerHTML = visible.map(d => {
    const t = typeInfo(d);
    const mac = d.mac || "";
    return `
    <tr class="device ${d.ip===state.selectedIp?"selected":""}" data-ip="${d.ip}">
      <td class="c-dev">
        <span class="device-icon">${iconFor(d)}</span>
        <span class="d-meta">
          <span class="d-name">${escapeHtml(deviceName(d))}</span>
          ${d.is_self ? '<span class="tag self">this device</span>' : ""}
          ${d.is_gateway ? '<span class="tag gw">gateway</span>' : ""}
          <span class="d-sub">${escapeHtml(d.vendor || "Unknown vendor")}</span>
        </span>
      </td>
      <td class="c-ip mono">${d.ip}</td>
      <td class="c-mac mono">${mac || "—"}</td>
      <td class="c-type">${t.icon} ${t.label}</td>
      <td class="c-act">
        <a class="act" href="http://${d.ip}" target="_blank" rel="noopener"
           title="Open http://${d.ip} in a new tab" data-stop>🌐</a>
        <button class="act" data-act="ports" data-ip="${d.ip}"
           title="Scan open ports">🔍</button>
        <button class="act" data-act="wol" data-ip="${d.ip}" data-mac="${mac}"
           data-name="${escapeHtml(deviceName(d))}" data-kind="${d.kind}"
           title="${!mac ? "No MAC — can't wake"
              : d.wol_capable ? "Save & send Wake-on-LAN packet"
              : "Wake-on-LAN unlikely for this device type — saved anyway if you try"}"
           ${mac ? "" : "disabled"}>⏰</button>
      </td>
    </tr>`;
  }).join("");

  $("empty").classList.toggle("hidden", visible.length > 0);
  $("summary").innerHTML = state.devices.length
    ? `<b>${state.devices.length}</b> device${state.devices.length>1?"s":""} on <b>${$("ni-cidr").textContent}</b>`
    : "Click <b>Scan network</b> to begin.";

  list.querySelectorAll(".act[data-stop]").forEach(a =>
    a.addEventListener("click", (e) => e.stopPropagation()));
  list.querySelectorAll('.act[data-act="ports"]').forEach(b =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      openDevice(b.dataset.ip);
      scanPorts();
    }));
  list.querySelectorAll('.act[data-act="wol"]').forEach(b =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      wakeAndSave(b.dataset);
    }));
  list.querySelectorAll("tr.device").forEach(tr =>
    tr.addEventListener("click", () => openDevice(tr.dataset.ip)));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g,
    c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
}

async function loadNetwork() {
  const r = await fetch("/api/network");
  if (!r.ok) return;
  renderNetwork(await r.json());
}

function startScan() {
  if (state.scanning) return;
  state.scanning = true;
  state.devices = [];
  renderDevices();

  const btn = $("scanBtn"); btn.disabled = true;
  btn.classList.add("scanning");
  $("scanBtnLabel").textContent = "Scanning…";
  $("progress").classList.remove("hidden");

  const es = new EventSource("/api/scan");
  es.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.type === "start") {
      $("prog-total").textContent = e.total;
    } else if (e.type === "progress") {
      $("prog-scanned").textContent = e.scanned;
      $("prog-total").textContent = e.total;
      $("prog-found").textContent = e.found;
      $("bar-fill").style.width = (100 * e.scanned / e.total) + "%";
    } else if (e.type === "device") {
      state.devices.push(e.device);
      renderDevices();
    } else if (e.type === "done") {
      es.close();
      state.scanning = false;
      btn.disabled = false;
      btn.classList.remove("scanning");
      $("scanBtnLabel").textContent = "Rescan network";
      $("bar-fill").style.width = "100%";
      setTimeout(() => $("progress").classList.add("hidden"), 1200);
    }
  };
  es.onerror = () => {
    es.close();
    state.scanning = false;
    btn.disabled = false;
    btn.classList.remove("scanning");
    $("scanBtnLabel").textContent = "Scan network";
  };
}

function openDevice(ip) {
  const d = state.devices.find(x => x.ip === ip);
  if (!d) return;
  state.selectedIp = ip;
  renderDevices();
  const t = typeInfo(d);
  $("d-icon").textContent = iconFor(d);
  $("d-name").textContent = deviceName(d);
  $("d-sub").textContent = d.vendor || t.label;
  $("d-type").textContent = `${t.icon} ${t.label}`
    + (d.is_self ? " · this device" : d.is_gateway ? " · gateway" : "");
  $("d-ip").textContent = d.ip;
  $("d-mac").textContent = d.mac || "—";
  $("d-vendor").textContent = d.vendor || "Unknown";
  $("d-host").textContent = d.hostname || "—";
  $("d-open").href = "http://" + d.ip;
  const wolBtn = $("d-wol");
  wolBtn.disabled = !d.mac;
  wolBtn.onclick = () => wakeAndSave({ mac: d.mac, ip: d.ip, name: deviceName(d), kind: d.kind });
  $("d-ssh").onclick = () => sshLaunch(d.ip, "", "");
  $("portResults").innerHTML = "";
  $("drawer").classList.remove("hidden");
}

async function scanPorts() {
  if (!state.selectedIp) return;
  const btn = $("portBtn");
  btn.disabled = true; btn.textContent = "Scanning ports…";
  const r = await fetch("/api/portscan?ip=" + encodeURIComponent(state.selectedIp));
  const data = await r.json();
  $("portResults").innerHTML = (data.services||[]).length
    ? data.services.map(s => `<div class="port-chip"><b>${s.port}</b> ${s.service||""}</div>`).join("")
    : '<div class="muted">No open common ports.</div>';
  btn.disabled = false; btn.textContent = "Scan open ports";
}

async function wake(mac) {
  if (!mac) return false;
  try {
    const r = await fetch("/api/wol?mac=" + encodeURIComponent(mac));
    const data = await r.json();
    if (r.ok && data.sent) return true;
  } catch { /* fall through */ }
  return false;
}

// Save the device so it can be woken later (when it's asleep & off the scan),
// then send the magic packet now.
async function wakeAndSave(d) {
  if (!d || !d.mac) return;
  try {
    await fetch("/api/saved", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mac: d.mac, ip: d.ip || "", name: d.name || "", kind: d.kind || "" }),
    });
  } catch { /* saving is best-effort */ }
  const ok = await wake(d.mac);
  toast(ok ? `📨 Saved & woke ${d.name || d.mac}` : `💾 Saved ${d.name || d.mac} · packet not sent`, !ok);
  if (!$("view-wol").classList.contains("hidden")) loadSaved();
}

/* ===================== saved (Wake-on-LAN) devices ===================== */
async function loadSaved() {
  let devs = [];
  try {
    const r = await fetch("/api/saved");
    devs = (await r.json()).devices || [];
  } catch { /* ignore */ }
  const tb = $("savedRows");
  tb.innerHTML = devs.map(d => {
    const t = TYPES[d.kind] || TYPES.device;
    return `<tr>
      <td>${escapeHtml(d.name || "—")}</td>
      <td class="mono">${escapeHtml(d.ip || "—")}</td>
      <td class="mono">${escapeHtml(d.mac)}</td>
      <td>${t.icon} ${t.label}</td>
      <td class="c-act">
        <button class="act" data-w="${d.mac}" data-n="${escapeHtml(d.name||"")}" title="Send Wake-on-LAN packet">⏰</button>
        <button class="act" data-rm="${d.mac}" title="Forget this device">🗑️</button>
      </td>
    </tr>`;
  }).join("");
  $("savedEmpty").classList.toggle("hidden", devs.length > 0);
  tb.querySelectorAll(".act[data-w]").forEach(b =>
    b.addEventListener("click", async () => {
      const ok = await wake(b.dataset.w);
      toast(ok ? `📨 Wake packet sent to ${b.dataset.n || b.dataset.w}`
               : `⚠️ Could not send packet`, !ok);
    }));
  tb.querySelectorAll(".act[data-rm]").forEach(b =>
    b.addEventListener("click", async () => {
      await fetch("/api/saved?mac=" + encodeURIComponent(b.dataset.rm), { method: "DELETE" });
      loadSaved();
    }));
}

async function addSaved() {
  const mac = $("wolMac").value.trim();
  const msg = $("wolAddMsg");
  if (!mac) { msg.textContent = "A MAC address is required to wake a device."; return; }
  const r = await fetch("/api/saved", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mac, ip: $("wolIp").value.trim(), name: $("wolName").value.trim(),
    }),
  });
  if (r.ok) {
    $("wolName").value = $("wolIp").value = $("wolMac").value = "";
    msg.textContent = "Saved.";
    loadSaved();
  } else {
    msg.textContent = (await r.json()).error || "Could not save device.";
  }
}

/* ===================== SSH ===================== */
function sshKeyVal() { return ($("sshKey").value || "").trim(); }

function buildSshCmd(host, user, port, key) {
  let c = "ssh";
  if (port && port !== "22") c += " -p " + port;
  if (key) c += " -i " + key;
  c += " " + (user ? user + "@" + host : host);
  return c;
}

function fmtTs(ts) {
  if (!ts) return "—";
  try { return new Date(ts * 1000).toLocaleString(); } catch { return "—"; }
}

async function sshLaunch(host, user, port) {
  const key = sshKeyVal();
  $("sshMsg").textContent = "Opening terminal…";
  try {
    const r = await fetch("/api/ssh-launch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host, user: user || "", port: port || "", key }),
    });
    const d = await r.json();
    if (r.ok && d.launched) { $("sshMsg").textContent = `Launched via ${d.method}: ${d.command}`; toast(`⌨️ ${d.command}`); }
    else { $("sshMsg").textContent = "⚠️ " + (d.error || "Could not open a terminal."); }
  } catch { $("sshMsg").textContent = "⚠️ Request failed."; }
}

async function sshCopy(host, user, port) {
  const cmd = buildSshCmd(host, user, port, sshKeyVal());
  try { await navigator.clipboard.writeText(cmd); toast(`⧉ Copied: ${cmd}`); }
  catch { $("sshMsg").textContent = "Command: " + cmd; }
}

async function loadSshHistory() {
  let data = { connections: [], history_files: [], note: "" };
  try { data = await (await fetch("/api/ssh-history")).json(); } catch { /* ignore */ }
  $("sshFiles").textContent = (data.history_files || []).join(", ") || "no history file";
  $("sshNote").textContent = data.note || "";
  const tb = $("sshRows");
  tb.innerHTML = (data.connections || []).map((c, i) => `
    <tr>
      <td class="mono">${escapeHtml(c.target)}</td>
      <td class="mono">${escapeHtml(c.port)}</td>
      <td>${c.count || "—"}</td>
      <td>${fmtTs(c.last_used)}</td>
      <td><span class="st">${escapeHtml(c.source)}</span></td>
      <td class="c-act">
        <button class="act" data-i="${i}" data-act="ssh-open" title="Open terminal">⌨️</button>
        <button class="act" data-i="${i}" data-act="ssh-copy" title="Copy ssh command">⧉</button>
      </td>
    </tr>`).join("");
  $("sshEmpty").classList.toggle("hidden", (data.connections || []).length > 0);
  const conns = data.connections || [];
  tb.querySelectorAll('.act[data-act="ssh-open"]').forEach(b =>
    b.addEventListener("click", () => { const c = conns[b.dataset.i]; sshLaunch(c.host, c.user, c.port); }));
  tb.querySelectorAll('.act[data-act="ssh-copy"]').forEach(b =>
    b.addEventListener("click", () => { const c = conns[b.dataset.i]; sshCopy(c.host, c.user, c.port); }));
}

/* ===================== theme ===================== */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = $("themeToggle");
  if (btn) btn.textContent = theme === "light" ? "☀️" : "🌙";
}
function initTheme() {
  const saved = localStorage.getItem("lanny-theme");
  const sys = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  applyTheme(saved || sys);
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  localStorage.setItem("lanny-theme", next);
  applyTheme(next);
}
initTheme();

let toastTimer = null;
function toast(msg, isError) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("error", !!isError);
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 3000);
}

/* ===================== view switching ===================== */
function switchView(view) {
  document.querySelectorAll(".nav-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.view === view));
  ["devices", "health", "traffic", "wol", "ssh"].forEach(v =>
    $("view-" + v).classList.toggle("hidden", v !== view));
  $("device-controls").style.display = view === "devices" ? "" : "none";
  if (view === "wol") loadSaved();
  if (view === "ssh") loadSshHistory();
}

/* ===================== network test ===================== */
function fmtMbps(v) { return v == null ? "—" : v + " Mbps"; }
function sevRank(s) { return { high: 0, medium: 1, low: 2 }[s] ?? 3; }

function renderCheck(key, title, data) {
  const card = document.createElement("div");
  card.className = "h-card";
  let body = "";

  if (data.error) {
    body = `<div class="bad">⚠️ ${escapeHtml(data.error)}</div>`;
  } else if (key === "speed") {
    body = `<div class="metrics">
      <div><span>${fmtMbps(data.download_mbps)}</span><label>Download</label></div>
      <div><span>${fmtMbps(data.upload_mbps)}</span><label>Upload</label></div>
      <div><span>${data.latency_ms ?? "—"} ms</span><label>Latency</label></div>
    </div>`;
  } else if (key === "latency") {
    body = (data.targets || []).map(t =>
      `<div class="row2"><span>${escapeHtml(t.label)}</span>
        <b class="${t.ok ? "" : "bad"}">${t.ok ? t.avg_ms + " ms · ±" + t.jitter_ms + " · " + t.loss + "% loss" : "unreachable"}</b></div>`).join("");
  } else if (key === "dns") {
    body = `<div class="row2"><span>Resolvers</span><b>${(data.resolvers||[]).join(", ")||"—"}</b></div>
      <div class="row2"><span>Avg lookup</span><b>${data.avg_ms ?? "—"} ms</b></div>
      <div class="row2"><span>Resolved</span><b>${data.resolved}/${data.total}</b></div>
      <div class="row2"><span>Hijack test</span><b class="${data.hijacked?"bad":"good"}">${data.hijacked?"⚠️ redirected":"✓ clean"}</b></div>`;
  } else if (key === "security") {
    const f = (data.findings || []).slice().sort((a,b)=>sevRank(a.severity)-sevRank(b.severity));
    body = `<div class="row2"><span>Router open ports</span><b>${(data.gateway_open_ports||[]).join(", ")||"none"}</b></div>`;
    body += f.length ? f.map(x =>
      `<div class="finding ${x.severity}"><b>${escapeHtml(x.service)}</b> :${x.port} · ${x.severity}
        <div class="muted">${escapeHtml(x.detail)}</div></div>`).join("")
      : `<div class="good">✓ No risky services exposed on the router.</div>`;
  } else if (key === "wifi") {
    if (!data.available) {
      body = `<div class="muted">${escapeHtml(data.reason || "Unavailable")}</div>`;
    } else {
      body = `<table class="mini"><tr><th>SSID</th><th>Ch</th><th>Signal</th><th>Security</th></tr>` +
        data.networks.map(n => `<tr><td>${escapeHtml(n.ssid||"(hidden)")}</td><td>${n.channel}</td><td>${n.signal}</td><td>${escapeHtml(n.security||"open")}</td></tr>`).join("") +
        `</table>`;
    }
  }
  card.innerHTML = `<div class="h-card-title">${escapeHtml(title)}</div>${body}`;
  return card;
}

function runHealth() {
  if (state.healthRunning) return;
  state.healthRunning = true;
  const btn = $("healthBtn"); btn.disabled = true; btn.classList.add("scanning");
  $("healthBtnLabel").textContent = "Testing…";
  $("healthGrid").innerHTML = "";
  $("scoreCard").classList.add("hidden");
  const cards = {};

  const es = new EventSource("/api/health");
  es.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.type === "running") {
      const ph = document.createElement("div");
      ph.className = "h-card pending";
      ph.innerHTML = `<div class="h-card-title">${escapeHtml(e.title)}</div><div class="muted">Running…</div>`;
      cards[e.key] = ph; $("healthGrid").appendChild(ph);
    } else if (e.type === "check") {
      const card = renderCheck(e.key, e.title, e.data);
      if (cards[e.key]) cards[e.key].replaceWith(card);
      else $("healthGrid").appendChild(card);
      cards[e.key] = card;
    } else if (e.type === "summary") {
      const d = e.data;
      $("scoreNum").textContent = d.score;
      $("scoreGrade").textContent = d.grade;
      $("scoreRing").className = "score-ring " +
        (d.score >= 75 ? "ok" : d.score >= 55 ? "warn" : "bad");
      $("scoreNotes").innerHTML = (d.notes||[]).length
        ? d.notes.map(n => `<li>${escapeHtml(n)}</li>`).join("")
        : "<li>No issues detected.</li>";
      $("scoreCard").classList.remove("hidden");
    } else if (e.type === "start") { /* total known */ }
  };
  const finish = () => {
    es.close(); state.healthRunning = false;
    btn.disabled = false; btn.classList.remove("scanning");
    $("healthBtnLabel").textContent = "Re-run tests";
  };
  // server closes stream after summary -> onerror fires; treat as done
  es.onerror = finish;
}

/* ===================== traffic monitor ===================== */
function renderSniff() {
  const f = (state.sniffFilter || "").toLowerCase();
  const tf = state.sniffType || "";
  const rows = state.sniffRows.filter(r =>
    (!tf || r.service === tf) &&
    (!f || r.process.toLowerCase().includes(f) || r.remote.toLowerCase().includes(f) ||
      (r.remote_host||"").toLowerCase().includes(f) || r.local.toLowerCase().includes(f)));

  $("sniffRows").innerHTML = rows.map(r => `
    <tr>
      <td><span class="pill ${r.proto.toLowerCase()}">${r.proto}</span></td>
      <td>${escapeHtml(r.service)}</td>
      <td class="mono">${escapeHtml(r.process || "—")}${r.pid?` <span class="muted">#${r.pid}</span>`:""}</td>
      <td class="mono">${escapeHtml(r.local)}</td>
      <td class="mono">${escapeHtml(r.remote || "—")}</td>
      <td>${escapeHtml(r.remote_host || "")}</td>
      <td><span class="st ${r.status==="ESTABLISHED"?"live":""}">${r.status}</span></td>
    </tr>`).join("");
  $("sniffEmpty").classList.toggle("hidden", rows.length > 0);
}

function updateTypeOptions() {
  const types = [...new Set(state.sniffRows.map(r => r.service))].sort();
  const sel = $("sniffType"), cur = sel.value;
  sel.innerHTML = '<option value="">All protocols</option>' +
    types.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
  sel.value = cur;
}

function toggleSniff() {
  if (state.sniffES) { stopSniff(); return; }
  const btn = $("sniffBtn"); btn.classList.add("scanning");
  $("sniffBtnLabel").textContent = "Stop monitor";
  $("sniffStat").textContent = "connecting…";
  const es = new EventSource("/api/sniff?interval=2");
  state.sniffES = es;
  es.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.type === "snapshot") {
      state.sniffRows = e.items;
      $("sniffStat").textContent = `${e.count} active connections · live`;
      updateTypeOptions();
      renderSniff();
    }
  };
  es.onerror = () => { $("sniffStat").textContent = "disconnected"; stopSniff(); };
}

function stopSniff() {
  if (state.sniffES) { state.sniffES.close(); state.sniffES = null; }
  $("sniffBtn").classList.remove("scanning");
  $("sniffBtnLabel").textContent = "Start monitor";
  if ($("sniffStat").textContent.includes("live")) $("sniffStat").textContent = "stopped";
}

document.addEventListener("DOMContentLoaded", () => {
  loadNetwork();
  $("scanBtn").addEventListener("click", startScan);
  $("closeDrawer").addEventListener("click", () => {
    $("drawer").classList.add("hidden");
    state.selectedIp = null; renderDevices();
  });
  $("portBtn").addEventListener("click", scanPorts);
  $("search").addEventListener("input", (e) => {
    state.filter = e.target.value; renderDevices();
  });
  document.querySelectorAll(".nav-btn").forEach(b =>
    b.addEventListener("click", () => switchView(b.dataset.view)));
  $("healthBtn").addEventListener("click", runHealth);
  $("sniffBtn").addEventListener("click", toggleSniff);
  $("themeToggle").addEventListener("click", toggleTheme);
  $("wolAddBtn").addEventListener("click", addSaved);
  $("wolMac").addEventListener("keydown", (e) => { if (e.key === "Enter") addSaved(); });

  // SSH: persist the identity key, wire manual-connect buttons
  const savedKey = localStorage.getItem("lanny-ssh-key");
  if (savedKey) $("sshKey").value = savedKey;
  $("sshKey").addEventListener("input", (e) => localStorage.setItem("lanny-ssh-key", e.target.value));
  $("sshOpenBtn").addEventListener("click", () => {
    const h = $("sshHost").value.trim();
    if (!h) { $("sshMsg").textContent = "Enter a host or IP."; return; }
    sshLaunch(h, $("sshUser").value.trim(), $("sshPort").value.trim());
  });
  $("sshCopyBtn").addEventListener("click", () => {
    const h = $("sshHost").value.trim();
    if (!h) { $("sshMsg").textContent = "Enter a host or IP."; return; }
    sshCopy(h, $("sshUser").value.trim(), $("sshPort").value.trim());
  });
  $("sniffFilter").addEventListener("input", (e) => {
    state.sniffFilter = e.target.value; renderSniff();
  });
  $("sniffType").addEventListener("change", (e) => {
    state.sniffType = e.target.value; renderSniff();
  });
});
