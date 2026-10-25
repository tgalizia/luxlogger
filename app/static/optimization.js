const adviceUrl = "/api/advice";

const fields = {
  adviceBody: document.querySelector("#advice-body"),
  adviceMeta: document.querySelector("#advice-meta"),
  findings: document.querySelector("#findings"),
  dataWindow: document.querySelector("#data-window"),
};

const pumpTable = mountPumpTable(document.querySelector("#pump-table"), { editable: false });

const adviceButton = document.querySelector("#advice-button");
const adviceNote = document.querySelector("#advice-note");
let advicePending = false;

const RANGE_LABELS = {
  hour: "Last hour",
  day: "Last 24 hours",
  week: "Last 7 days",
  month: "Last 30 days",
  year: "Last year",
};
let adviceRange = "day";
let lastPreset = "day";

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

function windowText(findings) {
  if (!findings) return "";
  const start = formatWhen(findings.window_start);
  const end = formatWhen(findings.window_end);
  if (start && end) return `${start} – ${end}`;
  return start || end;
}

function selectionLabel() {
  if (adviceRange !== "custom") return RANGE_LABELS[adviceRange];
  const span = selectedWindow();
  if (!span) return "Custom";
  const startText = formatDay(span.start);
  const endText = formatDay(new Date(span.end.getTime() - 1));
  return startText === endText ? startText : `${startText} – ${endText}`;
}

function describeSelection(findings) {
  const span = windowText(findings);
  const count = findings && !missing(findings.sample_count) ? `${findings.sample_count} samples` : "";
  return [selectionLabel(), span, count].filter(Boolean).join(" · ");
}

function renderFindings(findings) {
  fields.findings.replaceChildren();
  if (!findings) {
    fields.dataWindow.textContent = selectionLabel();
    return;
  }
  fields.dataWindow.textContent = describeSelection(findings);
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

function renderSuggestion(report, message) {
  if (report && report.suggestion) {
    const paragraphs = report.suggestion.split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);
    fields.adviceBody.replaceChildren();
    for (const part of paragraphs) {
      const paragraph = document.createElement("p");
      paragraph.textContent = part;
      fields.adviceBody.append(paragraph);
    }
    const when = formatWhen(report.created_at);
    fields.adviceMeta.textContent = [windowText(report.findings), report.provider, report.model, when]
      .filter(Boolean)
      .join(" · ");
    fields.adviceMeta.hidden = false;
    return;
  }
  showStatus(message || "Ask a question after a few samples have been stored.");
}

function renderAdvice(report, message, paintFindings) {
  if (paintFindings && report && report.findings) renderFindings(report.findings);
  renderSuggestion(report, message);
}

let previewToken = 0;

async function refreshPreview(options) {
  const quiet = options && options.quiet;
  const token = ++previewToken;
  const query = analysisQuery();
  if (!query) {
    fields.findings.replaceChildren();
    fields.dataWindow.textContent = "Choose a start date and an end date after it.";
    return;
  }
  if (!quiet) {
    fields.findings.replaceChildren();
    fields.dataWindow.textContent = `Reading ${periodPhrase()}…`;
  }
  const response = await fetch(`/api/diagnostics?${query}`);
  if (token !== previewToken) return;
  if (!response.ok) {
    const error = await readError(response);
    if (token !== previewToken) return;
    fields.findings.replaceChildren();
    fields.dataWindow.textContent = `${selectionLabel()} · ${error.message}`;
    return;
  }
  const findings = await response.json();
  if (token !== previewToken) return;
  renderFindings(findings);
}

async function loadLatest() {
  if (advicePending) return;
  const response = await fetch("/api/advice/latest");
  if (!response.ok) return;
  const payload = await response.json();
  if (payload.report) renderSuggestion(payload.report);
}

function dateInputValue(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function parseDateInput(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  date.setHours(0, 0, 0, 0);
  if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) return null;
  return date;
}

function presetWindow(range) {
  const end = new Date();
  const start = new Date(end);
  if (range === "hour") start.setTime(end.getTime() - 60 * 60 * 1000);
  else if (range === "week") start.setDate(start.getDate() - 7);
  else if (range === "month") start.setDate(start.getDate() - 30);
  else if (range === "year") start.setFullYear(start.getFullYear() - 1);
  else start.setTime(end.getTime() - 24 * 60 * 60 * 1000);
  return { start, end };
}

function customWindow() {
  const start = parseDateInput(document.querySelector("#advice-range-start").value);
  const endDay = parseDateInput(document.querySelector("#advice-range-end").value);
  if (!start || !endDay || endDay < start) return null;
  const end = new Date(endDay);
  end.setDate(end.getDate() + 1);
  return { start, end };
}

function selectedWindow() {
  if (adviceRange === "custom") return customWindow();
  return presetWindow(adviceRange);
}

