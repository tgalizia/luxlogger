const adviceUrl = "/api/advice";

const fields = {
  adviceBody: document.querySelector("#advice-body"),
  adviceMeta: document.querySelector("#advice-meta"),
  findings: document.querySelector("#findings"),
};

const pumpTable = mountPumpTable(document.querySelector("#pump-table"), { editable: false });

const adviceButton = document.querySelector("#advice-button");
const adviceNote = document.querySelector("#advice-note");
let advicePending = false;

function missing(value) {
  return value === null || value === undefined || value === "";
}

const DISPLAY_LOCALE = "de-DE";

function formatNumber(value, digits, unit) {
  if (missing(value)) return "—";
  const formatted = new Intl.NumberFormat(DISPLAY_LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  }).format(Number(value));
  return `${formatted}${unit}`;
}

function formatDuration(seconds) {
  if (missing(seconds)) return "—";
  const total = Math.round(Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.round((total % 3600) / 60);
  if (hours <= 0) return `${minutes} min`;
  return `${hours} h ${minutes} min`;
}

function formatWhen(iso) {
  if (!iso) return "";
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso));
}

async function readError(response) {
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  if (typeof detail === "string") return { message: detail, findings: null };
  if (detail && typeof detail === "object") {
    return { message: detail.message || "Request failed", findings: detail.findings || null };
  }
  return { message: response.statusText || "Request failed", findings: null };
}

function renderFindings(findings) {
  fields.findings.replaceChildren();
  if (!findings) return;
  const rows = [
    ["Samples", findings.sample_count],
    ["Compressor starts", findings.compressor_starts],
    ["Short cycles", `${findings.short_cycles} of ${findings.completed_cycles}`],
    ["Compressor on", formatDuration(findings.compressor_on_time_s)],
    ["Backup heater", formatDuration(findings.backup_heater_on_time_s)],
    ["Flow − return", formatNumber(findings.mean_flow_return_delta_c, 1, " °C")],
    ["Return vs setpoint", formatNumber(findings.mean_return_minus_setpoint_c, 1, " °C")],
  ];
  for (const [label, value] of rows) {
    const item = document.createElement("div");
    item.className = "stat";
    const name = document.createElement("span");
    name.className = "stat-label";
    name.textContent = label;
    const number = document.createElement("strong");
    number.className = "stat-value";
    number.textContent = missing(value) ? "—" : String(value);
    item.append(name, number);
    fields.findings.append(item);
  }
}

function showStatus(message) {
  fields.adviceBody.replaceChildren();
  const paragraph = document.createElement("p");
  paragraph.className = "advice-status";
  paragraph.textContent = message;
  fields.adviceBody.append(paragraph);
  fields.adviceMeta.hidden = true;
  fields.adviceMeta.textContent = "";
}

function renderAdvice(report, message) {
  renderFindings(report && report.findings);
  if (report && report.suggestion) {
    const paragraphs = report.suggestion.split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);
    fields.adviceBody.replaceChildren();
    for (const part of paragraphs) {
      const paragraph = document.createElement("p");
      paragraph.textContent = part;
      fields.adviceBody.append(paragraph);
    }
    const when = formatWhen(report.created_at);
    fields.adviceMeta.textContent = [report.provider, report.model, when].filter(Boolean).join(" · ");
    fields.adviceMeta.hidden = false;
    return;
  }
  showStatus(message || "Ask for a suggestion after a few samples have been stored.");
}

async function loadLatest() {
  if (advicePending) return;
  const response = await fetch("/api/advice/latest");
  if (!response.ok) return;
  const payload = await response.json();
  if (payload.report) renderAdvice(payload.report);
}

adviceButton.addEventListener("click", async () => {
  advicePending = true;
  adviceButton.disabled = true;
  showStatus("Reading the last day of samples…");
  try {
    const response = await fetch(adviceUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: adviceNote.value }),
    });
    if (!response.ok) {
      const error = await readError(response);
      renderAdvice(error.findings ? { findings: error.findings, suggestion: "" } : null, error.message);
      if (error.findings) showStatus(error.message);
      return;
    }
    renderAdvice(await response.json());
  } finally {
    advicePending = false;
    adviceButton.disabled = false;
  }
});

const suggestButton = document.querySelector("#suggest-button");
const changesSection = document.querySelector("#setting-changes");
const changesEl = document.querySelector("#changes");
const changesStatus = document.querySelector("#changes-status");
const dialog = document.querySelector("#confirm-dialog");
const confirmText = document.querySelector("#confirm-text");
const confirmOk = document.querySelector("#confirm-ok");
const confirmCancel = document.querySelector("#confirm-cancel");

