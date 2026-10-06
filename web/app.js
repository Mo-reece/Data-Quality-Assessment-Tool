// UI for the in-browser data quality check. All analysis happens in worker.js.

const $ = (sel) => document.querySelector(sel);

// ── Worker RPC ───────────────────────────────────────────────────────
const worker = new Worker("worker.js", { type: "module" });
worker.onerror = (e) => {
  for (const p of pending.values()) p.reject(new Error(e.message || "The analysis engine stopped unexpectedly."));
  pending.clear();
};
let nextId = 0;
const pending = new Map();
worker.onmessage = ({ data }) => {
  const p = pending.get(data.id);
  if (!p) return;
  pending.delete(data.id);
  data.ok ? p.resolve(data.result) : p.reject(new Error(data.error));
};
function call(type, payload, transfer = []) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, type, payload }, transfer);
  });
}

// ── State ────────────────────────────────────────────────────────────
const FORMATS = {
  "": "—",
  email: ["E-mail", "[^@\\s]+@[^@\\s]+\\.[A-Za-z]{2,}"],
  phone: ["Phone", "\\+?[0-9 ()\\-]{7,20}"],
  digits: ["Digits only", "[0-9]+"],
  postcode: ["Letters & digits", "[A-Za-z0-9]+"],
  custom: "Custom regex…",
};
const state = {
  dataset: null, // {name, rows, columns, dtypes}
  config: null, // QualityConfig as a plain object
  refs: {}, // name -> {columns}
  result: null,
};

const setText = (el, text) => { el.textContent = text; };
const pct = (x, digits = 0) => `${(x * 100).toFixed(digits)}%`;
const titleCase = (s) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const tone = (s) => (s >= 0.95 ? "good" : s >= 0.7 ? "warn" : "bad");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else if (v !== false && v != null) node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) node.append(c instanceof Node ? c : String(c));
  return node;
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ── Boot ─────────────────────────────────────────────────────────────
const status = $("#engine-status");
let engineReady = false;
call("init").then(
  (version) => { engineReady = true; setText(status, `Engine ready (v${version})`); status.classList.add("ok"); },
  (err) => { setText(status, `The engine failed to start: ${err.message}`); status.classList.add("error"); },
);

// ── Loading files ────────────────────────────────────────────────────
async function readFile(file) {
  return new Uint8Array(await file.arrayBuffer());
}

async function loadMain(name, bytes) {
  const info = $("#file-info");
  info.hidden = false;
  setText(info, engineReady ? `Reading ${name}…` : `Reading ${name} — waiting for the engine to finish loading (first visit takes ~10 s)…`);
  try {
    const meta = await call("load", { key: "main", name, bytes }, [bytes.buffer]);
    state.dataset = { name: name.replace(/\.[^.]+$/, ""), ...meta };
    state.refs = {};
    state.config = await call("suggest");
    setText(info, `${name} — ${meta.rows.toLocaleString()} rows × ${meta.columns.length} columns`);
    renderRules();
    $("#step-rules").hidden = false;
    $("#step-results").hidden = true;
    $("#step-rules").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setText(info, `Could not read ${name}: ${err.message}`);
  }
}

$("#file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (f) await loadMain(f.name, await readFile(f));
  e.target.value = "";
});

const drop = $("#drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
drop.addEventListener("drop", async (e) => {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (f) await loadMain(f.name, await readFile(f));
});

$("#sample").addEventListener("click", async () => {
  const get = async (p) => new Uint8Array(await (await fetch(p)).arrayBuffer());
  const [orders, customers, rules] = await Promise.all([
    get("samples/orders.csv"), get("samples/customers.csv"), fetch("samples/orders_rules.json").then((r) => r.json()),
  ]);
  await loadMain("orders.csv", orders);
  await addRef("customers", "customers.csv", customers);
  state.config = { ...state.config, ...rules };
  renderRules();
});

async function addRef(name, filename, bytes) {
  const meta = await call("load", { key: `ref:${name}`, name: filename, bytes }, [bytes.buffer]);
  state.refs[name] = meta;
  renderRefs();
  renderRules();
}

$("#ref-file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  const name = f.name.replace(/\.[^.]+$/, "").replace(/[^\w-]/g, "_");
  try { await addRef(name, f.name, await readFile(f)); }
  catch (err) { setText($("#ref-list"), `Could not read ${f.name}: ${err.message}`); }
});

function renderRefs() {
  const names = Object.keys(state.refs);
  setText($("#ref-list"), names.length
    ? `Reference tables: ${names.map((n) => `${n} (${state.refs[n].rows.toLocaleString()} rows)`).join(", ")}`
    : "Optional: add e.g. a customers file to check that every order's customer exists.");
}

// ── Rules editor ─────────────────────────────────────────────────────
const toggle = (list, col, on) => {
  const set = new Set(list || []);
  on ? set.add(col) : set.delete(col);
  return [...set];
};