function formatDay(date) {
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

function periodPhrase() {
  if (adviceRange !== "custom") {
    const label = RANGE_LABELS[adviceRange];
    return `the ${label.charAt(0).toLowerCase()}${label.slice(1)}`;
  }
  const span = selectedWindow();
  if (!span) return "";
  const startText = formatDay(span.start);
  const endText = formatDay(new Date(span.end.getTime() - 1));
  return startText === endText ? startText : `${startText} – ${endText}`;
}

function analysisQuery() {
  const span = selectedWindow();
  if (!span) return null;
  const since = encodeURIComponent(span.start.toISOString());
  const until = encodeURIComponent(span.end.toISOString());
  return `since=${since}&until=${until}`;
}

function press(buttons, selected) {
  buttons.forEach((item) => {
    const active = item === selected;
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function seedCustomDates() {
  const span = presetWindow(lastPreset);
  document.querySelector("#advice-range-start").value = dateInputValue(span.start);
  document.querySelector("#advice-range-end").value = dateInputValue(new Date(span.end.getTime() - 1));
}

function setCustomOpen(open) {
  const panel = document.querySelector("#advice-custom-range");
  const button = document.querySelector('[data-range="custom"]');
  panel.hidden = !open;
  button.setAttribute("aria-expanded", open ? "true" : "false");
}

document.querySelectorAll("[data-range]").forEach((button) => {
  button.addEventListener("click", () => {
    const range = button.dataset.range;
    if (range !== "custom" && !RANGE_LABELS[range]) return;
    if (range === "custom") {
      const already = adviceRange === "custom";
      if (!already) seedCustomDates();
      adviceRange = "custom";
      press(document.querySelectorAll("[data-range]"), button);
      setCustomOpen(already ? document.querySelector("#advice-custom-range").hidden : true);
      refreshPreview();
      return;
    }
    lastPreset = range;
    adviceRange = range;
    press(document.querySelectorAll("[data-range]"), button);
    setCustomOpen(false);
    refreshPreview();
  });
});

document.addEventListener("click", (event) => {
  if (!document.querySelector(".custom-picker").contains(event.target)) setCustomOpen(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setCustomOpen(false);
});

document.querySelectorAll("#advice-range-start, #advice-range-end").forEach((input) => {
  input.addEventListener("change", () => {
    adviceRange = "custom";
    press(document.querySelectorAll("[data-range]"), document.querySelector('[data-range="custom"]'));
    refreshPreview();
  });
});

const earliestAdvice = new Date();
earliestAdvice.setDate(earliestAdvice.getDate() - 799);
document.querySelectorAll("#advice-range-start, #advice-range-end").forEach((input) => {
  input.min = dateInputValue(earliestAdvice);
  input.max = dateInputValue(new Date());
});

function fileStamp(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}_${hours}${minutes}`;
}

function downloadName(span) {
  return `luxlogger-${fileStamp(span.start)}_${fileStamp(span.end)}.json`;
}

const downloadButton = document.querySelector("#download-data");

downloadButton.addEventListener("click", async () => {
  const span = selectedWindow();
  const query = analysisQuery();
  if (!query || !span) {
    fields.dataWindow.textContent = "Choose a start date and an end date after it.";
    return;
  }
  downloadButton.disabled = true;
  try {
    const response = await fetch(`/api/period-data?${query}`);
    if (!response.ok) {
      const error = await readError(response);
      fields.dataWindow.textContent = `${selectionLabel()} · ${error.message}`;
      return;
    }
    const payload = await response.json();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = downloadName(span);
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  } finally {
    downloadButton.disabled = false;
  }
});

adviceButton.addEventListener("click", async () => {
  const query = analysisQuery();
  if (!query) {
    showStatus("Choose a start date and an end date after it.");
    return;
  }
  const sentToken = previewToken;
  advicePending = true;
  adviceButton.disabled = true;
  showStatus(`Reading ${periodPhrase()}…`);
  try {
    const response = await fetch(`${adviceUrl}?${query}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: adviceNote.value }),
    });
    if (!response.ok) {
      const error = await readError(response);
      renderAdvice(
        error.findings ? { findings: error.findings, suggestion: "" } : null,
        error.message,
        sentToken === previewToken,
      );
      if (error.findings) showStatus(error.message);
      return;
    }
    renderAdvice(await response.json(), undefined, sentToken === previewToken);
  } finally {
    advicePending = false;
    adviceButton.disabled = false;
  }
});

const suggestButton = document.querySelector("#suggest-button");
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
  const query = analysisQuery();
  if (!query) {
    changesEl.replaceChildren();
    changesStatus.textContent = "Choose a start date and an end date after it.";
    return;
  }
  suggestButton.disabled = true;
  changesEl.replaceChildren();
  changesStatus.textContent = `Looking at ${periodPhrase()}…`;
  try {
    const response = await fetch(`/api/settings/suggest?${query}`, { method: "POST" });
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
  refreshPreview({ quiet: true });
  pumpTable.load();
});

window.addEventListener("controller-polling", (event) => {
  if (event.detail && event.detail.polling !== false) pumpTable.load();
});

pumpTable.load();
loadLatest();
refreshPreview();