let proposed = [];
let currentSettings = [];
let pending = null;
let sending = false;

function detailMessage(body) {
  if (body && typeof body.detail === "string") return body.detail;
  if (body && body.detail && body.detail.message) return body.detail.message;
  return "Request failed.";
}

function displayValue(setting, value) {
  if (!setting) return String(value);
  if (setting.kind === "number") {
    const number = new Intl.NumberFormat(DISPLAY_LOCALE, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      useGrouping: false,
    }).format(Number(value));
    return setting.unit ? `${number} ${setting.unit}` : number;
  }
  const labels = setting.option_labels || {};
  return labels[value] || String(value);
}

function renderChanges() {
  changesSection.hidden = false;
  changesEl.replaceChildren();
  const byId = Object.fromEntries(currentSettings.map((setting) => [setting.id, setting]));
  for (const change of proposed) {
    const setting = byId[change.id];
    if (!setting) continue;
    const item = document.createElement("div");
    item.className = "change";
    const copy = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = setting.label;
    const value = document.createElement("div");
    value.className = "value";
    const from = setting.display || displayValue(setting, setting.value);
    const to = displayValue(setting, change.value);
    value.textContent = `${from} → ${to}`;
    copy.append(title, value);
    if (change.reason) {
      const reason = document.createElement("p");
      reason.className = "reason";
      reason.textContent = change.reason;
      copy.append(reason);
    }
    const apply = document.createElement("button");
    apply.type = "button";
    apply.textContent = "Apply";
    apply.addEventListener("click", () => openConfirm(setting, change.value, from, to));
    item.append(copy, apply);
    changesEl.append(item);
  }
}

function openConfirm(setting, nextValue, from, to) {
  if (sending) return;
  pending = { id: setting.id, value: nextValue, label: setting.label, from, to };
  confirmText.textContent = `Change ${pending.label} from ${pending.from} to ${pending.to}?`;
  confirmOk.disabled = false;
  dialog.showModal();
}

suggestButton.addEventListener("click", async () => {
  suggestButton.disabled = true;
  changesSection.hidden = false;
  changesEl.replaceChildren();
  changesStatus.textContent = "Looking at the last 24 hours…";
  try {
    const response = await fetch("/api/settings/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: adviceNote.value }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      changesStatus.textContent = detailMessage(body);
      return;
    }
    currentSettings = body.settings || [];
    pumpTable.setSettings(currentSettings);
    proposed = body.changes || [];
    changesStatus.textContent = proposed.length
      ? "Review each suggestion. Nothing is sent until you confirm it."
      : "No changes suggested. Every setting stays as it is.";
    renderChanges();
  } finally {
    suggestButton.disabled = false;
  }
});

confirmCancel.addEventListener("click", () => {
  pending = null;
  dialog.close();
});

dialog.addEventListener("cancel", () => {
  pending = null;
});

confirmOk.addEventListener("click", async () => {
  if (!pending || sending) return;
  const body = pending;
  sending = true;
  confirmOk.disabled = true;
  confirmCancel.disabled = true;
  try {
    const response = await fetch("/api/settings/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: body.id,
        value: body.value,
        from_suggestion: true,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      changesStatus.textContent = detailMessage(payload);
      return;
    }
    pending = null;
    dialog.close();
    currentSettings = currentSettings.map((setting) =>
      setting.id === payload.setting.id ? payload.setting : setting,
    );
    pumpTable.updateSetting(payload.setting);
    proposed = proposed.filter((change) => change.id !== payload.setting.id);
    changesStatus.textContent = payload.changed
      ? `${payload.setting.label} is now ${payload.setting.display}.`
      : `${payload.setting.label} was already ${payload.setting.display}.`;
    if (proposed.length) {
      changesStatus.textContent += " Review the remaining suggestions. Nothing else is sent until you confirm it.";
    }
    renderChanges();
  } finally {
    sending = false;
    confirmOk.disabled = false;
    confirmCancel.disabled = false;
  }
});

window.addEventListener("controller-tick", () => {
  loadLatest();
  pumpTable.load();
});

window.addEventListener("controller-polling", (event) => {
  if (event.detail && event.detail.polling !== false) pumpTable.load();
});

pumpTable.load();
loadLatest();