function formatKey(pattern) {
  if (!pattern) return "";
  const hit = Object.entries(FORMATS).find(([, v]) => Array.isArray(v) && v[1] === pattern);
  return hit ? hit[0] : "custom";
}

function numberOrUndefined(v) {
  return v === "" || v == null || Number.isNaN(Number(v)) ? undefined : Number(v);
}

function setRange(col, bound, value) {
  const rules = { ...(state.config.range_rules || {}) };
  const r = { ...(rules[col] || {}) };
  if (value === undefined) delete r[bound]; else r[bound] = value;
  if (Object.keys(r).length) rules[col] = r; else delete rules[col];
  state.config.range_rules = rules;
  syncJson();
}

function renderRules() {
  const c = state.config;
  const tbody = $("#rules-table tbody");
  tbody.replaceChildren();
  const refOptions = Object.entries(state.refs).flatMap(([t, m]) => m.columns.map((col) => `${t}.${col}`));

  for (const col of state.dataset.columns) {
    const pattern = (c.string_patterns || {})[col] || "";
    const fkey = formatKey(pattern);
    const range = (c.range_rules || {})[col] || {};
    const ref = (c.reference_rules || []).find((r) => r.child_col === col);

    const custom = el("input", {
      type: "text", class: "regex", value: fkey === "custom" ? pattern : "", placeholder: "regex",
      "aria-label": `Custom pattern for ${col}`, hidden: fkey !== "custom",
      onchange: (e) => { setPattern(col, e.target.value); },
    });
    const fmt = el("select", {
      "aria-label": `Format for ${col}`,
      onchange: (e) => {
        const k = e.target.value;
        custom.hidden = k !== "custom";
        setPattern(col, k === "custom" ? custom.value : k ? FORMATS[k][1] : "");
        if (k === "custom") custom.focus();
      },
    }, Object.entries(FORMATS).map(([k, v]) => el("option", { value: k, selected: k === fkey }, Array.isArray(v) ? v[0] : v)));

    const checkbox = (key, label) => el("input", {
      type: "checkbox", "aria-label": `${label} — ${col}`, checked: (c[key] || []).includes(col),
      onchange: (e) => { state.config[key] = toggle(state.config[key], col, e.target.checked); syncJson(); },
    });
    const numInput = (bound) => el("input", {
      type: "number", step: "any", class: "num-in", value: range[bound] ?? "", "aria-label": `${bound} for ${col}`,
      onchange: (e) => setRange(col, bound, numberOrUndefined(e.target.value)),
    });
    const refSelect = el("select", {
      "aria-label": `Reference for ${col}`, disabled: !refOptions.length,
      onchange: (e) => {
        const rules = (state.config.reference_rules || []).filter((r) => r.child_col !== col);
        if (e.target.value) {
          const [t, ...rest] = e.target.value.split(".");
          rules.push({ child_col: col, parent_df: t, parent_col: rest.join(".") });
        }
        state.config.reference_rules = rules;
        syncJson();
      },
    }, el("option", { value: "" }, refOptions.length ? "—" : "add a table"),
    refOptions.map((o) => el("option", { value: o, selected: ref && `${ref.parent_df}.${ref.parent_col}` === o }, o)));

    tbody.append(el("tr", {},
      el("th", { scope: "row" }, col),
      el("td", { class: "muted" }, state.dataset.dtypes[col]),
      el("td", { class: "c" }, checkbox("not_null_columns", "Required")),
      el("td", { class: "c" }, checkbox("unique_columns", "Unique")),
      el("td", { class: "c" }, checkbox("date_columns", "Date")),
      el("td", {}, fmt, custom),
      el("td", {}, numInput("min")),
      el("td", {}, numInput("max")),
      el("td", {}, refSelect),
    ));
  }

  $("#missing").value = Math.round((c.missing_threshold ?? 0.05) * 100);
  $("#date-format").value = c.date_format ?? "";
  if ($("#date-format").value !== (c.date_format ?? "")) {
    $("#date-format").append(el("option", { value: c.date_format }, c.date_format));
    $("#date-format").value = c.date_format;
  }
  $("#future").checked = !!c.allow_future_dates;
  $("#outlier").value = c.outlier_method || "iqr";
  syncJson();
}

function setPattern(col, pattern) {
  const p = { ...(state.config.string_patterns || {}) };
  if (pattern) p[col] = pattern; else delete p[col];
  state.config.string_patterns = p;
  syncJson();
}

function syncJson() {
  $("#json").value = JSON.stringify(state.config, null, 2);
  setText($("#json-error"), "");
}

$("#missing").addEventListener("change", (e) => {
  state.config.missing_threshold = Math.min(Math.max(Number(e.target.value) || 0, 0), 100) / 100; syncJson();
});
$("#date-format").addEventListener("change", (e) => { state.config.date_format = e.target.value || null; syncJson(); });
$("#future").addEventListener("change", (e) => { state.config.allow_future_dates = e.target.checked; syncJson(); });
$("#outlier").addEventListener("change", (e) => { state.config.outlier_method = e.target.value; syncJson(); });

