/* WELA front-end - vanilla JS, no external libraries (works offline). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TYPES = {
  shutdown: { label: "Normal shutdown", short: "Shutdown", color: "var(--ok)" },
  restart: { label: "Restart", short: "Restart", color: "var(--accent)" },
  hard: { label: "Hard shutdown", short: "Hard", color: "var(--bad)" },
  sleep: { label: "Sleep / resume", short: "Sleep", color: "var(--purple)" },
  unknown: { label: "Undetermined", short: "Undetermined", color: "var(--grey)" },
};
const STATE_COLOR = { healthy: "var(--ok)", slow: "var(--warn)", warning: "var(--warn)", reset: "var(--bad)",
  error: "var(--bad)", missing: "var(--bad)", "no data": "var(--grey)", info: "var(--grey)" };
const ICON = {
  warn: '<svg viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
  ok: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg>',
  pc: '<svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
  cal: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
  dl: '<svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
  file: '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="m5 3 14 9-14 9V3z"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  flask: '<svg viewBox="0 0 24 24"><path d="M9 3h6M10 3v6L4 20a1 1 0 0 0 .9 1.5h14.2A1 1 0 0 0 20 20l-6-11V3"/></svg>',
};

const S = { cases: [], c: null, tab: "overview", filter: "all", q: "", tl: null, selected: null, settings: null };

/* ------------------------------------------------------------------ utils */
const store = {
  get(k, d) { try { const v = localStorage.getItem("wela." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("wela." + k, JSON.stringify(v)); } catch { /* ignore */ } },
};
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
  return j;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}
