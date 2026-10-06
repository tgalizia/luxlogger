const modesEl = document.querySelector("#modes");
const rowsEl = document.querySelector("#rows");
const statusEl = document.querySelector("#status");
const suggestButton = document.querySelector("#suggest");
const dialog = document.querySelector("#confirm-dialog");
const confirmText = document.querySelector("#confirm-text");
const confirmOk = document.querySelector("#confirm-ok");
const confirmCancel = document.querySelector("#confirm-cancel");

let settings = [];
let suggestions = null;
let pending = null;
let sending = false;

function detailMessage(body) {
  if (body && typeof body.detail === "string") return body.detail;
  if (body && body.detail && body.detail.message) return body.detail.message;
  return "Request failed.";
}

function optionLabel(setting, value) {
  const labels = setting.option_labels || {};
  return labels[value] || String(value);
}

function display(setting, value) {
  if (setting.kind === "number") {
    const number = new Intl.NumberFormat("de-DE", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      useGrouping: false,
    }).format(Number(value));
    return setting.unit ? `${number} ${setting.unit}` : number;
  }
  return optionLabel(setting, value);
}

function suggestionFor(id) {
  if (!suggestions) return null;
  return suggestions[id] || null;
}

const MODE_IDS = ["ID_Ba_Hz_akt", "ID_Ba_Bw_akt"];

function renderModes() {
  const chosen = {};
  for (const select of modesEl.querySelectorAll("select")) {
    chosen[select.dataset.id] = select.value;
  }
  modesEl.replaceChildren();
  const modes = settings.filter((setting) => MODE_IDS.includes(setting.id));
  if (!modes.length) return;

  for (const setting of modes) {
    const article = document.createElement("article");
    article.className = "card";
    const title = document.createElement("h2");
    title.id = `mode-title-${setting.id}`;
    title.textContent = setting.label;
    const control = document.createElement("div");
    control.className = "control";
    const select = document.createElement("select");
    select.id = `mode-${setting.id}`;
    select.dataset.id = setting.id;
    select.setAttribute("aria-labelledby", title.id);
    const currentValue = String(setting.value);
    const options = setting.options ? [...setting.options] : [];
    if (currentValue && !options.includes(currentValue)) options.unshift(currentValue);
    for (const option of options) {
      const item = document.createElement("option");
      item.value = option;
      item.textContent = optionLabel(setting, option);
      if (!setting.options || !setting.options.includes(option)) item.disabled = true;
      select.append(item);
    }
    const preferred = chosen[setting.id];
    select.value = preferred && [...select.options].some((item) => item.value === preferred)
      ? preferred
      : currentValue;

    const set = document.createElement("button");
    set.type = "button";
    set.textContent = "Set";
    const refresh = () => {
      set.disabled = select.value === currentValue;
    };
    select.addEventListener("change", refresh);
    set.addEventListener("click", () => openConfirm(setting, select.value, false));
    refresh();
    control.append(select, set);
    article.append(title, control);
    modesEl.append(article);
  }
}

function render() {
  renderModes();
  rowsEl.replaceChildren();
  for (const setting of settings) {
    const suggestion = suggestionFor(setting.id);
    const article = document.createElement("article");
    article.className = "card";
    const row = document.createElement("div");
    row.className = "row";

    const copy = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = setting.label;
    const currentLabel = document.createElement("div");
    currentLabel.className = "label";
    currentLabel.textContent = "Current";
    const current = document.createElement("div");
    current.className = "value";
    current.textContent = setting.display || display(setting, setting.value);
    const suggestionLabel = document.createElement("div");
    suggestionLabel.className = "label";
    suggestionLabel.textContent = "Suggestion";
    const suggested = document.createElement("div");
    suggested.className = "value";
    suggested.textContent = suggestion ? display(setting, suggestion.value) : "No change";
    copy.append(title, currentLabel, current, suggestionLabel, suggested);

    if (suggestion && suggestion.reason) {
      const reason = document.createElement("p");
      reason.className = "reason";
      reason.textContent = suggestion.reason;
      copy.append(reason);
    }

    row.append(copy);
    if (suggestion) {
      const apply = document.createElement("button");
      apply.type = "button";
      apply.textContent = "Apply";
      apply.addEventListener("click", () => openConfirm(setting, suggestion.value, true));
      row.append(apply);
    }
    article.append(row);
    rowsEl.append(article);
  }
}

function openConfirm(setting, nextValue, fromSuggestion) {
  if (sending) return;
  pending = {
    id: setting.id,
    value: nextValue,
    fromSuggestion: fromSuggestion,
    label: setting.label,
    from: setting.display || display(setting, setting.value),
    to: display(setting, nextValue),
  };
  confirmText.textContent = `Change ${pending.label} from ${pending.from} to ${pending.to}?`;
  confirmOk.disabled = false;
  dialog.showModal();
}

async function load() {
  const statusResponse = await fetch("/api/status");
  const statusBody = await statusResponse.json().catch(() => ({}));
  const polling = statusResponse.ok && statusBody.polling !== false;
  if (!polling) {
    statusEl.textContent = "Controller queries are paused.";
    return;
  }
  const response = await fetch("/api/settings");
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    statusEl.textContent = detailMessage(body);
    return;
  }
  settings = body.settings;
  statusEl.textContent = "Nothing is changed until you confirm one setting.";
  render();
}

window.addEventListener("controller-polling", async (event) => {
  if (event.detail.polling === false) {
    statusEl.textContent = "Controller queries are paused.";
    return;
  }
  await load();
});

suggestButton.addEventListener("click", async () => {
  suggestButton.disabled = true;
  statusEl.textContent = "Looking at the last 24 hours…";
  try {
    const response = await fetch("/api/settings/suggest", { method: "POST" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      statusEl.textContent = detailMessage(body);
      return;
    }
    settings = body.settings;
    suggestions = {};
    for (const change of body.changes) suggestions[change.id] = change;
    const count = body.changes.length;
    statusEl.textContent = count === 0
      ? "No changes suggested. Every setting stays as it is."
      : "Review each suggestion. Nothing is sent until you confirm it.";
    render();
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
        from_suggestion: body.fromSuggestion,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      statusEl.textContent = detailMessage(payload);
      return;
    }
    pending = null;
    dialog.close();
    settings = settings.map((setting) => setting.id === payload.setting.id ? payload.setting : setting);
    if (suggestions) delete suggestions[payload.setting.id];
    statusEl.textContent = payload.changed
      ? `${payload.setting.label} is now ${payload.setting.display}.`
      : `${payload.setting.label} was already ${payload.setting.display}.`;
    render();
  } finally {
    sending = false;
    confirmOk.disabled = false;
    confirmCancel.disabled = false;
  }
});

load();