$("#json-apply").addEventListener("click", () => {
  try {
    const parsed = JSON.parse($("#json").value);
    if (typeof parsed !== "object" || Array.isArray(parsed) || !parsed) throw new Error("Rules must be a JSON object.");
    state.config = parsed;
    renderRules();
  } catch (err) {
    setText($("#json-error"), err.message);
  }
});

$("#rules-export").addEventListener("click", () => {
  download(`${state.dataset?.name || "dataset"}_rules.json`, JSON.stringify(state.config, null, 2), "application/json");
});
$("#rules-import").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  try {
    state.config = JSON.parse(await f.text());
    renderRules();
  } catch (err) {
    setText($("#json-error"), `Could not read ${f.name}: ${err.message}`);
    $("details.advanced").open = true;
  }
});

// ── Run ──────────────────────────────────────────────────────────────
$("#run").addEventListener("click", async () => {
  const btn = $("#run");
  const errBox = $("#run-error");
  setText(errBox, "");
  btn.disabled = true;
  setText(btn, "Checking…");
  try {
    state.result = await call("run", {
      config: JSON.stringify(state.config), name: state.dataset.name, refs: Object.keys(state.refs),
    });
    renderResults(state.result.assessment);
    $("#step-results").hidden = false;
    $("#step-results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    setText(errBox, err.message);
  } finally {
    btn.disabled = false;
    setText(btn, "Run quality check");
  }
});

$("#dl-html").addEventListener("click", () => download(`${state.dataset.name}_quality_report.html`, state.result.html, "text/html"));
$("#dl-json").addEventListener("click", () => download(`${state.dataset.name}_quality.json`, JSON.stringify(state.result.assessment, null, 2), "application/json"));

// ── Results ──────────────────────────────────────────────────────────
function gauge(score, grade) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 120 120");
  svg.setAttribute("class", `gauge ${tone(score)}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Score ${pct(score)}, grade ${grade}`);
  const r = 52;
  const circ = 2 * Math.PI * r;
  const mk = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); svg.append(n); return n; };
  mk("circle", { cx: 60, cy: 60, r, class: "track" });
  mk("circle", { cx: 60, cy: 60, r, class: "arc", "stroke-dasharray": `${circ * score} ${circ}`, transform: "rotate(-90 60 60)" });
  mk("text", { x: 60, y: 60, class: "pct" }).textContent = pct(score);
  mk("text", { x: 60, y: 80, class: "grade" }).textContent = `Grade ${grade}`;
  return svg;
}

function renderResults(a) {
  const s = a.summary;
  const stat = (v, label) => el("div", { class: "stat" }, el("b", {}, v), el("span", {}, label));
  $("#summary").replaceChildren(
    gauge(s.composite_score, s.grade),
    el("div", { class: "stats" },
      stat(s.rows.toLocaleString(), "Rows"),
      stat(s.columns.toLocaleString(), "Columns"),
      stat(`${s.checks_passed}/${s.checks_run}`, "Checks passed"),
      stat(s.critical, "Critical"),
      stat(s.warnings, "Warnings"),
      stat(s.checks_skipped, "Skipped (no rules)")),
  );

  const ordered = [...a.results].sort((x, y) => (x.skipped - y.skipped) || (x.passed - y.passed) || (x.score - y.score));
  $("#findings").replaceChildren(...ordered.map((r) => {
    const t = r.skipped ? "muted" : r.passed ? "good" : tone(r.score);
    const label = r.skipped ? "Skipped" : r.passed ? "Pass" : r.severity === "critical" ? "Critical" : "Warning";
    return el("article", { class: `check ${t}` },
      el("header", {},
        el("h4", {}, titleCase(r.name)),
        el("div", {}, el("span", { class: `pill ${t}` }, label), r.skipped ? null : el("span", { class: "score" }, pct(r.score)))),
      el("p", {}, r.summary),
      r.recommendations.length ? el("ul", {}, r.recommendations.map((x) => el("li", {}, x))) : null);
  }));

  const threshold = a.config.missing_threshold;
  $("#profile tbody").replaceChildren(...a.columns.map((c) => el("tr", {},
    el("th", { scope: "row" }, c.column),
    el("td", {}, el("code", {}, c.dtype)),
    el("td", { class: `num ${c.missing_pct > threshold ? "bad" : ""}` }, pct(c.missing_pct, 1)),
    el("td", { class: "num" }, c.unique.toLocaleString()),
    el("td", {}, "min" in c ? `${c.min} – ${c.max}` : ""),
    el("td", { class: "muted" }, (c.top_values || []).map((t) => `${t.value} (${t.count.toLocaleString()})`).join(", ")))));
}