function tzOffset() {
  const v = $("#tzSelect").value;
  return v === "local" ? -new Date().getTimezoneOffset() : parseInt(v, 10) || 0;
}
function tzLabel() {
  const m = tzOffset(); if (!m) return "UTC";
  const a = Math.abs(m); return `UTC${m > 0 ? "+" : "-"}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(a % 60).padStart(2, "0")}`;
}
function tsOf(iso) { return iso ? Date.parse(iso) / 1000 : null; }
function fmtTs(ts, withSec = true) {
  if (ts == null) return "—";
  const d = new Date((ts + tzOffset() * 60) * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}${withSec ? ":" + p(d.getUTCSeconds()) : ""}`;
}
const fmt = (iso, s = true) => fmtTs(tsOf(iso), s);
function fmtDur(sec) {
  if (sec == null) return "—";
  sec = Math.round(sec);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
  return `${Math.floor(sec / 86400)}d ${Math.floor((sec % 86400) / 3600)}h`;
}
const chip = (type, text) => `<span class="chip ${esc(type).replace(/\s/g, "")}"><i></i>${esc(text ?? TYPES[type]?.short ?? type)}</span>`;
const stateChip = (s) => `<span class="chip ${esc(s || "nodata").replace(/\s/g, "")}">${esc(s || "no data")}</span>`;
function confBar(c) {
  const col = c >= 0.8 ? "var(--ok)" : c >= 0.6 ? "var(--accent)" : c >= 0.35 ? "var(--warn)" : "var(--bad)";
  return `<div class="conf"><div class="bar"><b style="width:${Math.round(c * 100)}%;background:${col}"></b></div><span>${Math.round(c * 100)}%</span></div>`;
}
const confColor = (c) => (c >= 0.8 ? "var(--ok)" : c >= 0.6 ? "var(--accent)" : c >= 0.35 ? "var(--warn)" : "var(--bad)");
const CAUSE_CLS = { likely: "error", possible: "warning", no_evidence: "noevidence", unknown: "nodata", "n/a": "nodata" };
const EFFECT_CLS = { missing: "error", errors: "error", warnings: "warning", none: "healthy", unknown: "nodata" };
const causeChip = (d) => (d?.cause ? `<span class="chip ${CAUSE_CLS[d.cause]}">${esc(d.cause_label)}</span>` : "");
const effectChip = (d) => (d?.effect ? `<span class="chip ${EFFECT_CLS[d.effect]}">${esc(d.effect_label)}</span>` : "");
const isSuspect = (it) => ["likely", "possible"].includes(it.drive?.cause);
const hitAfter = (it) => ["errors", "missing"].includes(it.drive?.effect);
function fmtOff(s) {
  if (s == null) return "";
  const a = Math.abs(s);
  return `${s < 0 ? "−" : "+"}${a < 10 && a % 1 ? a.toFixed(1) : Math.round(a)}s`;
}

/* ------------------------------------------------------------------ sidebar */
async function loadCases() {
  try { S.cases = await api("/api/cases"); } catch { S.cases = []; }
  const el = $("#caseList");
  if (!S.cases.length) { el.innerHTML = '<div class="muted small pad">No cases yet</div>'; return; }
  el.innerHTML = S.cases.map((c) => `
    <div class="case-item ${S.c && S.c.id === c.id ? "active" : ""}" data-id="${esc(c.id)}">
      <div class="t">${esc(c.name)}</div>
      <div class="m"><span>${esc(fmt(c.generated, false))}</span>
        <span class="dotc"><i style="background:var(--bad)"></i>${c.counts?.hard ?? 0}</span>
        <span class="dotc"><i style="background:var(--warn)"></i>${c.counts?.needs_review ?? 0}</span></div>
    </div>`).join("");
  $$(".case-item", el).forEach((n) => n.addEventListener("click", () => openCase(n.dataset.id)));
}

/* ------------------------------------------------------------------ home */
function renderHome() {
  S.c = null; closeDrawer(); loadCases();
  const st = S.settings || {};
  const saved = store.get("paths", "");
  $("#main").innerHTML = `
  <div class="home">
    <div class="card hero">
      <h1>Analyze Windows event logs</h1>
      <p>Point WELA at a claim's <b>.evtx</b> files (System, Application, Storport) or the folder that holds them.
         It rebuilds every power cycle, checks what the drive was doing around each one, and flags anything uncertain.</p>
      <div class="dropzone">
        <textarea id="paths" spellcheck="false" placeholder="One file or folder per line, e.g.&#10;D:\\Claims\\DELL-12345\\Logs&#10;D:\\Claims\\DELL-12345\\System.evtx">${esc(saved)}</textarea>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn" id="pickFolder">${ICON.folder} Browse folder</button>
        <button class="btn" id="pickFiles">${ICON.file} Browse files</button>
        <input type="text" id="caseName" placeholder="Case name (optional)" style="width:220px">
        <div class="spacer"></div>
        <button class="btn ghost" id="demoBtn">${ICON.flask} Try demo data</button>
        <button class="btn primary" id="analyzeBtn">${ICON.play} Analyze</button>
      </div>
      <div class="err" id="err"></div>
      <details class="adv"><summary>Analysis settings</summary>
        <div class="settings">
          <label>Drive window before power-off &amp; after boot (seconds)<input type="number" id="s_drive" value="${st.drive_window_s ?? 60}" min="5"></label>
          <label>Restart if stop → boot gap below (seconds)<input type="number" id="s_restart" value="${st.restart_gap_s ?? 300}" min="10"></label>
          <label>Flag for review below confidence<input type="number" id="s_review" value="${st.review_threshold ?? 0.6}" step="0.05" min="0" max="1"></label>
          <label>Flag quiet gaps longer than (seconds)<input type="number" id="s_gap" value="${st.unexplained_gap_s ?? 7200}" min="600"></label>
        </div>
        <div class="note" style="margin-top:12px">Event rules and weights live in <span class="mono">wela/catalog.py</span>; override any of them with a <span class="mono">wela_config.json</span> next to <span class="mono">run_wela.py</span>.</div>
      </details>
    </div>
    <div class="steps">
      ${[["Merge", "All logs become one timeline in UTC, with coverage and gap checks per log."],
         ["Classify", "Each boot closes a session: clean stop, hard shutdown or undetermined — from redundant evidence."],
         ["Correlate", "Every Storport, disk, NVMe and PCIe event in the minute before power-off and after boot — did the drive cause it?"],
         ["Review", "Confidence per verdict, missing evidence listed, uncertain items flagged."]]
        .map(([b, s], i) => `<div class="card step"><div class="n">${i + 1}</div><b>${b}</b><span>${s}</span></div>`).join("")}
    </div>
  </div>`;
  $("#pickFolder").onclick = () => pick("folder");
  $("#pickFiles").onclick = () => pick("files");
  $("#analyzeBtn").onclick = () => analyze(false);
  $("#demoBtn").onclick = () => analyze(true);
  $("#paths").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) analyze(false); });
}
function readSettings() {
  const n = (id) => parseFloat($(id)?.value);
  const o = { drive_window_s: n("#s_drive"), restart_gap_s: n("#s_restart"), review_threshold: n("#s_review"), unexplained_gap_s: n("#s_gap") };
  Object.keys(o).forEach((k) => Number.isNaN(o[k]) && delete o[k]);
  return o;
}
async function pick(kind) {
  try {
    const r = await api("/api/pick", { method: "POST", body: JSON.stringify({ kind }) });
    if (r.paths?.length) {
      const ta = $("#paths");
      ta.value = (ta.value.trim() ? ta.value.trim() + "\n" : "") + r.paths.join("\n");
    }
  } catch (e) { showErr(e.message); }
}
function showErr(msg) { const el = $("#err"); if (!el) return toast(msg); el.textContent = msg; el.style.display = msg ? "block" : "none"; }
async function analyze(demo) {
  showErr("");
  const paths = $("#paths").value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  if (!demo && !paths.length) return showErr("Add at least one .evtx file or a folder.");
  const btn = demo ? $("#demoBtn") : $("#analyzeBtn"); btn.disabled = true;
  const old = btn.innerHTML; btn.innerHTML = '<span class="spin" style="width:15px;height:15px;border-width:2px"></span> Analyzing…';
  try {
    if (!demo) store.set("paths", $("#paths").value);
    const body = { paths, name: $("#caseName").value.trim() || undefined, settings: readSettings() };
    const r = await api(demo ? "/api/demo" : "/api/analyze", { method: "POST", body: JSON.stringify(body) });
    S.c = r; S.tab = "overview"; S.filter = "all"; S.q = ""; S.tl = null;
    await loadCases(); renderCase();
    toast(`Analyzed ${r.event_count.toLocaleString()} events in ${r.analysis_seconds}s`);
  } catch (e) { showErr(e.message); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

/* ------------------------------------------------------------------ case view */
async function openCase(id) {
  $("#main").innerHTML = '<div class="loading"><div class="spin"></div>Loading case…</div>';
  try { S.c = await api(`/api/cases/${encodeURIComponent(id)}`); S.tab = "overview"; S.filter = "all"; S.q = ""; S.tl = null; renderCase(); loadCases(); }
  catch (e) { toast(e.message); renderHome(); }
}
function renderCase() {
  const c = S.c; if (!c) return renderHome();
  const n = c.counts, integ = c.integrity;
  const dq = integ.missing_channels.length + integ.record_gaps.length + integ.clears.length + integ.time_changes.length +
    integ.unreadable_files.length + integ.clock_backwards.length;
  const tabs = [["overview", "Overview"], ["timeline", "Timeline"], ["cycles", "Power cycles", c.items.length],
    ["drive", "Drive", c.storage_events.length], ["quality", "Data quality", dq, dq > 0], ["smart", "SMART check"]];
  $("#main").innerHTML = `
    <div class="case-head">
      <div><h1>${esc(c.case_name)}</h1>
        <div class="meta">
          <span>${ICON.pc}${esc(c.computer || "unknown host")}</span>
          <span>${ICON.cal}${fmt(c.coverage.start, false)} → ${fmt(c.coverage.end, false)} <span class="muted">(${tzLabel()})</span></span>
          <span>${ICON.list}${c.event_count.toLocaleString()} events · ${c.sources.length} file(s)</span>
          <span>${ICON.clock}analyzed ${fmt(c.generated, false)}</span>
        </div></div>
      <div class="row">
        <div class="menu" id="expMenu"><button class="btn">${ICON.dl} Export</button>
          <div class="menu-pop">
            ${[["html", "HTML report", "to read / share"], ["xlsx", "Excel workbook", "attach to claim"], ["csv", "CSV", "power cycles"], ["json", "JSON", "full result"]]
              .map(([f, l, s]) => `<a href="/api/cases/${encodeURIComponent(c.id)}/export.${f}?tz=${tzOffset()}" download>${l}<small>${s}</small></a>`).join("")}
          </div></div>
        <button class="btn danger" id="delBtn" title="Delete case">${ICON.trash}</button>
      </div>
    </div>
    <div class="tabs">${tabs.map(([k, l, b, w]) => `<button class="tab ${S.tab === k ? "active" : ""}" data-tab="${k}">${l}${b != null ? ` <span class="badge ${w ? "warn" : ""}">${b}</span>` : ""}</button>`).join("")}</div>
    <div id="tabBody"></div>`;
  $$(".tab").forEach((t) => (t.onclick = () => { S.tab = t.dataset.tab; renderCase(); }));
  const menu = $("#expMenu"); menu.querySelector(".btn").onclick = (e) => { e.stopPropagation(); menu.classList.toggle("open"); };
  document.addEventListener("click", () => menu.classList.remove("open"), { once: true });
  const del = $("#delBtn");
  del.onclick = async () => {
    if (!del.dataset.armed) { del.dataset.armed = "1"; del.innerHTML = `${ICON.trash} Confirm delete`; setTimeout(() => { if (del.isConnected) { delete del.dataset.armed; del.innerHTML = ICON.trash; } }, 3000); return; }
    await api(`/api/cases/${encodeURIComponent(c.id)}`, { method: "DELETE" }); toast("Case deleted"); renderHome();
  };
  ({ overview: tabOverview, timeline: tabTimeline, cycles: tabCycles, drive: tabDrive, quality: tabQuality, smart: tabSmart })[S.tab]();
}

/* ------------------------------------------------------------------ overview */
function tabOverview() {
  const c = S.c, n = c.counts;
  const sleepTotal = n.sleep + n.hibernate + n.modern_standby;
  const tiles = [
    ["shutdown", n.shutdown, "Normal shutdowns", subOf("shutdown")],
    ["restart", n.restart, "Restarts", subOf("restart")],
    ["hard", n.hard, "Hard shutdowns", subOf("hard")],
    ["sleep", sleepTotal, "Sleep / hibernate", [n.sleep && `${n.sleep} S3`, n.hibernate && `${n.hibernate} hibernate`, n.modern_standby && `${n.modern_standby} standby`].filter(Boolean).join(" · ")],
    ["unknown", n.unknown, "Undetermined", "type could not be decided"],
    ["review", n.needs_review, "Needs review", "low confidence or warnings"],
  ];
  const colors = { review: "var(--warn)" };
  const hb = Object.entries(c.hard_breakdown).sort((a, b) => b[1] - a[1]);
  const maxHb = Math.max(1, ...hb.map((x) => x[1]));
  const review = c.items.filter((x) => x.needs_review).slice(0, 7);
  const t0 = c.coverage.start_ts, t1 = c.coverage.end_ts, span = Math.max(1, t1 - t0);
  const st = Object.entries(c.storage_counts).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const maxSt = Math.max(1, ...st.map((x) => x[1]));
  const suspects = c.items.filter(isSuspect).slice(0, 6);
  const dstats = [["likely", "Likely", "drive"], ["possible", "Possibly", "drive"], ["no_evidence", "No drive evidence"], ["unknown", "Can't tell"]];
  $("#tabBody").innerHTML = `
    <div class="tiles">${tiles.map(([k, v, l, s]) => `
      <div class="card tile" data-f="${k}" style="--c:${colors[k] || TYPES[k].color}">
        <div class="v">${v}</div><div class="l">${l}</div><div class="s">${esc(s || "")}</div></div>`).join("")}</div>
    <div class="grid g2">
      <div class="card span2"><div class="card-h"><h3>Did the drive cause it?</h3><span class="muted small">hard shutdowns &amp; undetermined · drive checked ${esc(c.settings.drive_window_s)}s before power-off and after boot</span></div>
        <div class="card-b">${n.drive_likely === undefined ? '<div class="muted">Re-run the analysis to get the drive assessment for this case.</div>' : `
          <div class="dstats">${dstats.map(([k, l, f]) => `<div class="dstat ${k}" ${f ? `data-f="${f}"` : ""}><b>${n["drive_" + k]}</b><span>${l}</span></div>`).join("")}
            <div class="dstat effect" data-f="effect"><b>${n.drive_effect}</b><span>drive errors right after boot / wake</span></div></div>
          <div class="muted small" style="margin:2px 0 6px">“No drive evidence” is not proof the drive is fine — a drive that froze suddenly may not have been able to save its last events. Cross-check its SMART and error logs.</div>
          ${suspects.length ? suspects.map((it) => `
            <div class="list-row" data-id="${it.id}">${chip(it.type)}<div style="flex:1;min-width:0"><div class="lt">${esc(it.id)} · ${esc(it.subtype)}</div>
              <div class="muted small">${fmt(it.time)} · ${esc(it.drive.reasons[0] || "")}</div></div>${causeChip(it.drive)}</div>`).join("")
            : '<div class="muted" style="padding-top:8px">No power cycle points at the drive.</div>'}`}
        </div></div>
      <div class="card"><div class="card-h"><h3>Hard shutdown causes</h3><span class="muted small">${n.hard} total</span></div>
        <div class="card-b">${hb.length ? hb.map(([k, v]) => `<div class="hbar"><span>${esc(k)}</span><div class="track"><b style="width:${(v / maxHb) * 100}%;background:var(--bad)"></b></div><span class="n">${v}</span></div>`).join("")
          : '<div class="muted">No hard shutdowns found.</div>'}</div></div>
      <div class="card"><div class="card-h"><h3>Needs review</h3><span class="muted small">${n.needs_review} item(s)</span></div>
        <div class="card-b" style="padding-top:6px;padding-bottom:6px">${review.length ? review.map((it) => `
          <div class="list-row" data-id="${it.id}">${chip(it.type)}<div style="flex:1;min-width:0"><div class="lt">${esc(it.subtype)}</div>
            <div class="muted small">${fmt(it.time)} · ${esc(it.flags[0]?.text || "low confidence")}</div></div>${confBar(it.confidence)}</div>`).join("")
          : '<div class="muted" style="padding:10px 0">Nothing flagged — every verdict has solid evidence.</div>'}</div></div>
      <div class="card"><div class="card-h"><h3>Log coverage</h3><span class="muted small">${tzLabel()}</span></div>
        <div class="card-b">${c.channels.filter((ch) => ch.kind !== "other" || ch.events > 0).map((ch) => `
          <div class="cov"><span title="${esc(ch.channel)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(shortChan(ch.channel))} <span class="muted">· ${ch.events.toLocaleString()}</span></span>
          <div class="track"><b class="${ch.kind}" style="left:${((ch.start_ts - t0) / span) * 100}%;width:${Math.max(0.6, ((ch.end_ts - ch.start_ts) / span) * 100)}%"></b></div></div>`).join("")}
          <div class="cov" style="margin-top:2px"><span></span><div class="axis"><span>${fmt(c.coverage.start, false)}</span><span>${fmt(c.coverage.end, false)}</span></div></div>
          ${c.integrity.missing_channels.length ? `<div class="flagbox warn" style="margin-top:10px">${ICON.warn}<span>Missing: ${esc(c.integrity.missing_channels.join(", "))} log — related checks are limited.</span></div>` : ""}
        </div></div>
      <div class="card"><div class="card-h"><h3>Storage events</h3><span class="muted small">${c.storage_events.length} warning/error events</span></div>
        <div class="card-b">${st.length ? st.map(([k, v]) => `<div class="hbar"><span>${esc(k)}</span><div class="track"><b style="width:${(v / maxSt) * 100}%;background:var(--warn)"></b></div><span class="n">${v}</span></div>`).join("")
          : '<div class="muted">No storage warnings or errors logged.</div>'}
          ${c.disks.length ? `<div class="muted small" style="margin-top:12px">Drive: <b style="color:var(--ink)">${esc(c.disks[0].Model || "")}</b> · FW ${esc(c.disks[0].Revision || c.disks[0].FirmwareRevision || "?")} · SN ${esc(c.disks[0].SerialNumber || "?")}</div>` : ""}
        </div></div>
    </div>`;
  $$(".tile, .dstat[data-f]").forEach((t) => (t.onclick = () => { S.filter = t.dataset.f; S.tab = "cycles"; renderCase(); }));
  $$(".list-row").forEach((r) => (r.onclick = () => openDetail(r.dataset.id)));
}
function subOf(type) {
  const m = {};
  S.c.items.filter((x) => x.type === type).forEach((x) => (m[x.subtype] = (m[x.subtype] || 0) + 1));
  return Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ");
}
function shortChan(ch) {
  return ch.replace("Microsoft-Windows-", "").replace("Storage-Storport/Operational", "Storport").replace("/Diagnostic", " (diag)");
}

/* ------------------------------------------------------------------ power cycles */
function filtered() {
  const q = S.q.toLowerCase();
  return S.c.items.filter((it) => {
    if (S.filter === "review" && !it.needs_review) return false;
    if (S.filter === "drive" && !isSuspect(it)) return false;
    if (S.filter === "effect" && !hitAfter(it)) return false;
    if (!["all", "review", "drive", "effect"].includes(S.filter) && it.type !== S.filter) return false;
    if (!q) return true;
    return `${it.id} ${it.type} ${it.subtype} ${it.drive?.state} ${it.drive?.cause_label ?? ""} ${it.drive?.effect_label ?? ""} ${it.flags.map((f) => f.text).join(" ")} ${it.evidence_found.map((e) => e.eid).join(" ")}`.toLowerCase().includes(q);
  });
}
function tabCycles() {
  const n = S.c.counts;
  const f = [["all", "All", S.c.items.length], ["shutdown", "Shutdown", n.shutdown], ["restart", "Restart", n.restart],
    ["hard", "Hard", n.hard], ["sleep", "Sleep", n.sleep + n.hibernate + n.modern_standby], ["unknown", "Undetermined", n.unknown],
    ["review", "Needs review", n.needs_review], ["drive", "Drive suspected", (n.drive_likely ?? 0) + (n.drive_possible ?? 0)],
    ["effect", "Drive errors after", n.drive_effect ?? 0]];
  $("#tabBody").innerHTML = `
    <div class="row" style="margin-bottom:12px">
      ${f.map(([k, l, c]) => `<button class="fchip ${S.filter === k ? "on" : ""}" data-f="${k}">${l}<span class="badge">${c}</span></button>`).join("")}
      <div class="spacer"></div>
      <input type="search" id="q" placeholder="Search detail, flags, event ID…" value="${esc(S.q)}" style="width:250px">
    </div>
    <div class="card"><div class="tbl-wrap" style="max-height:calc(100vh - 290px)"><table class="t" id="cyc"></table></div></div>`;
  $$(".fchip").forEach((b) => (b.onclick = () => { S.filter = b.dataset.f; tabCycles(); }));
  const q = $("#q"); q.oninput = () => { S.q = q.value; drawCycleRows(); };
  drawCycleRows();
}
function drawCycleRows() {
  const rows = filtered();
  const el = $("#cyc");
  if (!rows.length) { el.innerHTML = '<tr><td class="empty">Nothing matches this filter.</td></tr>'; return; }
  el.innerHTML = `<thead><tr><th>ID</th><th>Time (${tzLabel()})</th><th>Type</th><th>Detail</th><th>Off / asleep</th><th>Confidence</th><th>Drive</th><th>Drive caused it?</th><th>Flags</th></tr></thead><tbody>
    ${rows.map((it) => {
      const warn = it.flags.filter((x) => x.severity === "warn").length;
      return `<tr class="click ${S.selected === it.id ? "sel" : ""}" data-id="${it.id}">
        <td class="mono">${it.id}</td><td style="white-space:nowrap">${fmt(it.time)}</td><td>${chip(it.type)}</td>
        <td>${esc(it.subtype)}${it.wake_source ? `<div class="muted small">wake: ${esc(it.wake_source)}</div>` : ""}</td>
        <td style="white-space:nowrap">${esc(it.type === "sleep" ? it.duration : it.gap)}</td>
        <td>${confBar(it.confidence)}</td><td>${stateChip(it.drive?.state)}</td>
        <td>${it.type === "sleep" ? '<span class="muted">—</span>' : causeChip(it.drive)}</td>
        <td>${warn ? `<span class="flagdot">${ICON.warn}${warn}</span>` : it.flags.length ? `<span class="muted small">${it.flags.length} note${it.flags.length > 1 ? "s" : ""}</span>` : ""}</td></tr>`;
    }).join("")}</tbody>`;
  $$("tr.click", el).forEach((r) => (r.onclick = () => openDetail(r.dataset.id)));
}

/* ------------------------------------------------------------------ detail drawer */
function openDrawer(html) {
  const d = $("#drawer"); d.innerHTML = html; d.classList.add("open"); d.setAttribute("aria-hidden", "false");
  $("#drawerBack").classList.add("open"); d.querySelector(".dr-close")?.addEventListener("click", closeDrawer);
}
function closeDrawer() {
  $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#drawerBack").classList.remove("open");
  S.selected = null; $$("#cyc tr.sel").forEach((r) => r.classList.remove("sel"));
}
function openDetail(id) {
  const it = S.c.items.find((x) => x.id === id); if (!it) return;
  S.selected = id; $$("#cyc tr").forEach((r) => r.classList.toggle("sel", r.dataset.id === id));
  const isSleep = it.type === "sleep";
  const kv = isSleep
    ? [["Asleep from", fmt(it.time)], ["Woke at", fmt(it.end)], ["Duration", it.duration], ["Wake source", it.wake_source || "—"], ["Kind", it.subtype]]
    : [["Last sign of life", fmt(it.last_alive)], ["Clean stop logged", it.stop_time ? fmt(it.stop_time) : "—"], ["Next boot", fmt(it.boot_time)],
       ["Off for", it.gap], ["Boot type", it.boot_type || "not logged"]];
  const nFound = new Set(it.evidence_found.map((e) => e.signal)).size;
  const win = (w, label, from) => !w ? "" : `<div class="win"><div class="win-h"><span><b>${label}</b> · ${fmt(w.from)} → ${fmt(w.to)}</span>${stateChip(w.state)}</div>
      ${w.events.length ? `<div class="wev">${w.events.map((e) => `
        <div class="wrow ${e.state === "info" ? "info" : ""}" data-idx="${e.idx}" title="Click for the full event data">
          <span class="off mono">${fmtOff(e.offset_s) || fmt(e.time).slice(11)}</span><span class="mono"><b>${e.eid}</b></span>
          <div class="wx"><div>${esc(e.label)} <span class="muted">· ${esc(e.provider.replace("Microsoft-Windows-", ""))}</span></div>${e.fields ? `<div class="wf mono">${esc(e.fields)}</div>` : ""}</div>
          ${stateChip(e.state)}</div><pre class="data" style="display:none"></pre>`).join("")}</div>
        ${w.total > w.events.length ? `<div class="muted small">Showing the first ${w.events.length} of ${w.total} events.</div>` : ""}`
        : `<div class="muted small">${w.state === "no data" ? "No log covers this window." : "No drive events in this window."}</div>`}
      <div class="muted small" style="margin-top:4px">Offsets from the ${from}${w.storport_covered ? "" : " · Storport log not available for this time"}</div></div>`;
  const d = it.drive || {};
  const driveSec = `<div class="sec"><h4>Drive at this ${isSleep ? "sleep" : "power cycle"}</h4>
      ${d.cause ? `<div class="assess">
        ${isSleep ? "" : `<div class="a-row"><span>Did the drive cause it?</span>${causeChip(d)}</div>`}
        <div class="a-row"><span>Effect on the drive</span>${effectChip(d)}</div>
        <ul class="reasons">${d.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`
        : '<div class="note" style="margin-bottom:10px">Re-run the analysis to get the drive assessment for this case.</div>'}
      ${win(d.before, isSleep ? "Before sleep" : "Before power-off", isSleep ? "sleep entry" : "last logged event")}
      ${win(d.after, isSleep ? "After wake" : "After boot", isSleep ? "wake" : "boot")}</div>`;
  const anchor = (it.evidence_found[it.evidence_found.length - 1] || it.evidence_found[0])?.idx;
  openDrawer(`
    <div class="dr-h"><div style="flex:1">
        <div class="row" style="gap:6px">${chip(it.type, TYPES[it.type].label)}${it.needs_review ? chip("review", "Needs review") : ""}<span class="muted small mono">${it.id}</span></div>
        <h2>${esc(it.subtype)}</h2><div class="muted small">${fmt(it.time)} ${tzLabel()}</div></div>
      <button class="icon-btn dr-close" aria-label="Close">${ICON.x}</button></div>
    <div class="dr-b">
      <div class="sec"><dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
      ${driveSec}
      <div class="sec"><h4>Confidence</h4>
        <div class="bigconf"><strong style="color:${confColor(it.confidence)}">${Math.round(it.confidence * 100)}%</strong>
          <div class="bar"><b style="width:${it.confidence * 100}%;background:${confColor(it.confidence)}"></b></div></div>
        <div class="muted small" style="margin-top:6px">${nFound} signal(s) found${it.evidence_missing.length ? `, ${it.evidence_missing.length} expected signal(s) not logged` : ", nothing expected is missing"}.</div></div>
      ${it.flags.length ? `<div class="sec"><h4>Flags</h4>${it.flags.map((f) => `<div class="flagbox ${f.severity}">${f.severity === "warn" ? ICON.warn : ICON.info}<span>${esc(f.text)}</span></div>`).join("")}</div>` : ""}
      <div class="sec"><h4>Evidence found</h4>${it.evidence_found.length ? it.evidence_found.map((e) => `
        <div class="evi"><span class="id">${e.eid}</span><div class="x"><b>${esc(e.label)}</b><div>${fmt(e.time)} · ${esc(e.provider)}${e.note ? `<br>${esc(e.note)}` : ""}</div></div>
        <button class="btn ghost small ctx" data-idx="${e.idx}" style="padding:3px 8px">context</button></div>`).join("") : '<div class="muted small">No direct evidence — verdict is inferred.</div>'}
        ${it.evidence_missing.map((m) => `<div class="evi miss"><span class="id">—</span><div class="x"><b>${esc(m)}</b><div>expected, not logged</div></div></div>`).join("")}</div>
      <div class="sec"><h4>Raw events</h4><div id="rawBox"><button class="btn" id="rawBtn" data-idx="${anchor ?? ""}">${ICON.list} Show events around this point</button></div></div>
    </div>`);
  $$(".wrow").forEach((r) => r.addEventListener("click", async () => {
    const box = r.nextElementSibling;
    if (box.style.display !== "none") { box.style.display = "none"; return; }
    box.style.display = "";
    if (box.textContent) return;
    box.textContent = "Loading…";
    try {
      const [e] = await api(`/api/cases/${encodeURIComponent(S.c.id)}/events?around=${r.dataset.idx}&n=0`);
      box.textContent = JSON.stringify(e?.data ?? {}, null, 1);
    } catch (err) { box.textContent = err.message; }
  }));
  $("#rawBtn")?.addEventListener("click", (e) => loadRaw(e.currentTarget.dataset.idx));
  $$(".ctx").forEach((b) => b.addEventListener("click", () => loadRaw(b.dataset.idx, true)));
}
async function loadRaw(idx, scroll) {
  if (idx === "" || idx == null) return;
  const box = $("#rawBox"); box.innerHTML = '<div class="loading" style="padding:12px"><div class="spin"></div></div>';
  if (scroll) box.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const evs = await api(`/api/cases/${encodeURIComponent(S.c.id)}/events?around=${idx}&n=20`);
    box.innerHTML = `<div class="card" style="box-shadow:none"><div class="tbl-wrap" style="max-height:420px"><table class="t raw"><thead><tr><th>Time</th><th>Log</th><th>Provider</th><th>ID</th></tr></thead><tbody>
      ${evs.map((e) => `<tr class="click ${String(e.idx) === String(idx) ? "hl" : ""}" data-i="${e.idx}"><td>${fmt(e.time).slice(5)}</td><td>${esc(shortChan(e.channel))}</td>
        <td>${esc(e.provider.replace("Microsoft-Windows-", ""))}</td><td><b>${e.eid}</b></td></tr>
        <tr class="dat" data-for="${e.idx}" style="display:none"><td colspan="4"><pre class="data">${esc(JSON.stringify(e.data, null, 1))}</pre></td></tr>`).join("")}
      </tbody></table></div></div><div class="muted small" style="margin-top:6px">Click a row to see its event data. Highlighted row is the selected evidence.</div>`;
    $$("tr.click", box).forEach((r) => (r.onclick = () => { const d = $(`tr.dat[data-for="${r.dataset.i}"]`, box); d.style.display = d.style.display === "none" ? "" : "none"; }));
    $("tr.hl", box)?.scrollIntoView({ block: "center" });
  } catch (e) { box.innerHTML = `<div class="err" style="display:block">${esc(e.message)}</div>`; }
}
function openContext(idx, title) {
  openDrawer(`<div class="dr-h"><div style="flex:1"><h2>${esc(title)}</h2><div class="muted small">Events around this record</div></div>
    <button class="icon-btn dr-close" aria-label="Close">${ICON.x}</button></div><div class="dr-b"><div id="rawBox"></div></div>`);
  loadRaw(idx);
}

/* ------------------------------------------------------------------ timeline */
function tabTimeline() {
  const c = S.c;
  if (!S.tl) { const pad = (c.coverage.end_ts - c.coverage.start_ts) * 0.01 || 60; S.tl = { t0: c.coverage.start_ts - pad, t1: c.coverage.end_ts + pad }; }
  $("#tabBody").innerHTML = `
    <div class="card"><div class="card-h"><h3>Timeline</h3>
      <div class="tl-tools"><span class="muted small">Scroll to zoom · drag to pan · click a marker for details</span>
        <button class="btn" id="zin">+</button><button class="btn" id="zout">−</button><button class="btn" id="zfit">Fit</button></div></div>
      <div class="card-b"><div class="tl-wrap" id="tlwrap"><svg id="tlsvg"></svg></div>
      <div class="legend">
        <span><i style="background:var(--accent);opacity:.35"></i>Powered on (boot session)</span>
        ${Object.entries(TYPES).map(([k, v]) => `<span><i style="background:${v.color}"></i>${v.label}</span>`).join("")}
        <span><i style="background:var(--warn)"></i>Storage warning</span><span><i style="background:var(--bad)"></i>Storage error / reset</span>
      </div></div></div>`;
  drawTimeline();
  const svg = $("#tlsvg");
  svg.addEventListener("wheel", (e) => { e.preventDefault(); const r = svg.getBoundingClientRect(); zoomAt((e.clientX - r.left) / r.width, e.deltaY > 0 ? 1.25 : 0.8); }, { passive: false });
  let drag = null;
  svg.addEventListener("mousedown", (e) => { drag = { x: e.clientX, t0: S.tl.t0, t1: S.tl.t1 }; svg.classList.add("drag"); });
  window.addEventListener("mouseup", () => { drag = null; svg.classList.remove("drag"); });
  svg.addEventListener("mousemove", (e) => {
    if (!drag) return;
    const r = svg.getBoundingClientRect(), dt = ((drag.x - e.clientX) / (r.width - 150)) * (drag.t1 - drag.t0);
    S.tl.t0 = drag.t0 + dt; S.tl.t1 = drag.t1 + dt; drawTimeline();
  });
  $("#zin").onclick = () => zoomAt(0.5, 0.6); $("#zout").onclick = () => zoomAt(0.5, 1.6);
  $("#zfit").onclick = () => { S.tl = null; tabTimeline(); };
  window.onresize = () => S.tab === "timeline" && drawTimeline();
}
function zoomAt(frac, k) {
  const LW = 150, W = $("#tlsvg").getBoundingClientRect().width;
  const f = Math.min(1, Math.max(0, (frac * W - LW) / (W - LW - 16)));
  const span = S.tl.t1 - S.tl.t0, ns = Math.max(120, span * k), at = S.tl.t0 + f * span;
  S.tl.t0 = at - f * ns; S.tl.t1 = at + (1 - f) * ns; drawTimeline();
}
function drawTimeline() {
  const svg = $("#tlsvg"), c = S.c; if (!svg) return;
  const W = svg.getBoundingClientRect().width || 900, LW = 150, R = 16;
  const chans = c.channels;
  const lanes = [["Power state", 34], ["Transitions", 34], ["Sleep", 26], ["Drive events", 26], ...chans.map((ch) => [shortChan(ch.channel), 18])];
  let y = 34; const ly = lanes.map(([n, h]) => { const o = { n, y, h }; y += h + 8; return o; });
  const H = y + 6; svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.height = H + "px";
  const { t0, t1 } = S.tl, x = (t) => LW + ((t - t0) / (t1 - t0)) * (W - LW - R);
  const vis = (a, b) => b >= t0 && a <= t1;
  const out = [];
  // grid + axis
  const span = t1 - t0, steps = [60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400, 172800, 604800];
  const step = steps.find((s) => span / s <= 9) || 604800;
  const off = tzOffset() * 60;
  for (let t = Math.ceil((t0 + off) / step) * step - off; t <= t1; t += step) {
    const xx = x(t); if (xx < LW) continue;
    out.push(`<line x1="${xx}" x2="${xx}" y1="22" y2="${H - 4}" stroke="var(--line-2)"/>`);
    const lbl = step >= 86400 ? fmtTs(t, false).slice(5, 10) : step >= 3600 ? fmtTs(t, false).slice(5, 16) : fmtTs(t, false).slice(11, 16);
    out.push(`<text x="${xx + 3}" y="15" font-size="10.5" fill="var(--muted)">${lbl}</text>`);
  }
  ly.forEach((l) => out.push(`<text x="10" y="${l.y + l.h / 2 + 4}" font-size="11.5" fill="var(--ink-2)" font-weight="${l.h > 20 ? 600 : 400}">${esc(l.n.length > 22 ? l.n.slice(0, 21) + "…" : l.n)}</text>`,
    `<rect x="${LW}" y="${l.y}" width="${W - LW - R}" height="${l.h}" rx="5" fill="var(--panel-2)"/>`));
  const clipX = (a, b) => [Math.max(LW, x(a)), Math.min(W - R, x(b))];
  // sessions
  const L0 = ly[0];
  c.sessions.forEach((s) => {
    if (!vis(s.start_ts, s.end_ts)) return; const [a, b] = clipX(s.start_ts, s.end_ts);
    out.push(`<rect class="hit" data-tip="${esc(`<b>Boot session ${s.id}</b>${fmtTs(s.start_ts)} → ${fmtTs(s.end_ts)}<br>${s.boot_type || (s.partial_start ? "started before log" : "")}`)}" x="${a}" y="${L0.y + 6}" width="${Math.max(2, b - a)}" height="${L0.h - 12}" rx="4" fill="var(--accent)" opacity=".28"/>`);
  });
  // transitions
  const L1 = ly[1], L2 = ly[2];
  c.items.forEach((it) => {
    const col = TYPES[it.type].color, tip = esc(`<b>${it.id} · ${TYPES[it.type].label}</b>${esc(it.subtype)}<br>${fmtTs(it.time_ts)} · ${Math.round(it.confidence * 100)}%${it.needs_review ? " · needs review" : ""}${isSuspect(it) ? `<br>Drive caused it? ${esc(it.drive.cause_label)}` : ""}`);
    if (it.type === "sleep") {
      const a = it.start_ts || it.end_ts, b = it.end_ts || it.start_ts; if (!vis(a, b)) return;
      const [xa, xb] = clipX(a, b);
      out.push(`<rect class="hit mk" data-id="${it.id}" data-tip="${tip}" x="${xa}" y="${L2.y + 5}" width="${Math.max(5, xb - xa)}" height="${L2.h - 10}" rx="3" fill="${col}" opacity="${it.needs_review ? .55 : .85}"/>`);
      if (it.open) out.push(`<text x="${xb + 4}" y="${L2.y + L2.h / 2 + 4}" font-size="11" fill="${col}">no resume</text>`);
      return;
    }
    const a = it.last_alive_ts || it.boot_ts, b = it.boot_ts; if (!vis(a, b)) return;
    const [xa, xb] = clipX(a, b), cy = L1.y + L1.h / 2;
    out.push(`<line x1="${xa}" x2="${xb}" y1="${cy}" y2="${cy}" stroke="${col}" stroke-width="2" stroke-dasharray="3 3" opacity=".7"/>`);
    out.push(`<g class="hit mk" data-id="${it.id}" data-tip="${tip}" transform="translate(${x(a)},${cy})"><circle r="${it.needs_review ? 8 : 7}" fill="${col}" stroke="var(--panel)" stroke-width="2"/>
      ${it.needs_review ? '<circle r="11" fill="none" stroke="var(--warn)" stroke-width="1.5"/>' : ""}</g>`);
  });
  // drive events
  const L3 = ly[3];
  c.storage_events.forEach((e) => {
    const t = tsOf(e.time); if (!vis(t, t)) return;
    const col = STATE_COLOR[e.state] || "var(--warn)";
    out.push(`<rect class="hit ctxe" data-idx="${e.idx}" data-tip="${esc(`<b>${e.eid} · ${esc(e.label)}</b>${esc(e.provider)}<br>${fmt(e.time)}`)}" x="${x(t) - 2}" y="${L3.y + 4}" width="4" height="${L3.h - 8}" rx="1.5" fill="${col}"/>`);
  });
  // coverage
  chans.forEach((ch, i) => {
    const l = ly[4 + i]; if (!vis(ch.start_ts, ch.end_ts)) return; const [a, b] = clipX(ch.start_ts, ch.end_ts);
    const col = ch.kind === "storport" ? "var(--purple)" : ch.kind === "application" ? "var(--ok)" : ch.kind === "system" ? "var(--accent)" : "var(--grey)";
    out.push(`<rect x="${a}" y="${l.y + 5}" width="${Math.max(2, b - a)}" height="${l.h - 10}" rx="3" fill="${col}" opacity=".55"/>`);
  });
  c.integrity.record_gaps.forEach((g) => {
    if (!vis(g.start_ts, g.end_ts)) return; const [a, b] = clipX(g.start_ts, g.end_ts);
    out.push(`<rect class="hit" data-tip="${esc(`<b>${g.missing} records missing</b>${esc(g.channel)}<br>${fmt(g.start)} → ${fmt(g.end)}`)}" x="${a}" y="26" width="${Math.max(3, b - a)}" height="${H - 30}" fill="var(--warn)" opacity=".14"/>`);
  });
  svg.innerHTML = out.join("");
  const tt = $("#tooltip");
  $$(".hit", svg).forEach((n) => {
    n.addEventListener("mousemove", (e) => { tt.innerHTML = n.dataset.tip; tt.style.opacity = 1; tt.style.left = Math.min(innerWidth - 310, e.clientX + 14) + "px"; tt.style.top = e.clientY + 14 + "px"; });
    n.addEventListener("mouseleave", () => (tt.style.opacity = 0));
  });
  $$(".mk", svg).forEach((n) => n.addEventListener("click", (e) => { e.stopPropagation(); tt.style.opacity = 0; openDetail(n.dataset.id); }));
  $$(".ctxe", svg).forEach((n) => n.addEventListener("click", () => { tt.style.opacity = 0; openContext(n.dataset.idx, "Storage event"); }));
  $$(".mk,.ctxe", svg).forEach((n) => n.addEventListener("mousedown", (e) => e.stopPropagation()));
}

/* ------------------------------------------------------------------ drive */
function tabDrive() {
  const c = S.c;
  const states = ["all", ...new Set(c.storage_events.map((e) => e.state))];
  $("#tabBody").innerHTML = `
    ${c.disks.length ? `<div class="grid g3" style="margin-bottom:16px">${c.disks.map((d) => `<div class="card card-b">
      <div class="muted small">Disk seen in logs · ${fmt(d.first_seen, false)}</div><div style="font-weight:700;font-size:15px;margin:3px 0 8px">${esc(d.Model || "Unknown model")}</div>
      <dl class="kv">${Object.entries(d).filter(([k]) => !["Model", "first_seen"].includes(k)).map(([k, v]) => `<dt>${esc(k)}</dt><dd class="mono">${esc(v)}</dd>`).join("")}</dl></div>`).join("")}</div>`
      : `<div class="note" style="margin-bottom:16px">No disk inventory events (Partition/Diagnostic 1006) in these logs — add that log to see model, firmware and serial.</div>`}
    <div class="card"><div class="card-h"><h3>Storage warnings &amp; errors</h3>
      <div class="row"><label class="muted small">State <select id="stF">${states.map((s) => `<option>${esc(s)}</option>`).join("")}</select></label></div></div>
      <div class="tbl-wrap" style="max-height:calc(100vh - 380px)"><table class="t" id="stT"></table></div></div>`;
  const draw = () => {
    const f = $("#stF").value, rows = c.storage_events.filter((e) => f === "all" || e.state === f);
    $("#stT").innerHTML = rows.length ? `<thead><tr><th>Time (${tzLabel()})</th><th>ID</th><th>Meaning</th><th>Provider</th><th>Log</th><th>State</th><th>Near</th></tr></thead><tbody>${rows.map((e) => {
      const t = tsOf(e.time), near = nearestItem(t);
      return `<tr class="click" data-idx="${e.idx}"><td style="white-space:nowrap">${fmt(e.time)}</td><td class="mono"><b>${e.eid}</b></td><td>${esc(e.label)}</td>
        <td>${esc(e.provider.replace("Microsoft-Windows-", ""))}</td><td class="muted small">${esc(shortChan(e.channel))}</td><td>${stateChip(e.state)}</td>
        <td>${near ? `<span class="muted small">${near.id} · ${esc(TYPES[near.type].short)} (${fmtDur(Math.abs(near.d))} ${near.d < 0 ? "before" : "after"})</span>` : ""}</td></tr>`;
    }).join("")}</tbody>` : '<tr><td class="empty">No storage warnings or errors in these logs.</td></tr>';
    $$("#stT tr.click").forEach((r) => (r.onclick = () => openContext(r.dataset.idx, "Storage event")));
  };
  $("#stF").onchange = draw; draw();
}
function nearestItem(t) {
  let best = null;
  S.c.items.forEach((it) => {
    const a = it.type === "sleep" ? it.start_ts || it.end_ts : it.last_alive_ts || it.boot_ts;
    if (a == null) return; const d = t - a;
    if (Math.abs(d) <= 3600 && (!best || Math.abs(d) < Math.abs(best.d))) best = { id: it.id, type: it.type, d };
  });
  return best;
}

/* ------------------------------------------------------------------ data quality */
function tabQuality() {
  const c = S.c, g = c.integrity;
  const checks = [];
  checks.push(g.missing_channels.length ? ["warn", `Missing log(s): <b>${esc(g.missing_channels.join(", "))}</b>`, "Ask the customer for these; related checks are limited without them."]
    : ["ok", "System, Application and Storport logs are all present", ""]);
  if (g.unreadable_files.length) checks.push(["warn", `${g.unreadable_files.length} file(s) could not be read`, g.unreadable_files.map((f) => `${esc(f.file)}: ${esc(f.error)}`).join("<br>")]);
  checks.push(g.record_gaps.length ? ["warn", `${g.record_gaps.reduce((a, x) => a + x.missing, 0)} event records missing in ${g.record_gaps.length} gap(s)`, "Events inside these gaps are lost; verdicts near them are marked undetermined or lower confidence."]
    : ["ok", "No missing records (record IDs are continuous)", ""]);
  checks.push(g.clears.length ? ["warn", `Log cleared ${g.clears.length} time(s)`, g.clears.map((x) => fmt(x.time)).join(", ")] : ["ok", "Logs were not cleared", ""]);
  checks.push(g.time_changes.length ? ["warn", `System clock changed ${g.time_changes.length} time(s)`, g.time_changes.map((x) => `${fmt(x.time)}: ${esc(x.delta)} ${x.process ? "by " + esc(x.process.split("\\").pop()) : ""}`).join("<br>")]
    : ["ok", "No significant clock changes", ""]);
  if (g.clock_backwards.length) checks.push(["warn", `Time goes backwards ${g.clock_backwards.length} time(s) in record order`, "Check timestamps around these records."]);
  checks.push(g.unexplained_gaps.length ? ["info", `${g.unexplained_gaps.length} long quiet period(s) inside a boot session`, g.unexplained_gaps.slice(0, 8).map((x) => `${fmt(x.start)} → ${fmt(x.end)} (${esc(x.duration)})`).join("<br>") + "<br>Possibly an unlogged sleep — or simply an idle machine."]
    : ["ok", "No unexplained quiet periods", ""]);
  $("#tabBody").innerHTML = `
    <div class="grid g2">
      <div class="card"><div class="card-h"><h3>Checks</h3></div><div class="card-b" style="padding-top:4px;padding-bottom:4px">
        ${checks.map(([s, t, d]) => `<div class="qitem ${s}">${ICON[s]}<div><div>${t}</div>${d ? `<div class="muted small" style="margin-top:2px">${d}</div>` : ""}</div></div>`).join("")}</div></div>
      <div class="card"><div class="card-h"><h3>Log coverage</h3></div><div class="tbl-wrap"><table class="t">
        <thead><tr><th>Log</th><th>Events</th><th>From</th><th>To</th></tr></thead><tbody>
        ${c.channels.map((ch) => `<tr><td title="${esc(ch.channel)}">${esc(shortChan(ch.channel))}</td><td>${ch.events.toLocaleString()}</td><td style="white-space:nowrap">${fmt(ch.start, false)}</td><td style="white-space:nowrap">${fmt(ch.end, false)}</td></tr>`).join("")}
        </tbody></table></div>
        <div class="card-h" style="border-top:1px solid var(--line-2)"><h3>Files</h3></div><div class="tbl-wrap"><table class="t"><thead><tr><th>File</th><th>Events</th><th>Read with</th></tr></thead><tbody>
        ${c.sources.map((s) => `<tr><td class="mono" title="${esc(s.path)}">${esc(s.file)}</td><td>${s.error ? `<span style="color:var(--bad)">error</span>` : s.events.toLocaleString()}</td><td class="muted">${esc(s.reader || "—")}</td></tr>`).join("")}
        </tbody></table></div></div>
    </div>
    ${g.record_gaps.length ? `<div class="card" style="margin-top:16px"><div class="card-h"><h3>Record gaps</h3></div><div class="tbl-wrap"><table class="t">
      <thead><tr><th>Log</th><th>Missing</th><th>After record</th><th>Before record</th><th>Between</th></tr></thead><tbody>
      ${g.record_gaps.map((x) => `<tr><td>${esc(shortChan(x.channel))}</td><td><b>${x.missing}</b></td><td class="mono">${x.after_rid}</td><td class="mono">${x.before_rid}</td><td>${fmt(x.start)} → ${fmt(x.end)}</td></tr>`).join("")}
      </tbody></table></div></div>` : ""}`;
}

/* ------------------------------------------------------------------ SMART cross-check */
function tabSmart() {
  const sv = store.get("smart." + S.c.id, {});
  $("#tabBody").innerHTML = `
    <div class="card"><div class="card-h"><h3>Cross-check with the drive's own counters</h3></div><div class="card-b">
      <div class="note">The NVMe SMART / Health log counts <b>Power Cycles</b> and <b>Unsafe Shutdowns</b> independently of Windows.
        Take two SMART snapshots that bracket the log coverage (${fmt(S.c.coverage.start, false)} → ${fmt(S.c.coverage.end, false)}) and enter the <b>difference</b>.
        If the drive counted more than the logs explain, events are missing from the OS logs.</div>
      <div class="row" style="margin-top:14px">
        <label class="muted small" style="display:flex;flex-direction:column;gap:4px">Power Cycles (delta)<input type="number" id="sm_pc" min="0" value="${sv.pc ?? ""}" style="width:180px"></label>
        <label class="muted small" style="display:flex;flex-direction:column;gap:4px">Unsafe Shutdowns (delta)<input type="number" id="sm_us" min="0" value="${sv.us ?? ""}" style="width:180px"></label>
      </div>
      <div id="smRes"></div></div></div>`;
  const run = () => {
    const pc = $("#sm_pc").value, us = $("#sm_us").value; store.set("smart." + S.c.id, { pc, us });
    $("#smRes").innerHTML = smartCompare(pc === "" ? null : +pc, us === "" ? null : +us);
  };
  $("#sm_pc").oninput = run; $("#sm_us").oninput = run; run();
}
function smartCompare(pc, us) {
  const n = S.c.counts, thr = S.c.settings.review_threshold;
  const hardSure = S.c.items.filter((x) => x.type === "hard" && x.confidence >= thr).length;
  const pcMin = n.shutdown + n.hard + n.hibernate, pcMax = pcMin + n.restart + n.sleep + n.unknown;
  const usMin = hardSure, usMax = n.hard + n.unknown;
  const verdict = (v, lo, hi, what) => {
    if (v == null) return `<div class="muted small">Enter the SMART delta to compare.</div>`;
    if (v > hi) return `<div class="flagbox warn">${ICON.warn}<span>Drive counted <b>${v - hi}</b> more ${what} than the logs can explain — events are missing from the OS logs, or happened outside log coverage.</span></div>`;
    if (v < lo) return `<div class="flagbox warn">${ICON.warn}<span>Logs show <b>${lo - v}</b> more ${what} than the drive counted — check the SMART snapshot window, or whether some transitions kept the drive powered.</span></div>`;
    return `<div class="flagbox info">${ICON.ok}<span>Consistent with the logs.</span></div>`;
  };
  return `<div class="smart-res">
    <div class="smart-box"><div class="muted small">Power cycles expected from logs</div><div class="big">${pcMin}${pcMax !== pcMin ? `–${pcMax}` : ""}</div>
      <div class="muted small" style="margin:4px 0 10px">shutdowns + hard + hibernate${pcMax !== pcMin ? "; upper bound adds restarts, S3 sleeps and undetermined (platform-dependent whether they cut drive power)" : ""}</div>${verdict(pc, pcMin, pcMax, "power cycles")}</div>
    <div class="smart-box"><div class="muted small">Unsafe shutdowns expected from logs</div><div class="big">${usMin}${usMax !== usMin ? `–${usMax}` : ""}</div>
      <div class="muted small" style="margin:4px 0 10px">confident hard shutdowns${usMax !== usMin ? "; upper bound adds low-confidence hard and undetermined" : ""}</div>${verdict(us, usMin, usMax, "unsafe shutdowns")}</div></div>`;
}

/* ------------------------------------------------------------------ boot */
function applyTheme(t) { document.documentElement.dataset.theme = t; store.set("theme", t); }
async function init() {
  const theme = store.get("theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme);
  $("#themeBtn").onclick = () => { applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"); if (S.tab === "timeline" && S.c) drawTimeline(); };
  $("#tzSelect").value = store.get("tz", "0");
  $("#tzSelect").onchange = () => { store.set("tz", $("#tzSelect").value); S.c ? renderCase() : renderHome(); };
  $("#brandHome").onclick = renderHome; $("#newBtn").onclick = renderHome;
  $("#drawerBack").onclick = closeDrawer;
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());
  try { S.settings = (await api("/api/config")).settings; } catch { /* defaults */ }
  renderHome();
}
init();
