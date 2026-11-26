/* LENS front-end - vanilla JS, no external libraries (works offline). */
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

/* v: search / filter inputs by element id, kept while the case is open */
const S = { cases: [], c: null, tab: "overview", filter: "all", v: {}, tl: null, selected: null, settings: null };

/* ------------------------------------------------------------------ utils */
const store = {
  /* "wela.": the keys from before the rename to LENS, so a viewer keeps their theme, time zone and choices */
  get(k, d) { try { const v = localStorage.getItem("lens." + k) ?? localStorage.getItem("wela." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("lens." + k, JSON.stringify(v)); } catch { /* ignore */ } },
};
const debounce = (fn, ms = 150) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
/* search: event IDs ("41" or "41, 6008") match exactly, anything else is a text search. null = no search */
function matcher(q) {
  q = (q || "").trim().toLowerCase();
  if (!q) return null;
  if (/^\d+(?:[\s,;]+\d+)*$/.test(q)) { const ids = new Set(q.split(/[\s,;]+/).map(Number)); return (eids) => eids.some((x) => ids.has(+x)); }
  return (eids, text) => text.toLowerCase().includes(q);
}
const searchBox = (id, cls = "") => `<input type="search" id="${id}" class="${cls}" placeholder="Event ID or text" autocomplete="off">`;
/* inputs that keep their value in S.v across re-renders and redraw on change */
function bind(ids, draw) {
  ids.forEach((id) => {
    const el = $("#" + id); if (!el) return;
    if (S.v[id] != null) el.value = S.v[id];
    const sel = el.tagName === "SELECT";
    el[sel ? "onchange" : "oninput"] = debounce(() => { S.v[id] = el.value; draw(); }, sel ? 0 : 150);
  });
}
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
/* which drive: the highlighted vendor (Samsung) gets its own colour everywhere */
const HV = () => S.c?.highlight_vendor || "Samsung";
const isHl = (x) => x === "yes" || x === "probably";
const hlCycle = (it) => isHl(it.drive?.highlight);
const HL_CLS = { yes: "sam", probably: "samp", no: "other", unknown: "nodata" };
const hlChip = (d) => (d?.highlight && HL_CLS[d.highlight] ? `<span class="chip ${HL_CLS[d.highlight]}">${esc(d.highlight_label)}</span>` : "");
function devBadge(e) {
  const tip = esc(`${e.dev || "Drive not identified"} · ${e.dev_basis || ""}`);
  if (e.hl === "yes") return `<span class="chip sam" title="${tip}">${esc(HV())}</span>`;
  if (e.hl === "probably") return `<span class="chip samp" title="${tip}">${esc(HV())}?</span>`;
  if (e.hl === "no") return `<span class="chip other" title="${tip}">${esc(e.vendor || "other drive")}</span>`;
  return "";
}
const devLine = (e) => (e.dev_basis && e.state !== "info" ? `<div class="wd">${esc(e.dev ? `Drive: ${e.dev} · ${e.dev_basis}` : `Drive ${e.dev_basis}`)}</div>` : "");
/* what triggered it (software) */
const SW_CLS = { confirmed: "sw", likely: "sw", possible: "swp" };
const swConf = (s) => (s?.confidence != null ? ` · ${Math.round(s.confidence * 100)}%` : "");
const swChip = (s) => (s?.trigger ? `<span class="chip ${SW_CLS[s.strength] || "nodata"}" title="${esc(s.strength_label + swConf(s))}">${esc(s.label)}</span>` : "");
const isSoftware = (it) => ["confirmed", "likely", "possible"].includes(it.software?.strength) && it.software?.trigger !== "user";
const swLabel = (k) => S.c?.trigger_labels?.[k] || k;
/* whose account the shutdown request ran under: "DEMO\engineer · user account", "NT AUTHORITY\SYSTEM · Windows itself" */
const accountText = (init) => (init?.user ? init.user + (init.account_label ? ` · ${init.account_label}` : "") : "");
function fmtOff(s) {
  if (s == null) return "";
  const a = Math.abs(s);
  return (s < 0 ? "−" : "+") + (a >= 60 ? fmtDur(a) : `${a < 10 && a % 1 ? a.toFixed(1) : Math.round(a)}s`);
}
/* the power cycles around a moment: time since the boot / wake of the one before, to the power-off / sleep of the next */
const bisect = (arr, before) => { let lo = 0, hi = arr.length; while (lo < hi) { const m = (lo + hi) >> 1; if (before(arr[m])) lo = m + 1; else hi = m; } return lo; };
const cycLink = (x, label = `${x.id} ${TYPES[x.type].short}`) => `<a class="cyc" data-id="${esc(x.id)}" title="${esc(x.subtype)}">${esc(label)}</a>`;
function cycleMarks() {
  if (S.cm?.c !== S.c) {
    const m = S.c.items.map((x) => {
      const [off, on] = x.type === "sleep" ? [x.start_ts, x.end_ts] : [x.last_alive_ts, x.boot_ts];
      return { x, off: off ?? on, on };
    });
    S.cm = { c: S.c, ons: m.filter((o) => o.on != null).sort((a, b) => a.on - b.on), offs: m.filter((o) => o.off != null).sort((a, b) => a.off - b.off) };
  }
  return S.cm;
}
function nearCell(t) {
  const { ons, offs } = cycleMarks(), i = bisect(offs, (o) => o.off < t), cur = offs[i - 1];
  if (cur?.on > t) return `<div>during ${cycLink(cur.x)}</div>`;
  const prev = ons[bisect(ons, (o) => o.on <= t) - 1], next = offs[i];
  return (prev ? `<div>${fmtDur(t - prev.on)} after ${cycLink(prev.x)}</div>` : "") + (next ? `<div>${fmtDur(next.off - t)} before ${cycLink(next.x)}</div>` : "");
}
/* table rows open their event; a power cycle link in them opens the power cycle */
function onRows(el, open) {
  el.onclick = (ev) => {
    const a = ev.target.closest("a.cyc"); if (a) return openDetail(a.dataset.id);
    const r = ev.target.closest("tr.click"); if (r) open(r);
  };
}
/* long tables: the first rows at once, the next ones as the end of the table scrolls into view */
const PAGE = 150;
function pageRows(table, head, rows, rowHtml, empty) {
  table._io?.disconnect();
  if (!rows.length) { table.innerHTML = `<tr><td class="empty">${empty}</td></tr>`; return; }
  table.innerHTML = `${head}<tbody></tbody><tfoot><tr><td class="tmore" colspan="20"></td></tr></tfoot>`;
  const body = table.tBodies[0], foot = table.tFoot, note = foot.querySelector("td");
  let n = 0;
  const more = () => {
    const end = Math.min(rows.length, n + PAGE);
    body.insertAdjacentHTML("beforeend", rows.slice(n, end).map(rowHtml).join(""));
    n = end;
    if (n < rows.length) note.textContent = `Showing ${n.toLocaleString()} of ${rows.length.toLocaleString()} · scroll for more`;
    else { table._io?.disconnect(); foot.remove(); }
  };
  note.onclick = more;
  more();
  if (n >= rows.length) return;
  const io = new IntersectionObserver((es) => {   // observing again re-checks: still in view loads the next page
    if (!es[0].isIntersecting) return;
    more();
    if (n < rows.length) { io.unobserve(foot); io.observe(foot); }
  }, { root: table.closest(".tbl-wrap"), rootMargin: "400px" });
  io.observe(foot);
  table._io = io;
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
  $("#main").innerHTML = `
  <div class="home">
    <div class="card hero">
      <h1>Analyze Windows event logs</h1>
      <p>Point LENS at a claim's log folder or <b>.evtx</b> files. From a folder it reads only <b>System</b>, <b>Application</b>
         and <b>Storport</b> (Operational, Health). It rebuilds every power cycle, checks what the drive was doing around each one,
         and flags anything uncertain.</p>
      <div class="dropzone">
        <textarea id="paths" spellcheck="false" autocomplete="off" placeholder="One file or folder per line, e.g.&#10;D:\\Claims\\DELL-12345\\Logs&#10;D:\\Claims\\DELL-12345\\System.evtx"></textarea>
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn" id="pickFolder">${ICON.folder} Browse folder</button>
        <button class="btn" id="pickFiles">${ICON.file} Browse files</button>
        <input type="text" id="caseName" placeholder="Case name (optional)" autocomplete="off" style="width:220px">
        <div class="spacer"></div>
        <button class="btn ghost" id="demoBtn">${ICON.flask} Try demo data</button>
        <button class="btn primary" id="analyzeBtn">${ICON.play} Analyze</button>
      </div>
      <div class="err" id="err"></div>
      <details class="adv"><summary>Analysis settings</summary>
        <div class="settings">
          <label>Drive window before power-off &amp; after boot (seconds)<input type="number" id="s_drive" value="${st.drive_window_s ?? 60}" min="5"></label>
          <label>Software trigger window before power-off (seconds)<input type="number" id="s_sw" value="${st.software_window_s ?? 900}" min="60"></label>
          <label>Restart if stop → boot gap below (seconds)<input type="number" id="s_restart" value="${st.restart_gap_s ?? 300}" min="10"></label>
          <label>Flag for review below confidence<input type="number" id="s_review" value="${st.review_threshold ?? 0.6}" step="0.05" min="0" max="1"></label>
          <label>Flag quiet gaps longer than (seconds)<input type="number" id="s_gap" value="${st.unexplained_gap_s ?? 7200}" min="600"></label>
        </div>
        <div class="note" style="margin-top:12px">Event rules and weights live in <span class="mono">lens/catalog.py</span>; override any of them with a <span class="mono">lens_config.json</span> next to <span class="mono">run_lens.py</span>.</div>
      </details>
    </div>
    <div class="steps">
      ${[["Merge", "All logs become one timeline in UTC, with coverage and gap checks per log."],
         ["Classify", "Each boot closes a session: clean stop, hard shutdown or undetermined — from redundant evidence."],
         ["Correlate", "Storport, disk, NVMe and PCIe events around every power cycle, tied to the drive they belong to — and the app crashes, updates and installs that led up to it."],
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
  const o = { drive_window_s: n("#s_drive"), software_window_s: n("#s_sw"), restart_gap_s: n("#s_restart"), review_threshold: n("#s_review"), unexplained_gap_s: n("#s_gap") };
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
    const body = { paths, name: $("#caseName").value.trim() || undefined, settings: readSettings() };
    const r = await api(demo ? "/api/demo" : "/api/analyze", { method: "POST", body: JSON.stringify(body) });
    S.c = r; S.tab = "overview"; S.filter = "all"; S.v = {}; S.tl = null;
    await loadCases(); renderCase();
    toast(`Analyzed ${r.event_count.toLocaleString()} events in ${r.analysis_seconds}s${r.skipped_files ? ` · ${r.skipped_files} other logs skipped` : ""}`);
  } catch (e) { showErr(e.message); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

/* ------------------------------------------------------------------ case view */
async function openCase(id) {
  $("#main").innerHTML = '<div class="loading"><div class="spin"></div>Loading case…</div>';
  try { S.c = await api(`/api/cases/${encodeURIComponent(id)}`); S.tab = "overview"; S.filter = "all"; S.v = {}; S.tl = null; renderCase(); loadCases(); }
  catch (e) { toast(e.message); renderHome(); }
}
function renderCase() {
  const c = S.c; if (!c) return renderHome();
  const n = c.counts, integ = c.integrity;
  const dq = integ.missing_channels.length + integ.record_gaps.length + integ.clears.length + integ.time_changes.length +
    integ.unreadable_files.length + integ.clock_backwards.length;
  const tabs = [["overview", "Overview"], ["timeline", "Timeline"], ["cycles", "Power cycles", c.items.length],
    ["drive", "Drive", c.storage_events.filter((e) => e.state !== "info").length], ["software", "Apps & updates", n.software_events],
    ["quality", "Data quality", dq, dq > 0], ["refs", "References"]];
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
              .map(([f, l, s]) => `<a data-f="${f}" download>${l}<small>${s}</small></a>`).join("")}
            <label class="exp-names" title="The accounts of the people who shut the PC down. Hidden by default: a report leaves this PC, and a claim needs to know that a user did it, not who. Windows' own accounts are always shown."><input type="checkbox" id="expNames"> Include account names</label>
          </div></div>
        <button class="btn danger" id="delBtn" title="Delete case">${ICON.trash}</button>
      </div>
    </div>
    <div class="tabs">${tabs.map(([k, l, b, w]) => `<button class="tab ${S.tab === k ? "active" : ""}" data-tab="${k}">${l}${b != null ? ` <span class="badge ${w ? "warn" : ""}">${b}</span>` : ""}</button>`).join("")}</div>
    <div id="tabBody"></div>`;
  $$(".tab").forEach((t) => (t.onclick = () => { S.tab = t.dataset.tab; renderCase(); }));
  const menu = $("#expMenu"), names = $("#expNames");
  menu.querySelector(".btn").onclick = (e) => {
    e.stopPropagation();
    if (menu.classList.toggle("open")) document.addEventListener("click", () => menu.classList.remove("open"), { once: true });
  };
  /* exports leave people's account names out unless asked for; the choice is kept in this browser */
  const exportLinks = () => $$("a[data-f]", menu).forEach((a) => (a.href = `/api/cases/${encodeURIComponent(c.id)}/export.${a.dataset.f}?tz=${tzOffset()}${names.checked ? "&names=1" : ""}`));
  names.checked = store.get("expNames", false); exportLinks();
  names.onchange = () => { store.set("expNames", names.checked); exportLinks(); };
  menu.querySelector(".exp-names").onclick = (e) => e.stopPropagation();   // ticking it keeps the menu open
  const del = $("#delBtn");
  del.onclick = async () => {
    if (!del.dataset.armed) { del.dataset.armed = "1"; del.innerHTML = `${ICON.trash} Confirm delete`; setTimeout(() => { if (del.isConnected) { delete del.dataset.armed; del.innerHTML = ICON.trash; } }, 3000); return; }
    await api(`/api/cases/${encodeURIComponent(c.id)}`, { method: "DELETE" }); toast("Case deleted"); renderHome();
  };
  closeRefPop();
  ({ overview: tabOverview, timeline: tabTimeline, cycles: tabCycles, drive: tabDrive, software: tabSoftware, quality: tabQuality, refs: tabRefs })[S.tab]();
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
  const maxSt = Math.max(1, ...st.map((x) => x[1])), nSt = c.storage_events.filter((e) => e.state !== "info").length;
  const suspects = c.items.filter(isSuspect).slice(0, 6);
  const dstats = [["likely", "Likely", "drive"], ["possible", "Possibly", "drive"], ["no_evidence", "No drive evidence"], ["unknown", "Can't tell"]];
  const sb = Object.entries(c.software_breakdown || {}).sort((a, b) => b[1] - a[1]);
  const maxSb = Math.max(1, ...sb.map((x) => x[1]));
  const swc = Object.entries(c.software_counts || {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const maxSw = Math.max(1, ...swc.map((x) => x[1]));
  const disk = c.disks.find((d) => d.highlight) || c.disks[0];
  const rerun = '<div class="muted">Re-run the analysis to get this for the case.</div>';
  $("#tabBody").innerHTML = `
    <div class="tiles">${tiles.map(([k, v, l, s]) => `
      <div class="card tile" data-f="${k}" style="--c:${colors[k] || TYPES[k].color}">
        <div class="v">${v}</div><div class="l">${l}</div><div class="s">${esc(s || "")}</div></div>`).join("")}</div>
    <div class="grid g2">
      <div class="card span2"><div class="card-h"><h3>Did the drive cause it?</h3><span class="muted small">hard shutdowns &amp; undetermined · drive checked ${esc(c.settings.drive_window_s)}s before power-off and after boot</span></div>
        <div class="card-b">${n.drive_likely === undefined ? '<div class="muted">Re-run the analysis to get the drive assessment for this case.</div>' : `
          <div class="dstats">${dstats.map(([k, l, f]) => `<div class="dstat ${k}" ${f ? `data-f="${f}"` : ""}><b>${n["drive_" + k]}</b><span>${l}</span></div>`).join("")}
            <div class="dstat effect" data-f="effect"><b>${n.drive_effect}</b><span>drive errors right after boot / wake</span></div>
            ${n.hl_cycles !== undefined ? `<div class="dstat hl" data-f="samsung" title="${n.hl_suspect} of them with the drive suspected"><b>${n.hl_cycles}</b><span>with ${esc(HV())} drive problems</span></div>` : ""}</div>
          <div class="muted small" style="margin:2px 0 6px">“No drive evidence” is not proof the drive is fine — a drive that froze suddenly may not have been able to save its last events. Cross-check its SMART and error logs.</div>
          ${suspects.length ? suspects.map((it) => `
            <div class="list-row" data-id="${it.id}">${chip(it.type)}<div style="flex:1;min-width:0"><div class="lt">${esc(it.id)} · ${esc(it.subtype)}</div>
              <div class="muted small">${fmt(it.time)} · ${esc(it.drive.reasons[0] || "")}</div></div><span class="chips">${hlChip(it.drive)}${causeChip(it.drive)}</span></div>`).join("")
            : '<div class="muted" style="padding-top:8px">No power cycle points at the drive.</div>'}`}
        </div></div>
      <div class="card"><div class="card-h"><h3>Hard shutdown causes</h3><span class="muted small">${n.hard} total</span></div>
        <div class="card-b">${hb.length ? hb.map(([k, v]) => `<div class="hbar"><span>${esc(k)}</span><div class="track"><b style="width:${(v / maxHb) * 100}%;background:var(--bad)"></b></div><span class="n">${v}</span></div>`).join("")
          : '<div class="muted">No hard shutdowns found.</div>'}</div></div>
      <div class="card"><div class="card-h"><h3>What triggered it?</h3><span class="muted small">${n.software === undefined ? "" : `${n.software} triggered by software, not the user`}</span></div>
        <div class="card-b">${c.software_breakdown === undefined ? rerun : sb.length ? sb.map(([k, v]) => `<div class="hbar trig" data-sw="${esc(k)}" title="Show these power cycles"><span>${esc(swLabel(k))}</span><div class="track"><b style="width:${(v / maxSb) * 100}%;background:${["none", "unknown", "not_logged"].includes(k) ? "var(--grey)" : k === "user" ? "var(--ok)" : "var(--accent)"}"></b></div><span class="n">${v}</span></div>`).join("")
          : '<div class="muted">No power cycles found.</div>'}</div></div>
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
      <div class="card"><div class="card-h"><h3>Storage events</h3><span class="muted small">${nSt} warning/error events${nSt < c.storage_events.length ? ` · ${(c.storage_events.length - nSt).toLocaleString()} normal activity` : ""}</span></div>
        <div class="card-b">${st.length ? st.map(([k, v]) => `<div class="hbar"><span>${esc(k)}</span><div class="track"><b style="width:${(v / maxSt) * 100}%;background:var(--warn)"></b></div><span class="n">${v}</span></div>`).join("")
          : '<div class="muted">No storage warnings or errors logged.</div>'}
          ${n.hl_events !== undefined && nSt ? `<div class="muted small" style="margin-top:10px"><span class="chip sam">${esc(HV())}</span> ${n.hl_events} of ${nSt} warning / error events are on the ${esc(HV())} drive</div>` : ""}
          ${disk ? `<div class="muted small" style="margin-top:12px">Drive: <b style="color:var(--ink)">${esc(disk.Model || "")}</b>${disk.highlight ? ` <span class="chip sam">${esc(HV())}</span>` : ""} · FW ${esc(disk.Revision || disk.FirmwareRevision || "?")} · SN ${esc(disk.SerialNumber || "?")}${c.disks.length > 1 ? ` · +${c.disks.length - 1} more` : ""}</div>` : ""}
        </div></div>
      <div class="card"><div class="card-h"><h3>Apps &amp; updates</h3><span class="muted small">${n.software_events === undefined ? "" : `${n.software_events} crash / hang / failure / restart events`}</span></div>
        <div class="card-b">${c.software_counts === undefined ? rerun : swc.length ? swc.map(([k, v]) => `<div class="hbar"><span>${esc(k)}</span><div class="track"><b style="width:${(v / maxSw) * 100}%;background:var(--purple)"></b></div><span class="n">${v}</span></div>`).join("")
          : `<div class="muted">No app crashes or hangs, failed updates or service failures logged${(c.channels || []).some((ch) => ch.kind === "application") ? "" : " (no Application log in this case)"}.</div>`}</div></div>
    </div>`;
  $$(".tile, .dstat[data-f]").forEach((t) => (t.onclick = () => { S.filter = t.dataset.f; S.tab = "cycles"; renderCase(); }));
  $$(".hbar.trig").forEach((t) => (t.onclick = () => { S.filter = "sw:" + t.dataset.sw; S.tab = "cycles"; renderCase(); }));
  $$(".list-row").forEach((r) => (r.onclick = () => openDetail(r.dataset.id)));
}
function subOf(type) {
  const m = {};
  S.c.items.filter((x) => x.type === type).forEach((x) => (m[x.subtype] = (m[x.subtype] || 0) + 1));
  return Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ");
}
function shortChan(ch) {
  return ch.replace("Microsoft-Windows-", "").replace("Storage-Storport/Operational", "Storport").replace("Storage-Storport/Health", "Storport health")
    .replace("/Diagnostic", " (diag)");
}

/* ------------------------------------------------------------------ power cycles */
const winEvents = (x) => [...(x?.before?.events || []), ...(x?.after?.events || [])];
/* what a search looks through, worked out once per power cycle */
function cycleQ(it) {
  if (!it._q) {
    const s = it.software || {};
    it._q = { eids: [...it.evidence_found, ...winEvents(it.drive), ...winEvents(s)].map((e) => e.eid),
      text: `${it.id} ${it.type} ${it.subtype} ${it.drive?.state} ${it.drive?.cause_label ?? ""} ${it.drive?.effect_label ?? ""} ${it.drive?.highlight_label ?? ""} ${s.label ?? ""} ${s.initiator?.process ?? ""} ${(s.reasons || []).join(" ")} ${it.flags.map((f) => f.text).join(" ")}` };
  }
  return it._q;
}
function filtered() {
  const m = matcher(S.v.cyQ);
  const sw = S.filter.startsWith("sw:") ? S.filter.slice(3) : null;
  return S.c.items.filter((it) => {
    if (S.filter === "review" && !it.needs_review) return false;
    if (S.filter === "drive" && !isSuspect(it)) return false;
    if (S.filter === "effect" && !hitAfter(it)) return false;
    if (S.filter === "samsung" && !hlCycle(it)) return false;
    if (S.filter === "software" && !isSoftware(it)) return false;
    if (sw !== null && (it.type === "sleep" || it.software?.trigger !== sw)) return false;
    if (sw === null && !["all", "review", "drive", "effect", "samsung", "software"].includes(S.filter) && it.type !== S.filter) return false;
    if (!m) return true;
    const q = cycleQ(it);
    return m(q.eids, q.text);
  });
}
function tabCycles() {
  const n = S.c.counts;
  const main = [["all", "All", S.c.items.length], ["shutdown", "Shutdown", n.shutdown], ["restart", "Restart", n.restart],
    ["hard", "Hard", n.hard], ["sleep", "Sleep", n.sleep + n.hibernate + n.modern_standby]];
  if (n.hl_cycles !== undefined) main.push(["samsung", `${HV()} drive`, n.hl_cycles]);
  /* the rest sit under More, so the row stays short; the button names the one in use */
  const more = [["unknown", "Undetermined", n.unknown], ["review", "Needs review", n.needs_review],
    ["drive", "Drive suspected", (n.drive_likely ?? 0) + (n.drive_possible ?? 0)], ["effect", "Drive errors after", n.drive_effect ?? 0]];
  if (n.software !== undefined) more.push(["software", "Triggered by software", n.software]);
  if (S.filter.startsWith("sw:")) more.push([S.filter, `Trigger: ${swLabel(S.filter.slice(3))}`, (S.c.software_breakdown || {})[S.filter.slice(3)] || 0]);
  const on = more.find(([k]) => k === S.filter);
  $("#tabBody").innerHTML = `
    <div class="row" style="margin-bottom:12px">
      ${main.map(([k, l, c]) => `<button class="fchip ${S.filter === k ? "on" : ""}" data-f="${k}">${l}<span class="badge">${c}</span></button>`).join("")}
      <div class="menu" id="cyMore"><button class="fchip ${on ? "on" : ""}">${on ? `${esc(on[1])}<span class="badge">${on[2]}</span>` : "More"} ▾</button>
        <div class="menu-pop">${more.map(([k, l, c]) => `<a data-f="${k}" class="${S.filter === k ? "on" : ""}">${esc(l)}<small>${c}</small></a>`).join("")}</div></div>
      <div class="spacer"></div><span class="muted small" id="cyN"></span>${searchBox("cyQ")}
    </div>
    <div class="card"><div class="tbl-wrap" style="max-height:calc(100vh - 290px)"><table class="t" id="cyc"></table></div></div>`;
  $$(".fchip[data-f], #cyMore a").forEach((b) => (b.onclick = () => { S.filter = b.dataset.f; tabCycles(); }));
  const menu = $("#cyMore");
  menu.querySelector(".fchip").onclick = (e) => {
    e.stopPropagation();
    if (menu.classList.toggle("open")) document.addEventListener("click", () => menu.classList.remove("open"), { once: true });
  };
  $("#cyc").onclick = (ev) => { const r = ev.target.closest("tr.click"); if (r) openDetail(r.dataset.id); };
  bind(["cyQ"], drawCycleRows);
  drawCycleRows();
}
function cycleRow(it) {
  const warn = it.flags.filter((x) => x.severity === "warn").length;
  const hl = isHl(it.drive?.highlight) ? hlChip({ ...it.drive, highlight_label: it.drive.highlight === "yes" ? HV() : `${HV()}?` }) : "";
  const init = it.software?.initiator, acc = init?.account_kind === "user" ? init.user : "";   // a person's account; Windows' own is in the chip
  return `<tr class="click ${S.selected === it.id ? "sel" : ""} ${hl ? "samrow" : ""}" data-id="${it.id}">
    <td class="mono">${it.id}</td><td style="white-space:nowrap">${fmt(it.time)}</td><td>${chip(it.type)}</td>
    <td>${esc(it.subtype)}${it.wake_source ? `<div class="muted small">wake: ${esc(it.wake_source)}</div>` : ""}</td>
    <td style="white-space:nowrap">${esc(it.type === "sleep" ? it.duration : it.gap)}</td>
    <td>${confBar(it.confidence)}</td><td><span class="chips">${stateChip(it.drive?.state)}${hl}</span></td>
    <td>${it.type === "sleep" ? '<span class="muted">—</span>' : causeChip(it.drive)}</td>
    <td>${it.type === "sleep" || !it.software ? '<span class="muted">—</span>' : `${swChip(it.software)}${SW_CLS[it.software.strength] ? `<div class="muted small">${esc(it.software.strength_label + swConf(it.software) + (acc ? ` · ${acc}` : ""))}</div>` : ""}`}</td>
    <td>${warn ? `<span class="flagdot">${ICON.warn}${warn}</span>` : it.flags.length ? `<span class="muted small">${it.flags.length} note${it.flags.length > 1 ? "s" : ""}</span>` : ""}</td></tr>`;
}
function drawCycleRows() {
  const rows = filtered();
  $("#cyN").textContent = matcher(S.v.cyQ) ? `${rows.length.toLocaleString()} found` : "";
  pageRows($("#cyc"), `<thead><tr><th>ID</th><th>Time (${tzLabel()})</th><th>Type</th><th>Detail</th><th>Off / asleep</th><th>Confidence</th><th>Drive</th><th>Drive caused it?</th><th>Software trigger</th><th>Flags</th></tr></thead>`,
    rows, cycleRow, "Nothing matches this filter.");
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
/* one event in a before / after list; a click shows its data */
const evRow = (e, body, chips, cls = "") => `<div class="wrow ${e.state === "info" ? "info" : cls}" data-idx="${e.idx}" title="Click for the full event data">
    <span class="off mono" title="${fmt(e.time)}">${fmtOff(e.offset_s) || fmt(e.time).slice(11)}</span><span class="mono">${eidTag(e.eid, e.provider)}</span>
    <div class="wx"><div>${esc(e.label)} <span class="muted">· ${esc(e.provider.replace("Microsoft-Windows-", ""))}</span></div>${body}</div>
    <span class="chips">${chips}</span></div><pre class="data" hidden></pre>`;
const driveRow = (e) => evRow(e, (e.fields ? `<div class="wf mono">${esc(e.fields)}</div>` : "") + devLine(e), devBadge(e) + stateChip(e.state), isHl(e.hl) ? "sam" : "");
const swRow = (e) => evRow(e, e.subject || e.detail ? `<div class="wf">${esc([e.subject, e.detail].filter(Boolean).join(" · "))}</div>` : "", stateChip(e.state));
const rowText = (e) => `${e.label} ${e.provider} ${e.subject || ""} ${e.detail || ""} ${e.fields || ""} ${e.dev || ""}`;
/* where an app / update list starts (on) or ends: the power cycle before / after it, or the end of the log */
function edge(id, on) {
  const x = id && S.c.items.find((i) => i.id === id);
  if (!x) return on ? "the start of the log" : "the end of the log";
  return `${cycLink(x, x.id)} ${x.type === "sleep" ? (on ? "wake" : "sleep") : on ? "boot" : "power-off"}`;
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
  const [offL, onL] = isSleep ? ["Before sleep", "After wake"] : ["Before power-off", "After boot"];
  /* before / after lists: scroll boxes that open at the end nearest the power cycle - "before" at the bottom, "after" at the top */
  const wins = [];
  const win = (w, o) => {
    const i = wins.push({ w, ...o }) - 1;
    return `<div class="win"><div class="win-h"><span title="${esc(`${fmt(w.from)} → ${fmt(w.to)}`)}"><b>${o.label}</b> · ${o.span}</span>
      <span class="chips"><span class="muted small" data-n="${i}"></span>${o.chip || ""}</span></div>
      <div class="wev" data-w="${i}"></div>${o.note ? `<div class="muted small wnote">${o.note}</div>` : ""}</div>`;
  };
  const d = it.drive || {}, dw = d.window_s ?? S.c.settings.drive_window_s;
  const driveWin = (w, before) => !w ? "" : win(w, { before, row: driveRow, label: before ? offL : onL, span: `${before ? "last" : "first"} ${dw} s`,
    chip: stateChip(w.state), empty: w.state === "no data" ? "No log covers this window." : "No drive events in this window.",
    note: [!w.storport_covered && "Storport log not available for this time", w.total > w.events.length && `Showing the first ${w.events.length} of ${w.total}`].filter(Boolean).join(" · ") });
  const swWin = (w, before) => !w ? "" : win(w, { before, sw: true, row: swRow, label: before ? offL : onL,
    span: !("since" in w || "until" in w) ? `${fmt(w.from)} → ${fmt(w.to)}`   /* analysed before the lists ran cycle to cycle */
      : `${before ? `since ${edge(w.since, true)}` : `until ${edge(w.until, false)}`} · ${fmtDur(before ? tsOf(w.anchor) - tsOf(w.from) : tsOf(w.to) - tsOf(w.anchor))}`,
    empty: "No app, update or service events in this window.", note: w.app_covered ? "" : "No Application log for this time" });
  const driveSec = `<div class="sec"><h4>Drive at this ${isSleep ? "sleep" : "power cycle"}</h4>
      ${d.cause ? `<div class="assess">
        ${isSleep ? "" : `<div class="a-row"><span>Did the drive cause it?</span>${causeChip(d)}</div>`}
        <div class="a-row"><span>Effect on the drive</span>${effectChip(d)}</div>
        ${d.highlight ? `<div class="a-row"><span>Which drive had the problems?</span>${hlChip(d) || '<span class="chip healthy">No drive problems</span>'}</div>` : ""}
        <ul class="reasons">${d.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>`
        : '<div class="note" style="margin-bottom:10px">Re-run the analysis to get the drive assessment for this case.</div>'}
      ${driveWin(d.before, true)}${driveWin(d.after, false)}</div>`;
  const sw = it.software, init = sw?.initiator;
  const initKv = init ? [["Requested by", init.process || "—"], ["Account", accountText(init)], ["Path", init.path], ["Reason", init.reason_text],
    ["Type", init.type], ["Comment", init.comment], ["Logged at", fmt(init.time)]].filter(([, v]) => v) : [];
  const swSec = `<div class="sec"><h4>Apps, updates &amp; services</h4>
      ${sw ? `<div class="assess">
        ${isSleep ? "" : `<div class="a-row"><span>What triggered it?</span><span class="chips">${swChip(sw)}<span class="muted small" style="font-weight:400">${esc(sw.strength_label + swConf(sw))}</span></span></div>`}
        ${initKv.length ? `<dl class="kv" style="margin:8px 0 4px">${initKv.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : ""}
        <ul class="reasons">${sw.reasons.filter((r) => !(initKv.length && /^(Reason given|Comment): /.test(r))).map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
        ${swWin(sw.before, true)}${swWin(sw.after, false)}`
        : '<div class="note">Re-run the analysis to see the app, update and service events for this case.</div>'}</div>`;
  const anchor = (it.evidence_found[it.evidence_found.length - 1] || it.evidence_found[0])?.idx;
  openDrawer(`
    <div class="dr-h"><div style="flex:1;min-width:0">
        <div class="row" style="gap:6px">${chip(it.type, TYPES[it.type].label)}${it.needs_review ? chip("review", "Needs review") : ""}<span class="muted small mono">${it.id}</span></div>
        <h2>${esc(it.subtype)}</h2><div class="muted small">${fmt(it.time)} ${tzLabel()}</div></div>
      ${wins.length ? searchBox("drQ", "dr-q") : ""}
      <button class="icon-btn dr-close" aria-label="Close">${ICON.x}</button></div>
    <div class="dr-b">
      <div class="sec"><dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl></div>
      ${driveSec}
      ${swSec}
      <div class="sec"><h4>Confidence</h4>
        <div class="bigconf"><strong style="color:${confColor(it.confidence)}">${Math.round(it.confidence * 100)}%</strong>
          <div class="bar"><b style="width:${it.confidence * 100}%;background:${confColor(it.confidence)}"></b></div></div>
        <div class="muted small" style="margin-top:6px">${nFound} signal(s) found${it.evidence_missing.length ? `, ${it.evidence_missing.length} expected signal(s) not logged` : ", nothing expected is missing"}.</div></div>
      ${it.flags.length ? `<div class="sec"><h4>Flags</h4>${it.flags.map((f) => `<div class="flagbox ${f.severity}">${f.severity === "warn" ? ICON.warn : ICON.info}<span>${esc(f.text)}</span></div>`).join("")}</div>` : ""}
      <div class="sec"><h4>Evidence found</h4>${it.evidence_found.length ? it.evidence_found.map((e) => `
        <div class="evi"><span class="id eid" data-p="${esc(e.provider)}" title="What does ${e.eid} mean?">${e.eid}</span><div class="x"><b>${esc(e.label)}</b><div>${fmt(e.time)} · ${esc(e.provider)}${e.note ? `<br>${esc(e.note)}` : ""}</div></div>
        <button class="btn ghost small ctx" data-idx="${e.idx}" style="padding:3px 8px">context</button></div>`).join("") : '<div class="muted small">No direct evidence — verdict is inferred.</div>'}
        ${it.evidence_missing.map((m) => `<div class="evi miss"><span class="id">—</span><div class="x"><b>${esc(m)}</b><div>expected, not logged</div></div></div>`).join("")}</div>
      <div class="sec"><h4>Raw events</h4><div id="rawBox"><button class="btn" id="rawBtn" data-idx="${anchor ?? ""}">${ICON.list} Show events around this point</button></div></div>
    </div>`);
  const drawer = $("#drawer"), cid = S.c.id, boxes = wins.map((_, i) => $(`.wev[data-w="${i}"]`, drawer));
  let q = "";
  const fill = (i, keep = false) => {   // keep: stay on the same rows after more were loaded
    const o = wins[i], box = boxes[i]; if (!box.isConnected) return;
    const m = matcher(q), all = o.w.events, rows = m ? all.filter((e) => m([e.eid], rowText(e))) : all;
    const rest = o.sw && !m ? o.w.total - all.length : 0;
    const end = rest <= 0 ? "" : o.w.loaded ? `<div class="muted small wend">Showing the ${all.length.toLocaleString()} nearest of ${o.w.total.toLocaleString()}</div>`
      : `<button class="wmore" data-more="${i}">Show ${rest.toLocaleString()} ${o.before ? "earlier" : "later"} event${rest > 1 ? "s" : ""}</button>`;
    const list = rows.length ? rows.map(o.row).join("") : end ? "" : `<div class="muted small wend">${m ? "No match." : o.empty}</div>`;
    const fromEnd = box.scrollHeight - box.scrollTop, top = box.scrollTop;
    box.innerHTML = o.before ? end + list : list + end;
    box.scrollTop = o.before ? box.scrollHeight - (keep ? fromEnd : 0) : keep ? top : 0;
    $(`[data-n="${i}"]`, drawer).textContent = m ? `${rows.length} of ${all.length}` : o.w.total ? `${o.w.total.toLocaleString()} event${o.w.total > 1 ? "s" : ""}` : "";
  };
  const loadAll = async (i) => {   // the whole stretch, not just the events nearest the power cycle
    const o = wins[i], w = o.w;
    if (!o.sw || w.loaded || w.events.length >= w.total) return;
    const evs = await api(`/api/cases/${encodeURIComponent(cid)}/events?tag=software&limit=5000${o.before ? "&last=1" : ""}&from=${encodeURIComponent(w.from)}&to=${encodeURIComponent(w.to)}`);
    const a = tsOf(w.anchor);
    w.events = evs.map((e) => ({ ...e, offset_s: Math.round((tsOf(e.time) - a) * 10) / 10 }));
    w.loaded = true;
  };
  wins.forEach((_, i) => fill(i));
  $("#drQ")?.addEventListener("input", debounce(async (ev) => {
    q = ev.target.value;
    if (matcher(q)) await Promise.all(wins.map((_, i) => loadAll(i).catch(() => { /* search what is loaded */ })));
    wins.forEach((_, i) => fill(i));
  }));
  $(".dr-b", drawer).addEventListener("click", async (ev) => {
    const more = ev.target.closest("[data-more]");
    if (more) {
      more.disabled = true; more.textContent = "Loading…";
      try { await loadAll(+more.dataset.more); fill(+more.dataset.more, true); } catch (e) { more.textContent = e.message; }
      return;
    }
    const a = ev.target.closest("a.cyc"); if (a) return openDetail(a.dataset.id);
    const r = ev.target.closest(".wrow"); if (!r) return;
    const box = r.nextElementSibling; box.hidden = !box.hidden;
    if (box.hidden || box.textContent) return;
    box.textContent = "Loading…";
    try {
      const [e] = await api(`/api/cases/${encodeURIComponent(cid)}/events?around=${r.dataset.idx}&n=0`);
      box.textContent = JSON.stringify(e?.data ?? {}, null, 1);
    } catch (err) { box.textContent = err.message; }
  });
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
      ${evs.map((e) => `<tr class="click ${String(e.idx) === String(idx) ? "hl" : ""}" data-i="${e.idx}" title="${esc((e.msg || "").slice(0, 600))}"><td>${fmt(e.time).slice(5)}</td><td>${esc(shortChan(e.channel))}</td>
        <td>${esc(e.provider.replace("Microsoft-Windows-", ""))}</td><td>${eidTag(e.eid, e.provider)}</td></tr>
        <tr class="dat" data-for="${e.idx}" style="display:none"><td colspan="4">${e.msg ? `<div class="lmsg">${esc(e.msg)}</div>` : ""}<pre class="data">${esc(JSON.stringify(e.data, null, 1))}</pre></td></tr>`).join("")}
      </tbody></table></div></div><div class="muted small" style="margin-top:6px">Click a row to see what the event says and its data. Highlighted row is the selected evidence.</div>`;
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
  S.tl = S.tl || {};
  if (S.tl.t0 == null) { const pad = (c.coverage.end_ts - c.coverage.start_ts) * 0.01 || 60; S.tl.t0 = c.coverage.start_ts - pad; S.tl.t1 = c.coverage.end_ts + pad; }
  if (S.tl.cur == null) { const it = c.items.find((x) => x.type === "hard" && x.last_alive_ts); S.tl.cur = it ? it.last_alive_ts : c.coverage.start_ts; }
  S.tl.win = S.tl.win || store.get("tlwin", 5);
  /* one card: the timeline, then the logs at its line, so both fit on one screen; the legend opens on hover */
  $("#tabBody").innerHTML = `
    <div class="card"><div class="card-h"><h3>Timeline</h3>
      <div class="tl-tools"><span class="muted small">Scroll to zoom · drag to pan · click or drag the line to read the logs · Shift-drag for a range · ← → next event</span>
        <span class="menu tl-leg"><button class="btn">Legend</button><div class="menu-pop legend">
          <span><i style="background:var(--accent);opacity:.35"></i>Powered on (boot session)</span>
          ${Object.entries(TYPES).map(([k, v]) => `<span><i style="background:${v.color}"></i>${v.label}</span>`).join("")}
          <span><i style="background:var(--warn)"></i>Storage / app warning</span><span><i style="background:var(--bad)"></i>Storage error / reset, app crash</span>
          <span><i style="background:var(--ok);opacity:.6"></i>Drive normal activity</span>
          <span><i style="background:var(--sam-soft);box-shadow:inset 0 0 0 1.5px var(--sam)"></i>${esc(HV())} drive lane</span>
          <span><i style="background:var(--accent)"></i>Update / install / restart</span>
          <span><i style="background:var(--ink)"></i>The line, or a range's start and end: their logs are listed below</span></div></span>
        <button class="btn" id="zin">+</button><button class="btn" id="zout">−</button><button class="btn" id="zfit">Fit</button></div></div>
      <div class="card-b"><div class="tl-wrap" id="tlwrap"><svg id="tlsvg"></svg><div class="tl-band" id="tlband"></div>
        <div class="tl-cur" id="tlcur"><div class="grab"></div><span class="lbl" title="Drag to move through time"></span></div>
        <div class="tl-cur" id="tlA" data-end="a"><div class="grab"></div><span class="lbl" title="Start of the range: drag to move it"></span></div>
        <div class="tl-cur" id="tlB" data-end="b"><div class="grab"></div><span class="lbl" title="End of the range: drag to move it"></span></div></div>
      <div class="lc-bar"><h3 id="lcH">Logs at the line</h3><span class="muted small" id="lcT"></span><span class="spacer"></span>
        <button class="btn" id="lcPrev">‹</button><button class="btn" id="lcNext">›</button>
        <select id="lcW" title="How far either side of the line">${[1, 5, 10, 30, 60].map((v) => `<option value="${v}" ${v === S.tl.win ? "selected" : ""}>± ${v} s</option>`).join("")}</select>
        <button class="btn" id="lcR" title="Every log between a start and an end line">Range</button></div>
      <div class="lc-grid" id="lcGrid">${LOGS.map(([k, n]) => `<div class="lc"><div class="lc-h"><b>${n}</b><span class="muted small" id="lcn-${k}"></span></div><div class="lc-b" id="lc-${k}"></div></div>`).join("")}</div></div></div>`;
  drawTimeline();
  const svg = $("#tlsvg");
  svg.addEventListener("wheel", (e) => {
    e.preventDefault(); const r = svg.getBoundingClientRect();
    const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.shiftKey ? e.deltaY : 0;   // sideways = pan
    if (!d) return zoomAt((e.clientX - r.left) / r.width, e.deltaY > 0 ? 1.25 : 0.8);
    const dt = (d / (r.width - TL_LW - TL_R)) * (S.tl.t1 - S.tl.t0); S.tl.t0 += dt; S.tl.t1 += dt; queueDraw();
  }, { passive: false });
  /* one set of listeners for every mark: tooltips, clicks, and a drag to pan (a press that does not move puts the line there) */
  const tt = $("#tooltip");
  let drag = null;
  svg.addEventListener("mousedown", (e) => {   // with Shift a drag draws a range instead
    if (e.target.closest(".mk, .ctxe")) return;
    drag = { x: e.clientX, t0: S.tl.t0, t1: S.tl.t1, moved: false, from: e.shiftKey ? tlT(e.clientX) : null };
    if (!e.shiftKey) svg.classList.add("drag");
  });
  window.onmouseup = (e) => {
    if (drag && !drag.moved && $("#tlsvg")) clickAt(tlT(e.clientX));
    drag = null; $("#tlsvg")?.classList.remove("drag");
  };
  svg.addEventListener("mousemove", (e) => {
    if (drag && (drag.moved || Math.abs(e.clientX - drag.x) >= 4)) {
      drag.moved = true; tt.style.opacity = 0;
      if (drag.from != null) { const t = tlT(e.clientX); return setRange({ a: Math.min(drag.from, t), b: Math.max(drag.from, t) + 1e-3 }); }
      const r = svg.getBoundingClientRect(), dt = ((drag.x - e.clientX) / (r.width - TL_LW)) * (drag.t1 - drag.t0);
      S.tl.t0 = drag.t0 + dt; S.tl.t1 = drag.t1 + dt; queueDraw();
      return;
    }
    const n = e.target.closest(".hit");
    if (!n) { tt.style.opacity = 0; return; }
    tt.innerHTML = n.dataset.tip; tt.style.opacity = 1;
    tt.style.left = Math.min(innerWidth - 310, e.clientX + 14) + "px"; tt.style.top = e.clientY + 14 + "px";
  });
  svg.addEventListener("mouseleave", () => (tt.style.opacity = 0));
  svg.addEventListener("click", (e) => {
    const n = e.target.closest(".mk, .ctxe"); if (!n) return;
    tt.style.opacity = 0;
    if (n.classList.contains("ctxe")) return moveTo(+n.dataset.t);
    const it = c.items.find((x) => x.id === n.dataset.id); if (it?.time_ts) moveTo(it.time_ts);
    openDetail(n.dataset.id);
  });
  $$(".tl-cur", $("#tlwrap")).forEach((cur) => cur.addEventListener("pointerdown", (e) => {   // the line, or a range's start or end
    e.preventDefault(); cur.classList.add("on"); $("#tooltip").style.opacity = 0;   // the drag listens on the window, so a fast move does not lose it
    const move = (ev) => (cur.dataset.end ? moveEnd(cur.dataset.end, tlT(ev.clientX)) : setCursor(tlT(ev.clientX), { snap: true }));
    const up = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", up); removeEventListener("pointercancel", up); cur.classList.remove("on"); };
    addEventListener("pointermove", move); addEventListener("pointerup", up); addEventListener("pointercancel", up);
  }));
  $("#zin").onclick = () => zoomAt(0.5, 0.6); $("#zout").onclick = () => zoomAt(0.5, 1.6);
  $("#zfit").onclick = () => { S.tl.t0 = null; tabTimeline(); };
  $("#lcPrev").onclick = (e) => stepCursor(-1, e.shiftKey); $("#lcNext").onclick = (e) => stepCursor(1, e.shiftKey);
  $("#lcW").onchange = (e) => { S.tl.win = +e.target.value; store.set("tlwin", S.tl.win); placeCursor(); renderLogs(); };
  $("#lcR").onclick = () => setRange(S.tl.range ? null : startRange());
  /* a range lists from its start: the next rows come as a list is scrolled to its end */
  $$(".lc-b").forEach((box) => box.addEventListener("scroll", () => {
    if (!S.tl.range || box._more || !box.querySelector(".lshow") || box.scrollTop + box.clientHeight < box.scrollHeight - 80) return;
    box._more = true; box._n += LOG_MAX; queueLogs();
  }));
  $("#lcGrid").onclick = (ev) => {
    const j = ev.target.closest(".ljump"); if (j) return moveTo(+j.dataset.t);
    const s = ev.target.closest(".lshow"); if (s) { s.closest(".lc-b")._n += LOG_MAX; return renderLogs(); }
    const r = ev.target.closest(".lr"), ix = S.ix; if (!r || !ix) return;
    const i = +r.dataset.idx;
    if (ix.open.has(i)) ix.open.delete(i); else { ix.open.add(i); if (!ix.full.has(i)) loadFull(ix, i); }
    renderLogs();
  };
  window.onresize = () => { if (S.tab === "timeline") { drawTimeline(); sizeLogs(); } };
  rangeBar(); sizeLogs(); renderLogs();
  loadIndex().then(renderLogs).catch((e) => LOGS.forEach(([k]) => { const b = $(`#lc-${k}`); if (b) b.innerHTML = `<div class="lempty">${esc(e.message)}</div>`; }));
}
function zoomAt(frac, k) {
  const W = $("#tlsvg").getBoundingClientRect().width;
  const f = Math.min(1, Math.max(0, (frac * W - TL_LW) / (W - TL_LW - TL_R)));
  const span = S.tl.t1 - S.tl.t0, ns = Math.max(120, span * k), at = S.tl.t0 + f * span;
  S.tl.t0 = at - f * ns; S.tl.t1 = at + (1 - f) * ns; queueDraw();
}
function drawTimeline() {
  const svg = $("#tlsvg"), c = S.c; if (!svg) return;
  const W = svg.getBoundingClientRect().width || 900, LW = TL_LW, R = TL_R;
  S.tl.W = W;
  const chans = c.channels;
  const hasHl = c.storage_events.some((e) => isHl(e.hl));
  const lanes = [["power", "Power state", 34], ["trans", "Transitions", 34], ["sleep", "Sleep", 26],
    ...(hasHl ? [["hl", `${HV()} drive`, 26]] : []), ["drive", hasHl ? "Other storage" : "Drive events", 26],
    ...(c.software_events ? [["sw", "Apps & updates", 26]] : []), ...chans.map((ch, i) => ["ch" + i, shortChan(ch.channel), 18])];
  let y = 34; const ly = lanes.map(([k, n, h]) => { const o = { k, n, y, h }; y += h + 8; return o; });
  const L = Object.fromEntries(ly.map((l) => [l.k, l]));
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
  ly.forEach((l) => out.push(`<text x="10" y="${l.y + l.h / 2 + 4}" font-size="11.5" fill="${l.k === "hl" ? "var(--sam)" : "var(--ink-2)"}" font-weight="${l.h > 20 ? 600 : 400}">${esc(l.n.length > 22 ? l.n.slice(0, 21) + "…" : l.n)}</text>`,
    l.k === "hl" ? `<rect x="${LW}" y="${l.y}" width="${W - LW - R}" height="${l.h}" rx="5" fill="var(--sam-soft)" stroke="var(--sam)" stroke-width="1"/>`
      : `<rect x="${LW}" y="${l.y}" width="${W - LW - R}" height="${l.h}" rx="5" fill="var(--panel-2)"/>`));
  const clipX = (a, b) => [Math.max(LW, x(a)), Math.min(W - R, x(b))];
  /* a lane with hundreds of marks in view (a case with thousands of power cycles, zoomed out) keeps its most important
     one per slot of a mark's width, and the tooltip says how many more are there: it stays a few thousand nodes and
     pans smoothly. Lanes with fewer marks draw every one, as before */
  const LOD = 300;
  const more = (n) => (n > 1 ? `<br><i>+${(n - 1).toLocaleString()} more here · zoom in</i>` : "");
  const bin = (list, px, rank, w = 3) => {   // w: pixels per slot, about a mark's width - closer marks overlap anyway
    if (list.length <= LOD) return list.map((m) => ({ m, n: 1 }));
    const best = new Map();
    for (const m of list) {
      const k = Math.round(px(m) / w), b = best.get(k);
      if (!b) best.set(k, { m, n: 1 });
      else { b.n++; if (rank(m) > rank(b.m)) b.m = m; }
    }
    return [...best.values()];
  };
  const T = (e) => e._t ?? (e._t = tsOf(e.time));
  // sessions: with hundreds in view, ones that touch at this zoom become one bar
  const L0 = L.power, inView = c.sessions.filter((s) => vis(s.start_ts, s.end_ts)), merge = inView.length > LOD;
  let run = null;
  const flush = () => {
    if (!run) return; const s = run.first;
    const tip = run.n === 1 ? `<b>Boot session ${s.id}</b>${fmtTs(s.start_ts)} → ${fmtTs(s.end_ts)}<br>${s.boot_type || (s.partial_start ? "started before log" : "")}`
      : `<b>${run.n.toLocaleString()} boot sessions</b>${fmtTs(s.start_ts)} → ${fmtTs(run.end)}<br><i>zoom in to see each</i>`;
    out.push(`<rect class="hit" data-tip="${esc(tip)}" x="${run.a}" y="${L0.y + 6}" width="${Math.max(2, run.b - run.a)}" height="${L0.h - 12}" rx="4" fill="var(--accent)" opacity=".28"/>`);
  };
  inView.forEach((s) => {
    const [a, b] = clipX(s.start_ts, s.end_ts);
    if (merge && run && a <= run.b + 1) { run.b = Math.max(run.b, b); run.n++; run.end = s.end_ts; }
    else { flush(); run = { a, b, n: 1, first: s, end: s.end_ts }; }
  });
  flush();
  // transitions and sleeps: a hard shutdown or one that needs review wins its pixel
  const L1 = L.trans, L2 = L.sleep, TR = { hard: 4, unknown: 3, restart: 2, shutdown: 1 };
  const tipOf = (it) => `<b>${it.id} · ${TYPES[it.type].label}</b>${esc(it.subtype)}<br>${fmtTs(it.time_ts)} · ${Math.round(it.confidence * 100)}%${it.needs_review ? " · needs review" : ""}${isSuspect(it) ? `<br>Drive caused it? ${esc(it.drive.cause_label)}` : ""}${hlCycle(it) ? ` · ${esc(it.drive.highlight_label)}` : ""}${it.software && it.type !== "sleep" && SW_CLS[it.software.strength] ? `<br>Trigger: ${esc(it.software.label)} (${esc(it.software.strength_label)})` : ""}`;
  const span2 = (it) => (it.type === "sleep" ? [it.start_ts || it.end_ts, it.end_ts || it.start_ts] : [it.last_alive_ts || it.boot_ts, it.boot_ts]);
  const sleeps = [], trans = [];
  c.items.forEach((it) => { const [a, b] = span2(it); if (vis(a, b)) (it.type === "sleep" ? sleeps : trans).push(it); });
  bin(sleeps, (it) => clipX(...span2(it))[0], (it) => (it.open ? 2 : 0) + (it.needs_review ? 1 : 0)).forEach(({ m: it, n }) => {
    const [xa, xb] = clipX(...span2(it)), col = TYPES.sleep.color;
    out.push(`<rect class="hit mk" data-id="${it.id}" data-tip="${esc(tipOf(it) + more(n))}" x="${xa}" y="${L2.y + 5}" width="${Math.max(5, xb - xa)}" height="${L2.h - 10}" rx="3" fill="${col}" opacity="${it.needs_review ? .55 : .85}"/>`);
    if (it.open) out.push(`<text x="${xb + 4}" y="${L2.y + L2.h / 2 + 4}" font-size="11" fill="${col}">no resume</text>`);
  });
  bin(trans, (it) => x(span2(it)[0]), (it) => (it.needs_review ? 10 : 0) + (TR[it.type] || 0), 6).forEach(({ m: it, n }) => {
    const [a, b] = span2(it), [xa, xb] = clipX(a, b), cy = L1.y + L1.h / 2, col = TYPES[it.type].color;
    if (xb - xa >= 1) out.push(`<line x1="${xa}" x2="${xb}" y1="${cy}" y2="${cy}" stroke="${col}" stroke-width="2" stroke-dasharray="3 3" opacity=".7"/>`);
    out.push(`<g class="hit mk" data-id="${it.id}" data-tip="${esc(tipOf(it) + more(n))}" transform="translate(${x(a)},${cy})"><circle r="${it.needs_review ? 8 : 7}" fill="${col}" stroke="var(--panel)" stroke-width="2"/>
      ${it.needs_review ? '<circle r="11" fill="none" stroke="var(--warn)" stroke-width="1.5"/>' : ""}</g>`);
  });
  // drive events: the highlighted vendor's drive on its own lane; the worst state wins its pixel, and normal activity
  // (Information events) is a thin green tick drawn under the problems
  const SEV = { missing: 5, reset: 4, error: 3, slow: 2, warning: 1 }, sev = (e) => (SEV[e.state] || 0) * 2 + (e.hl === "yes" ? 1 : 0);
  bin(c.storage_events.filter((e) => vis(T(e), T(e))), (e) => x(T(e)) + (isHl(e.hl) ? 3e6 : 0), sev).sort((p, q) => sev(p.m) - sev(q.m)).forEach(({ m: e, n }) => {
    const t = T(e), ok = e.state === "info", col = ok ? "var(--ok)" : STATE_COLOR[e.state] || "var(--warn)", l = isHl(e.hl) ? L.hl : L.drive;
    const who = e.dev_basis !== undefined ? `<br>${esc(e.dev || "drive not identified")}${e.hl === "probably" ? " (probably)" : ""}` : "";
    const tip = `<b>${e.eid} · ${esc(e.label)}</b>${esc(e.provider)}${ok ? " · normal activity" : ""}<br>${fmt(e.time)}${who}${more(n)}`;
    out.push(ok ? `<rect class="hit ctxe" data-t="${t}" data-tip="${esc(tip)}" x="${x(t) - 1}" y="${l.y + 7}" width="2" height="${l.h - 14}" fill="${col}" opacity=".6"/>`
      : `<rect class="hit ctxe" data-t="${t}" data-tip="${esc(tip)}" x="${x(t) - 2}" y="${l.y + 4}" width="4" height="${l.h - 8}" rx="1.5" fill="${col}" ${e.hl === "probably" ? 'opacity=".6"' : ""}/>`);
  });
  // apps & updates: problems and restart-related events; a crash wins its pixel over a restart over a warning
  const restartish = (e) => ["restart", "reboot"].includes(e.kind);
  if (L.sw) bin(c.software_events.filter((e) => (e.state !== "info" || restartish(e)) && vis(T(e), T(e))), (e) => x(T(e)),
    (e) => (e.state === "error" ? 3 : restartish(e) ? 2 : 1)).forEach(({ m: e, n }) => {
    const t = T(e), col = e.state === "error" ? "var(--bad)" : restartish(e) ? "var(--accent)" : "var(--warn)";
    out.push(`<rect class="hit ctxe" data-t="${t}" data-tip="${esc(`<b>${e.eid} · ${esc(e.label)}</b>${esc(e.subject || e.provider)}<br>${fmt(e.time)}${more(n)}`)}" x="${x(t) - 2}" y="${L.sw.y + 4}" width="4" height="${L.sw.h - 8}" rx="1.5" fill="${col}"/>`);
  });
  // coverage
  chans.forEach((ch, i) => {
    const l = L["ch" + i]; if (!vis(ch.start_ts, ch.end_ts)) return; const [a, b] = clipX(ch.start_ts, ch.end_ts);
    const col = ch.kind === "storport" ? "var(--purple)" : ch.kind === "application" ? "var(--ok)" : ch.kind === "system" ? "var(--accent)" : "var(--grey)";
    out.push(`<rect x="${a}" y="${l.y + 5}" width="${Math.max(2, b - a)}" height="${l.h - 10}" rx="3" fill="${col}" opacity=".55"/>`);
  });
  c.integrity.record_gaps.forEach((g) => {
    if (!vis(g.start_ts, g.end_ts)) return; const [a, b] = clipX(g.start_ts, g.end_ts);
    out.push(`<rect class="hit" data-tip="${esc(`<b>${g.missing} records missing</b>${esc(g.channel)}<br>${fmt(g.start)} → ${fmt(g.end)}`)}" x="${a}" y="26" width="${Math.max(3, b - a)}" height="${H - 30}" fill="var(--warn)" opacity=".14"/>`);
  });
  svg.innerHTML = out.join("");   // tooltips and clicks: the listeners set once in tabTimeline
  placeCursor();
}
/* pans and zooms redraw at most once a frame */
let drawQueued = false;
function queueDraw() { if (!drawQueued) { drawQueued = true; requestAnimationFrame(() => { drawQueued = false; drawTimeline(); }); } }

/* ------------------------------------------------------------------ timeline line: the logs at one moment */
/* the browser holds every event's time and log (one small index per case), so moving the line updates the counts,
   offsets and order in the same frame; what each event says comes from the server 256 at a time and is kept */
const TL_LW = 150, TL_R = 16;
const LOGS = [["s", "System"], ["a", "Application"], ["p", "Storport"]];
const PANEL_OF = { s: "s", a: "a", p: "p", o: "p" };   // other logs (e.g. Partition) sit with Storport
const LOG_MAX = 200, CHUNK = 256;
const LEVEL_STATE = { 1: "error", 2: "error", 3: "warning" };
const tlX = (t) => TL_LW + ((t - S.tl.t0) / (S.tl.t1 - S.tl.t0)) * (S.tl.W - TL_LW - TL_R);
function tlT(clientX) {
  const r = $("#tlsvg").getBoundingClientRect(), x = Math.min(r.width - TL_R, Math.max(TL_LW, clientX - r.left));
  return S.tl.t0 + ((x - TL_LW) / (r.width - TL_LW - TL_R)) * (S.tl.t1 - S.tl.t0);
}
function fmtMs(ts, date = false) {
  const d = new Date(Math.round((ts + tzOffset() * 60) * 1000)), p = (n, l = 2) => String(n).padStart(l, "0");
  return `${date ? `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` : ""}${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}.${p(d.getUTCMilliseconds(), 3)}`;
}
const fmtSec = (s) => (Math.abs(s) < 5e-4 ? "0.000 s" : `${s < 0 ? "−" : "+"}${Math.abs(s).toFixed(3)} s`);
function loadIndex() {
  const cid = S.c.id;
  if (S.ix?.cid === cid) return Promise.resolve(S.ix);
  if (S.ixLoad?.cid === cid) return S.ixLoad.p;
  const p = api(`/api/cases/${encodeURIComponent(cid)}/index`).then((r) => {
    const n = r.d.length, ts = new Float64Array(n), by = {};
    LOGS.forEach(([k]) => (by[k] = { n: 0 }));
    for (let i = 0, ms = r.t0; i < n; i++) { ms += r.d[i]; ts[i] = ms / 1000; by[PANEL_OF[r.k[i]]].n++; }
    Object.values(by).forEach((b) => { b.ts = new Float64Array(b.n); b.idx = new Int32Array(b.n); b.n = 0; });
    for (let i = 0; i < n; i++) { const b = by[PANEL_OF[r.k[i]]]; b.ts[b.n] = ts[i]; b.idx[b.n++] = i; }
    const ix = { cid, ts, by, rows: new Map(), full: new Map(), open: new Set() };
    if (S.c?.id === cid) S.ix = ix;
    return ix;
  });
  S.ixLoad = { cid, p };
  p.catch(() => { if (S.ixLoad?.p === p) S.ixLoad = null; });
  return p;
}
/* the line, or a range's start and end lines with the stretch between them shaded */
function placeCursor() {
  const tl = S.tl, band = $("#tlband"); if (!band || tl?.cur == null || !tl.W) return;
  const r = tl.range, x0 = TL_LW, x1 = tl.W - TL_R, clip = (x) => Math.min(x1, Math.max(x0, x));
  const [a, b] = r ? [r.a, r.b] : [tl.cur - tl.win, tl.cur + tl.win], xa = clip(tlX(a)), xb = clip(tlX(b)), cx = tlX(tl.cur);
  band.style.display = (r ? xb > xa : cx >= x0 - 1 && cx <= x1 + 1) ? "" : "none";
  band.classList.toggle("rng", !!r);
  band.style.left = `${xa}px`; band.style.width = `${Math.max(0, xb - xa)}px`;
  pin($("#tlcur"), r ? null : tl.cur, "mid"); pin($("#tlA"), r?.a, "left"); pin($("#tlB"), r?.b, "right");
}
/* one line and its time label: a range's labels open outwards (start to the left, end to the right), flipped at the edges */
function pin(el, t, side) {
  const tl = S.tl, x = t == null ? NaN : tlX(t), show = x >= TL_LW - 1 && x <= tl.W - TL_R + 1;
  el.style.display = show ? "" : "none";
  if (!show) return;
  el.style.left = `${x}px`;
  const lbl = $(".lbl", el), room = 130; lbl.textContent = fmtMs(t, true).slice(5);
  lbl.style.transform = side === "left" ? (x - room < TL_LW ? "translateX(0)" : "translateX(-100%)")
    : side === "right" ? (x + room > tl.W ? "translateX(-100%)" : "translateX(0)") : x > tl.W - 80 ? "translateX(-100%)" : "";
}
/* zoomed out, a pixel is minutes: a click or drag near events lands on the nearest one instead of on empty time */
function snapT(t) {
  const ix = S.ix, tl = S.tl; if (ix?.cid !== S.c.id || !ix.ts.length) return t;
  const a = ix.ts, i = bisect(a, (v) => v < t - tl.win);
  if (i < a.length && a[i] <= t + tl.win) return t;
  const j = bisect(a, (v) => v < t), near = [a[j - 1], a[j]].filter((v) => v !== undefined).sort((p, q) => Math.abs(p - t) - Math.abs(q - t))[0];
  return near !== undefined && Math.abs(near - t) <= (8 * (tl.t1 - tl.t0)) / Math.max(1, tl.W - TL_LW - TL_R) ? near : t;
}
function setCursor(t, { snap = false, follow = false } = {}) {
  const tl = S.tl; if (!tl || !Number.isFinite(t)) return;
  tl.cur = snap ? snapT(t) : t;
  if (follow && (tl.cur < tl.t0 || tl.cur > tl.t1)) { const h = (tl.t1 - tl.t0) / 2; tl.t0 = tl.cur - h; tl.t1 = tl.cur + h; drawTimeline(); }
  else placeCursor();
  queueLogs();
}
/* a range: every log between its start a and end b; null goes back to the line (inside the range) */
function setRange(r, { follow = false } = {}) {
  const tl = S.tl, old = tl.range;
  if (!r && old && (tl.cur < old.a || tl.cur > old.b)) tl.cur = (old.a + old.b) / 2;
  tl.range = r;
  rangeBar();
  if (follow && r && (r.a < tl.t0 || r.b > tl.t1)) {
    const span = Math.max(tl.t1 - tl.t0, (r.b - r.a) * 1.25), m = (r.a + r.b) / 2;
    tl.t0 = m - span / 2; tl.t1 = m + span / 2; drawTimeline();
  } else placeCursor();
  queueLogs();
}
/* a new range around the line (when it is in view): ± the chosen seconds, or a fifth of the view if that is wider */
function startRange() {
  const tl = S.tl, m = tl.cur >= tl.t0 && tl.cur <= tl.t1 ? tl.cur : (tl.t0 + tl.t1) / 2, h = Math.max(tl.win, (tl.t1 - tl.t0) / 10);
  return { a: m - h, b: m + h };
}
const moveEnd = (end, t) => { const r = S.tl.range; setRange(end === "a" ? { a: Math.min(t, r.b - 1e-3), b: r.b } : { a: r.a, b: Math.max(t, r.a + 1e-3) }); };
/* a click on the timeline: the line goes there, or the nearer end of a range */
function clickAt(t) {
  const r = S.tl.range;
  if (!r) return setCursor(t, { snap: true });
  moveEnd(Math.abs(t - r.a) <= Math.abs(t - r.b) ? "a" : "b", t);
}
/* a mark or a "next" link: the line moves there; a range keeps its length and centres on it when it is outside */
function moveTo(t) {
  const r = S.tl.range;
  if (!r) return setCursor(t, { follow: true });
  if (t < r.a || t > r.b) setRange({ a: t - (r.b - r.a) / 2, b: t + (r.b - r.a) / 2 }, { follow: true });
}
function rangeBar() {
  const r = S.tl.range, w = r ? "The same length" : "", b = $("#lcR"); if (!b) return;
  $("#lcH").textContent = r ? "Logs in the range" : "Logs at the line";
  b.classList.toggle("on", !!r); b.title = r ? "Back to one line" : "Every log between a start and an end line";
  $("#lcW").style.display = r ? "none" : "";
  $("#lcPrev").title = `${r ? `${w} earlier` : "Previous event"} (←) · Shift: previous power cycle`;
  $("#lcNext").title = `${r ? `${w} later` : "Next event"} (→) · Shift: next power cycle`;
}
/* ← → the next event in any of the logs (a range: the same length earlier / later); with Shift the next power cycle */
function stepCursor(dir, cycle) {
  const tl = S.tl, r = tl?.range; if (tl?.cur == null) return;
  if (r && !cycle) return setRange({ a: r.a + dir * (r.b - r.a), b: r.b + dir * (r.b - r.a) }, { follow: true });
  const t = r ? (r.a + r.b) / 2 : tl.cur;
  let a = S.ix?.cid === S.c.id ? S.ix.ts : [];
  if (cycle) a = S.c.items.map((x) => x.time_ts).filter((x) => x != null).sort((p, q) => p - q);
  const i = dir > 0 ? bisect(a, (v) => v <= t + 5e-4) : bisect(a, (v) => v < t - 5e-4) - 1;
  if (i < 0 || i >= a.length) return;
  if (r) setRange({ a: a[i] - (r.b - r.a) / 2, b: a[i] + (r.b - r.a) / 2 }, { follow: true });
  else setCursor(a[i], { follow: true });
}
/* the three logs fill what the window has left below the timeline, so both fit on one screen where they can */
function sizeLogs() {
  const g = $("#lcGrid"), card = $("#tlwrap")?.closest(".card"); if (!g || !card) return;
  const below = g.getBoundingClientRect().top - card.getBoundingClientRect().top;
  g.style.setProperty("--lch", `${Math.max(200, Math.min(520, innerHeight - 58 - below - 64))}px`);
}
function rangeText(r) {
  const a = fmtMs(r.a, true), b = fmtMs(r.b, true), d = r.b - r.a;
  return `${a} → ${a.slice(0, 10) === b.slice(0, 10) ? b.slice(11) : b} ${tzLabel()} · ${d < 10 ? `${d.toFixed(2)}s` : fmtDur(d)}`;
}
let logsQueued = false;
function queueLogs() { if (!logsQueued) { logsQueued = true; requestAnimationFrame(() => { logsQueued = false; renderLogs(); }); } }
/* the line: the events within ± w of it, the nearest 200 shown around a marker at the line's time.
   a range: every event from its start to its end, 200 more each time a list is scrolled to its end */
function renderLogs() {
  const tl = S.tl, ix = S.ix; if (!$("#lcGrid") || tl?.cur == null) return;
  const r = tl.range, t = tl.cur, w = tl.win, [p, q] = r ? [r.a, r.b] : [t - w, t + w], key = r ? `r${r.a}` : `${t}|${w}`;
  $("#lcT").textContent = r ? rangeText(r) : `${fmtMs(t, true)} ${tzLabel()}`;
  if (ix?.cid !== S.c.id) { LOGS.forEach(([k]) => { $(`#lc-${k}`).innerHTML = '<div class="lempty">Loading the logs…</div>'; }); return; }
  const miss = [], where = r ? "in the range" : `within ±${w} s`;
  LOGS.forEach(([k, name]) => {
    const b = ix.by[k], box = $(`#lc-${k}`), cnt = $(`#lcn-${k}`);
    box._more = false;
    if (!b.ts.length) { cnt.textContent = ""; box.innerHTML = `<div class="lempty">No ${name} log in this case</div>`; return; }
    const lo = bisect(b.ts, (v) => v < p), hi = bisect(b.ts, (v) => v <= q);
    const keep = box._key === key, top = box.scrollTop; box._key = key;   // a range keeps its scroll while only its end moves
    if (!keep) box._n = LOG_MAX;
    cnt.textContent = hi > lo ? `${(hi - lo).toLocaleString()} ${where}` : "";
    if (hi === lo) {
      box.innerHTML = `<div class="lempty">Nothing logged ${where}${lo > 0 ? `<a class="ljump" data-t="${b.ts[lo - 1]}">‹ previous: ${fmtDur((r ? p : t) - b.ts[lo - 1])} ${r ? "before the start" : "earlier"}</a>` : ""}${hi < b.ts.length ? `<a class="ljump" data-t="${b.ts[hi]}">next: ${fmtDur(b.ts[hi] - (r ? q : t))} ${r ? "after the end" : "later"} ›</a>` : ""}</div>`;
      return;
    }
    const at = r ? -1 : bisect(b.ts, (v) => v < t), a = r ? lo : Math.max(lo, Math.min(at - LOG_MAX / 2, hi - LOG_MAX)), z = Math.min(hi, a + (r ? box._n : LOG_MAX));
    const now = `<div class="lnow"><span>${fmtMs(t)}</span></div>`, html = [];
    const days = r && fmtMs(p, true).slice(0, 10) !== fmtMs(q, true).slice(0, 10);   // a range over midnight: a heading for each day
    let day = "";
    if (a > lo) html.push(`<div class="lmore">${(a - lo).toLocaleString()} earlier not shown</div>`);
    for (let i = a; i < z; i++) {
      if (i === at) html.push(now);
      if (days && fmtMs(b.ts[i], true).slice(0, 10) !== day) { day = fmtMs(b.ts[i], true).slice(0, 10); html.push(`<div class="lday">${day}</div>`); }
      const gi = b.idx[i], row = ix.rows.get(gi);
      if (!row) miss.push(gi);
      html.push(logRow(ix, gi, b.ts[i], b.ts[i] - (r ? p : t), row, !!r));
    }
    if (!r && at >= z) html.push(now);
    if (z < hi) html.push(r ? `<div class="lmore"><a class="lshow">Show ${Math.min(LOG_MAX, hi - z)} more</a> · ${(hi - z).toLocaleString()} later</div>`
      : `<div class="lmore">${(hi - z).toLocaleString()} later not shown</div>`);
    box.innerHTML = html.join("");
    box.scrollTop = keep ? top : r ? 0 : box.querySelector(".lnow").offsetTop - box.clientHeight / 2;
  });
  if (!miss.length) return;
  if (r) fetchIds(ix, miss);   // a range's rows can be far apart: only the ones listed
  else fetchRows(ix, Math.min(...miss), Math.max(...miss));
}
/* one event: its offset (from the line, or from a range's start) and time, what it is, and what it says - its message,
   when Windows wrote one, else its key fields. Clicked open: the whole message and every field */
function logRow(ix, i, ts, off, r, rng = false) {
  const st = r ? r.state || LEVEL_STATE[r.level] || "" : "", prov = r ? r.provider.replace("Microsoft-Windows-", "") : "";
  const log = r && !/^(System|Application|Microsoft-Windows-Storage-Storport\/Operational)$/i.test(r.channel) ? `<span class="ltag">${esc(shortChan(r.channel))}</span>` : "";
  const sub = r ? [r.label ? prov : "", r.text].filter(Boolean).join(" · ") : "", full = ix.full.get(i);
  return `<div class="lr ${st}${!rng && Math.abs(off) < 5e-4 ? " at" : ""}" data-idx="${i}" title="${esc(r?.msg || sub)}">
    <div class="lo"><b>${rng && off >= 60 ? `+${fmtDur(off)}` : fmtSec(off)}</b><span>${fmtMs(ts)}</span></div>
    <div class="lx"><div>${r ? `${r.eid === "" ? "" : eidTag(r.eid, r.provider, "mono")} ${esc(r.label || prov)}${log}` : "&nbsp;"}</div><div class="lt">${r ? esc(sub) || "&nbsp;" : "…"}</div></div></div>${
    !ix.open.has(i) ? "" : !full ? '<pre class="data lpre">Loading…</pre>' : `<div class="lmsg${full.msg ? "" : " none"}">${esc(full.msg || "No message text for this event")}</div>
    <pre class="data lpre">${esc(JSON.stringify(full.data, null, 1))}</pre>`}`;
}
let rowsBusy = false;
async function getRows(ix, query, want) {
  if (rowsBusy) return;   // one request at a time: when it lands, the next frame asks for whatever is still missing
  rowsBusy = true;
  try {
    const rows = await api(`/api/cases/${encodeURIComponent(ix.cid)}/rows?${query}`);
    if (ix.rows.size > 20000) ix.rows.clear();   // a few lists' worth; the ones in view come back in the next request
    rows.forEach((r) => ix.rows.set(r.idx, r));
    want.forEach((i) => { if (!ix.rows.has(i)) ix.rows.set(i, { idx: i, eid: "", level: 4, provider: "", channel: "", label: "(not found)", text: "", state: "" }); });
  } catch (e) { toast(e.message); return; } finally { rowsBusy = false; }
  if (S.ix === ix) queueLogs();
}
function fetchRows(ix, lo, hi) {   // plus a block either side, so a drag finds the next rows already here
  const a = Math.max(0, (Math.floor(lo / CHUNK) - 1) * CHUNK), b = Math.min(ix.ts.length, a + 16 * CHUNK, (Math.floor(hi / CHUNK) + 2) * CHUNK);
  getRows(ix, `from=${a}&to=${b}`, Array.from({ length: b - a }, (_, j) => a + j));
}
function fetchIds(ix, ids) { ids = ids.slice(0, 2 * CHUNK); getRows(ix, `ids=${ids.join(",")}`, ids); }
async function loadFull(ix, i) {
  try { const [e] = await api(`/api/cases/${encodeURIComponent(ix.cid)}/events?around=${i}&n=0`); ix.full.set(i, { msg: e?.msg || "", data: e?.data ?? {} }); }
  catch (err) { ix.full.set(i, { msg: "", data: { error: err.message } }); }
  if (S.ix === ix) renderLogs();
}

/* ------------------------------------------------------------------ drive */
function tabDrive() {
  const c = S.c, hv = HV();
  const shows = [["all", "All activity"], ["problems", "Warnings & errors"], ["info", "Normal activity"],
    ...[...new Set(c.storage_events.map((e) => e.state))].filter((s) => s !== "info").map((s) => [s, s])];
  const by = { yes: 0, probably: 0, no: 0, "": 0 };
  c.storage_events.forEach((e) => (by[e.hl ?? ""] = (by[e.hl ?? ""] || 0) + 1));
  const known = c.storage_events.length && c.storage_events[0].hl !== undefined;
  const whoOpts = [["all", "All drives"], ["hl", `${hv} drive`], ["no", "Other drives"], ["none", "Not identified"]];
  $("#tabBody").innerHTML = `
    ${c.disks.length ? `<div class="grid g3" style="margin-bottom:16px">${c.disks.map((d) => `<div class="card card-b disk ${d.highlight ? "sam" : ""}">
      <div class="row" style="justify-content:space-between"><span class="muted small">${esc(d.source === "named in storage events" ? "Named in storage events" : "Disk seen in logs")} · ${fmt(d.first_seen, false)}</span>${d.highlight ? `<span class="chip sam">${esc(hv)}</span>` : d.Vendor ? `<span class="chip other">${esc(d.Vendor)}</span>` : ""}</div>
      <div style="font-weight:700;font-size:15px;margin:3px 0 8px">${esc(d.Model || "Unknown model")}</div>
      <dl class="kv">${Object.entries(d).filter(([k]) => !["Model", "first_seen", "source", "highlight", "Vendor"].includes(k)).map(([k, v]) => `<dt>${esc(k)}</dt><dd class="mono">${esc(v)}</dd>`).join("")}</dl></div>`).join("")}</div>`
      : `<div class="note" style="margin-bottom:16px">No disk inventory events (Partition/Diagnostic 1006) in these logs — add that log to see model, firmware and serial, and to tie disk events to a drive by disk number.</div>`}
    <div class="card"><div class="card-h"><h3>Drive activity <span class="muted small" id="stN"></span></h3>
      <div class="row">${searchBox("stQ")}${known ? `<label class="muted small">Drive <select id="stW">${whoOpts.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></label>` : ""}
        <label class="muted small">Show <select id="stF">${shows.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></label></div></div>
      ${known ? `<div class="card-b" style="padding-bottom:0"><div class="dsum">
        <span class="chip sam">${esc(hv)}</span><b>${by.yes}</b><span class="muted">named or mapped by disk number</span>
        <span class="chip samp">${esc(hv)}?</span><b>${by.probably}</b><span class="muted">probably (name no drive, only drive seen)</span>
        <span class="chip other">other drive</span><b>${by.no}</b>
        <span class="chip nodata">not identified</span><b>${by[""]}</b></div></div>` : ""}
      <div class="tbl-wrap" style="max-height:calc(100vh - 420px)"><table class="t" id="stT"></table></div></div>`;
  const draw = () => {
    const f = $("#stF").value, w = $("#stW")?.value || "all", m = matcher(S.v.stQ);
    const rows = c.storage_events.filter((e) => (f === "all" || (f === "problems" ? e.state !== "info" : e.state === f)) &&
      (w === "all" || (w === "hl" ? isHl(e.hl) : w === "no" ? e.hl === "no" : !e.hl)) &&
      (!m || m([e.eid], `${e.label} ${e.provider} ${e.dev || ""} ${e.dev_basis || ""} ${e.channel}`)));
    $("#stN").textContent = rows.length < c.storage_events.length ? `${rows.length.toLocaleString()} of ${c.storage_events.length.toLocaleString()}` : "";
    pageRows($("#stT"), `<thead><tr><th>Time (${tzLabel()})</th><th>ID</th><th>Meaning</th><th>Provider</th><th>Drive</th><th>Log</th><th>State</th><th>Near</th></tr></thead>`, rows, (e) => `
      <tr class="click ${e.state === "info" ? "info" : isHl(e.hl) ? "sam" : ""}" data-idx="${e.idx}"><td style="white-space:nowrap">${fmt(e.time)}</td><td class="mono">${eidTag(e.eid, e.provider)}</td><td>${esc(e.label)}</td>
        <td>${esc(e.provider.replace("Microsoft-Windows-", ""))}</td>
        <td>${known ? `<span class="chips">${devBadge(e)}<span class="small">${esc(e.dev || "not identified")}</span></span><div class="muted small">${esc(e.dev_basis || "")}</div>` : '<span class="muted small">re-run to identify</span>'}</td>
        <td class="muted small">${esc(shortChan(e.channel))}</td><td>${stateChip(e.state)}</td><td class="near">${nearCell(tsOf(e.time))}</td></tr>`,
      f === "all" && !m ? "No drive events in these logs." : "No drive events match.");
  };
  onRows($("#stT"), (r) => openContext(r.dataset.idx, "Storage event"));
  bind(["stQ", "stF", "stW"], draw); draw();
}

/* ------------------------------------------------------------------ apps & updates */
function tabSoftware() {
  const c = S.c, evs = c.software_events;
  if (!evs) { $("#tabBody").innerHTML = '<div class="note">Re-run the analysis to see app, update and service events for this case.</div>'; return; }
  const show = [["problems", "Problems & restarts"], ["all", "Everything"], ["app", "App crashes & hangs"], ["update", "Windows Update"],
    ["install", "Installers"], ["service", "Services"], ["system", "Drivers, memory, power"]];
  const noApp = !(c.channels || []).some((ch) => ch.kind === "application");
  $("#tabBody").innerHTML = `
    ${noApp ? '<div class="flagbox warn" style="margin-bottom:12px">' + ICON.warn + '<span>No Application log in this case — app crashes, hangs and installer events are not visible. Only System-log events (Windows Update, services, display driver) are checked.</span></div>' : ""}
    <div class="card"><div class="card-h"><h3>App, update &amp; service events <span class="muted small" id="swN"></span></h3>
      <div class="row">${searchBox("swQ")}<label class="muted small">Show <select id="swF">${show.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></label></div></div>
      <div class="card-b" style="padding-bottom:0"><div class="muted small">Crashes, hangs, Windows Update, installers and service failures. Click a power cycle under <b>Near</b> to see what triggered it.</div></div>
      <div class="tbl-wrap" style="max-height:calc(100vh - 380px)"><table class="t" id="swT"></table></div></div>`;
  const draw = () => {
    const f = $("#swF").value, m = matcher(S.v.swQ);
    const rows = evs.filter((e) => (f === "all" || (f === "problems" ? e.state !== "info" || ["restart", "reboot"].includes(e.kind) : e.group === f)) &&
      (!m || m([e.eid], `${e.label} ${e.subject || ""} ${e.detail || ""} ${e.provider} ${e.channel}`))).reverse();   // latest first
    $("#swN").textContent = rows.length < evs.length ? `${rows.length.toLocaleString()} of ${evs.length.toLocaleString()}` : "";
    pageRows($("#swT"), `<thead><tr><th title="Latest first">Time (${tzLabel()}) ↓</th><th>ID</th><th>What</th><th>App / update / service</th><th>Source</th><th>Severity</th><th>Near</th></tr></thead>`, rows, (e) => `
      <tr class="click" data-idx="${e.idx}"><td style="white-space:nowrap">${fmt(e.time)}</td><td class="mono">${eidTag(e.eid, e.provider)}</td><td>${esc(e.label)}</td>
        <td>${esc(e.subject || "")}${e.detail ? `<div class="muted small">${esc(e.detail)}</div>` : ""}</td>
        <td class="muted small">${esc(e.provider.replace("Microsoft-Windows-", ""))} · ${esc(shortChan(e.channel))}</td><td>${stateChip(e.state)}</td>
        <td class="near">${nearCell(tsOf(e.time))}</td></tr>`,
      m && f !== "all" ? "No match here — try Show: Everything." : "Nothing of this kind was logged.");
  };
  onRows($("#swT"), (r) => openContext(r.dataset.idx, "App / update event"));
  bind(["swQ", "swF"], draw); draw();
}

/* ------------------------------------------------------------------ references: what each event ID means */
/* the reference is one small list for every case, loaded once; the event IDs in the open case come once per case.
   A lookup is one Map get, a search one pass over a few hundred lines */
const REF_LOGS = [["s", "System"], ["a", "Application"], ["p", "Storport"]];
const refKey = (p, e) => `${String(p).toLowerCase()}|${e}`;
const eidTag = (eid, prov, cls = "") => `<b class="eid ${cls}" data-p="${esc(prov)}" title="What does ${eid} mean?">${eid}</b>`;
let REF = null;
function loadRef() {
  REF = REF || api("/api/reference").then((rows) => {
    const list = rows.map(([k, p, eid, title, text, use]) => {
      const [a, b] = String(eid).split("-").map(Number);
      return { k, p, eid, title, text, use, provs: p.split("|"), ids: b ? Array.from({ length: b - a + 1 }, (_, i) => a + i) : [a],
        q: `${eid} ${p} ${title} ${text}`.toLowerCase() };
    });
    const by = new Map();
    list.forEach((r) => r.provs.forEach((p) => r.ids.forEach((i) => by.set(refKey(p, i), r))));
    return { list, by };
  });
  REF.catch(() => (REF = null));
  return REF;
}
function loadIds() {
  const cid = S.c.id;
  if (S.ids?.cid !== cid) {
    const p = api(`/api/cases/${encodeURIComponent(cid)}/ids`).then((rows) => {
      const by = new Map();   // one per provider and ID, the logs it is in added up
      rows.forEach((s) => { const k = refKey(s.p, s.e), o = by.get(k); by.set(k, !o ? s : { ...o, n: o.n + s.n, er: o.er + s.er, wa: o.wa + s.wa }); });
      return { rows, by };
    });
    S.ids = { cid, p };
    p.catch(() => { if (S.ids?.p === p) S.ids = null; });
  }
  return S.ids.p;
}
const plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;
/* what an ID means: the reference's words and what LENS uses it for, then - when the case has it - how often, first and
   last (a click shows it on the timeline), what the drive's driver said and the message Windows wrote */
function refBody(r, s) {
  const use = r?.use || s?.u;
  return `${r ? `<p class="rtext">${esc(r.text)}</p>` : `<p class="rtext muted">Not in LENS's reference yet${s?.m ? " — Windows' own words for it are below." : ", and Windows gave no message for it here: open one of these events to see its fields."}</p>`}
    ${use ? `<div class="rline"><b>In LENS</b><span>${esc(use)}</span></div>` : ""}
    ${s ? `<div class="rline"><b>In this case</b><span>${plural(s.n, "event")}${s.er ? ` · <em class="bad">${plural(s.er, "error")}</em>` : ""}${s.wa ? ` · <em class="warn">${plural(s.wa, "warning")}</em>` : ""}<br>
      <span class="nw">${s.n > 1 ? "first" : "at"} <a class="rjump" data-t="${esc(s.ft)}" title="Show it on the timeline">${fmt(s.ft)}</a></span>${s.n > 1 ? ` · <span class="nw">last <a class="rjump" data-t="${esc(s.lt)}" title="Show it on the timeline">${fmt(s.lt)}</a></span>` : ""}</span></div>`
      : S.c ? '<div class="rline"><b>In this case</b><span class="muted">not logged</span></div>' : ""}
    ${s?.said ? `<div class="rline"><b>Driver said</b><span>${s.said.map(([t, n]) => `${esc(t)} <i>× ${n.toLocaleString()}</i>`).join(" · ")}${s.kinds > s.said.length ? ` · <i>${s.kinds - s.said.length} more</i>` : ""}</span></div>` : ""}
    ${s?.m ? `<div class="lmsg" title="What Windows wrote for ${s.er || s.wa ? "the worst" : "the first"} of them">${esc(s.m)}</div>` : ""}`;
}
/* the shown ID's meaning, next to it */
function closeRefPop() { const p = $("#refPop"); if (p) { p.classList.remove("open"); p._for = null; } }
async function showRefPop(el) {
  const pop = $("#refPop"), prov = el.dataset.p, eid = +el.textContent.trim(), key = refKey(prov, eid);
  if (pop._for === el) return closeRefPop();
  pop._for = el;
  const head = (r) => `<div class="rp-h"><b class="mono">${eid}</b><span>${esc(r?.title || "Event " + eid)}</span><span class="muted small">${esc(prov.replace("Microsoft-Windows-", ""))}</span></div>`;
  pop.innerHTML = head() + '<div class="muted small">Loading…</div>';
  placePop(pop, el);
  try {
    const [ref, ids] = await Promise.all([loadRef(), S.c ? loadIds().catch(() => null) : null]);
    if (pop._for !== el) return;   // another one was clicked meanwhile
    const r = ref.by.get(key), s = ids?.by.get(key), k = r?.k || ids?.rows.find((x) => refKey(x.p, x.e) === key)?.k || "s";
    pop.innerHTML = `${head(r)}${refBody(r, s)}${S.c ? `<a class="rgo" data-k="${k === "o" ? "p" : k}" data-q="${eid}" data-key="${esc(key)}">References ›</a>` : ""}`;
    placePop(pop, el);
  } catch (e) { if (pop._for === el) pop.innerHTML = head() + `<div class="muted small">${esc(e.message)}</div>`; }
}
function placePop(pop, el) {
  const r = el.getBoundingClientRect(), w = Math.min(400, innerWidth - 24);
  pop.style.width = `${w}px`; pop.classList.add("open");
  const h = pop.offsetHeight, below = r.bottom + 6 + h <= innerHeight - 12;
  pop.style.left = `${Math.min(innerWidth - w - 12, Math.max(12, r.left - 14))}px`;
  pop.style.top = `${below ? r.bottom + 6 : Math.max(12, r.top - 6 - h)}px`;
}
/* the timeline's line at this moment, with the three logs around it */
function showOnTimeline(t) {
  closeRefPop(); closeDrawer();
  const tl = (S.tl = S.tl || {});
  tl.range = null; tl.cur = t;
  if (tl.t0 != null && (t < tl.t0 || t > tl.t1)) { const h = (tl.t1 - tl.t0) / 2; tl.t0 = t - h; tl.t1 = t + h; }
  S.tab = "timeline"; renderCase();
}
function tabRefs() {
  const lg = S.v.refLog || "s";
  $("#tabBody").innerHTML = `
    <div class="row" style="margin-bottom:12px">
      ${REF_LOGS.map(([k, l]) => `<button class="fchip ${lg === k ? "on" : ""}" data-k="${k}">${l}<span class="badge" id="refN-${k}"></span></button>`).join("")}
      <div class="spacer"></div><span class="muted small" id="refC"></span>${searchBox("refQ")}
    </div>
    <div class="card"><div class="tbl-wrap" style="max-height:calc(100vh - 290px)"><table class="t" id="refT"><tbody><tr><td class="empty">Loading the reference…</td></tr></tbody></table></div></div>`;
  $$(".fchip[data-k]").forEach((b) => (b.onclick = () => { S.v.refLog = b.dataset.k; tabRefs(); }));
  let data = null;
  bind(["refQ"], () => data && drawRefs(...data));
  $("#refT").onclick = (ev) => {
    const j = ev.target.closest(".rjump"); if (j) return showOnTimeline(tsOf(j.dataset.t));
    const tr = ev.target.closest("tr.click"); if (!tr) return;
    const next = tr.nextElementSibling;
    if (next?.classList.contains("rdet")) { next.remove(); tr.classList.remove("open"); return; }
    const x = S.refRows?.get(tr.dataset.key); if (!x) return;
    tr.classList.add("open");
    tr.insertAdjacentHTML("afterend", `<tr class="rdet"><td colspan="4">${refBody(x.r, x.s)}</td></tr>`);
  };
  Promise.all([loadRef(), loadIds()]).then((d) => { if (S.tab === "refs" && $("#refT")) { data = d; drawRefs(...d); } })
    .catch((e) => { if ($("#refT")) $("#refT").innerHTML = `<tr><td class="empty">${esc(e.message)}</td></tr>`; });
}
/* one log at a time: the IDs in this case first - errors, then warnings, then the most frequent - then the reference's
   other IDs for that log. A search looks through all three logs; their counts say where the matches are */
function drawRefs(ref, ids) {
  const lg = S.v.refLog || "s", m = matcher(S.v.refQ);
  const mine = ids.rows.map((s) => { const r = ref.by.get(refKey(s.p, s.e)); return { s, r, k: s.k === "o" ? r?.k || "p" : s.k, key: `${s.k}|${refKey(s.p, s.e)}` }; });
  const used = new Set(mine.map((x) => x.r));
  const rest = ref.list.filter((r) => !used.has(r)).map((r, i) => ({ r, k: r.k, key: `r${i}` }));
  const hit = (x) => !m || (x.s ? m([x.s.e], `${x.s.e} ${x.s.p} ${x.r?.title || ""} ${x.r?.text || ""} ${x.s.m || ""} ${(x.s.said || []).map((y) => y[0]).join(" ")}`) : m(x.r.ids, x.r.q));
  const all = [...mine, ...rest].filter(hit);
  REF_LOGS.forEach(([k]) => ($(`#refN-${k}`).textContent = (m ? all : mine).filter((x) => x.k === k).length));
  const sev = (s) => (s.er ? 2 : s.wa ? 1 : 0);
  const a = all.filter((x) => x.k === lg && x.s).sort((p, q) => sev(q.s) - sev(p.s) || q.s.n - p.s.n);
  const b = all.filter((x) => x.k === lg && !x.s).sort((p, q) => p.r.ids[0] - q.r.ids[0]);
  const rows = [...a, ...(b.length ? [{ sep: `${a.length ? "Not in this case" : "Known IDs"} · ${b.length}` }] : []), ...b];
  S.refRows = new Map(rows.filter((x) => !x.sep).map((x) => [x.key, x]));
  $("#refC").textContent = m ? `${all.length} found` : `${a.length} in this case · ${b.length} more known`;
  const else_ = m && all.length ? ` — ${REF_LOGS.filter(([k]) => k !== lg && all.some((x) => x.k === k)).map(([, l]) => l).join(", ")} has some` : "";
  pageRows($("#refT"), `<thead><tr><th>ID</th><th>Source</th><th>What it means</th><th class="rn">In this case</th></tr></thead>`, rows, refRow,
    m ? `No match in this log${else_}.` : "No IDs for this log.");
  const want = S.refOpen && rows.find((x) => !x.sep && (x.s ? refKey(x.s.p, x.s.e) === S.refOpen : x.r === ref.by.get(S.refOpen)));
  S.refOpen = null;
  const tr = want && $(`#refT tr.click[data-key="${CSS.escape(want.key)}"]`);
  if (tr) { tr.click(); tr.scrollIntoView({ block: "center" }); }
}
/* how many: the count, and how many of them were errors or warnings - just that when it is all of them */
function refCount(s) {
  const [n, cls, w] = s.er ? [s.er, "error", "error"] : s.wa ? [s.wa, "warning", "warning"] : [0];
  const chip = n ? `<span class="chip ${cls}">${plural(n, w)}</span>` : "";
  return n === s.n ? chip : `${s.n.toLocaleString()}${chip ? " " + chip : ""}`;
}
function refRow(x) {
  if (x.sep) return `<tr class="rsep"><td colspan="4">${esc(x.sep)}</td></tr>`;
  const { r, s } = x, prov = (s ? s.p : r.provs.join(" / ")).replace(/Microsoft-Windows-/g, "");
  const what = r ? `<div>${esc(r.title)}</div><div class="muted small">${esc(r.text)}</div>`
    : `<div>${s.m ? esc(s.m.split("\n")[0]) : '<span class="muted">No description yet</span>'}</div><div class="muted small">${s.m ? "What Windows says — not in the reference yet" : "Open one of these events to see its fields"}</div>`;
  return `<tr class="click ${s ? "" : "rk"}" data-key="${esc(x.key)}"><td class="mono"><b>${s ? s.e : esc(String(r.eid).replace("-", "–"))}</b></td>
    <td class="muted small rp">${esc(prov)}</td><td class="rm">${what}</td>
    <td class="rn">${s ? refCount(s) : '<span class="muted">—</span>'}</td></tr>`;
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
        <div class="card-h" style="border-top:1px solid var(--line-2)"><h3>Files</h3></div><div class="tbl-wrap"><table class="t"><thead><tr><th>File</th><th>Events</th><th title="Events whose message (Event Viewer's General text) was read">With message</th><th>Read with</th></tr></thead><tbody>
        ${c.sources.map((s) => `<tr><td class="mono" title="${esc(s.path)}">${esc(s.file)}</td><td>${s.error ? `<span style="color:var(--bad)">error</span>` : s.events.toLocaleString()}</td><td>${s.messages == null || s.error ? "—" : s.messages.toLocaleString()}</td><td class="muted">${esc(s.reader || "—")}</td></tr>`).join("")}
        </tbody></table></div>
        ${c.skipped_files ? `<div class="muted small pad">${c.skipped_files.toLocaleString()} other log${c.skipped_files > 1 ? "s" : ""} in the folder skipped — only System, Application and Storport are read from a folder.</div>` : ""}</div>
    </div>
    ${g.record_gaps.length ? `<div class="card" style="margin-top:16px"><div class="card-h"><h3>Record gaps</h3></div><div class="tbl-wrap"><table class="t">
      <thead><tr><th>Log</th><th>Missing</th><th>After record</th><th>Before record</th><th>Between</th></tr></thead><tbody>
      ${g.record_gaps.map((x) => `<tr><td>${esc(shortChan(x.channel))}</td><td><b>${x.missing}</b></td><td class="mono">${x.after_rid}</td><td class="mono">${x.before_rid}</td><td>${fmt(x.start)} → ${fmt(x.end)}</td></tr>`).join("")}
      </tbody></table></div></div>` : ""}`;
}

/* ------------------------------------------------------------------ boot */
function applyTheme(t) { document.documentElement.dataset.theme = t; store.set("theme", t); }
async function init() {
  // no longer kept: the last paths typed on the home screen, SMART check inputs
  try { Object.keys(localStorage).filter((k) => k === "wela.paths" || k.startsWith("wela.smart.")).forEach((k) => localStorage.removeItem(k)); } catch { /* ignore */ }
  const theme = store.get("theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  applyTheme(theme);
  $("#themeBtn").onclick = () => { applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"); if (S.tab === "timeline" && S.c) drawTimeline(); };
  $("#tzSelect").value = store.get("tz", "0");
  $("#tzSelect").onchange = () => { store.set("tz", $("#tzSelect").value); S.c ? renderCase() : renderHome(); };
  $("#brandHome").onclick = renderHome; $("#newBtn").onclick = renderHome;
  $("#drawerBack").onclick = closeDrawer;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if ($("#refPop.open")) closeRefPop(); else closeDrawer(); } });
  /* an event ID anywhere: a click shows what it means (and does not open its row); a click elsewhere closes it */
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest(".eid");
    if (el) { ev.preventDefault(); ev.stopPropagation(); return showRefPop(el); }
    if (!ev.target.closest("#refPop")) closeRefPop();
  }, true);
  addEventListener("scroll", (ev) => { if (!$("#refPop").contains(ev.target)) closeRefPop(); }, true);
  addEventListener("resize", closeRefPop);
  $("#refPop").onclick = (ev) => {
    const j = ev.target.closest(".rjump"); if (j) return showOnTimeline(tsOf(j.dataset.t));
    const g = ev.target.closest(".rgo"); if (!g) return;
    S.v.refLog = g.dataset.k; S.v.refQ = g.dataset.q; S.refOpen = g.dataset.key;   // the References tab, on this ID, opened
    closeRefPop(); closeDrawer(); S.tab = "refs"; renderCase();
  };
  document.addEventListener("keydown", (e) => {   // timeline: ← → move the line to the previous / next event, or a range by its length
    if ((e.key !== "ArrowLeft" && e.key !== "ArrowRight") || S.tab !== "timeline" || !$("#tlcur") || $("#drawer").classList.contains("open")
      || /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName || "")) return;
    e.preventDefault(); stepCursor(e.key === "ArrowRight" ? 1 : -1, e.shiftKey);
  });
  try { S.settings = (await api("/api/config")).settings; } catch { /* defaults */ }
  renderHome();
}
init();
