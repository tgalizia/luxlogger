const statusEl = document.querySelector("#status");
const dialog = document.querySelector("#confirm-dialog");
const confirmText = document.querySelector("#confirm-text");
const confirmOk = document.querySelector("#confirm-ok");
const confirmCancel = document.querySelector("#confirm-cancel");

const table = mountPumpTable(document.querySelector("#pump-table"), {
  editable: true,
  announce: false,
  onSet(setting, nextValue) {
    openConfirm(setting, nextValue);
  },
});

let pending = null;
let sending = false;
let loading = false;

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

function openConfirm(setting, nextValue) {
  if (sending) return;
  pending = {
    id: setting.id,
    value: nextValue,
    label: setting.label,
    from: setting.display || display(setting, setting.value),
    to: display(setting, nextValue),
  };
  confirmText.textContent = `Change ${pending.label} from ${pending.from} to ${pending.to}?`;
  confirmOk.disabled = false;
  dialog.showModal();
}

async function load() {
  if (loading || sending) return;
  loading = true;
  try {
    const statusResponse = await fetch("/api/status");
    const statusBody = await statusResponse.json().catch(() => ({}));
    const polling = statusResponse.ok && statusBody.polling !== false;
    if (!polling) {
      statusEl.textContent = "Data fetching is off.";
      return;
    }
    const result = await table.load();
    if (!result.ok) {
      statusEl.textContent = result.message;
      return;
    }
    statusEl.textContent = result.demo
      ? "Demo data has no live settings. Nothing is sent to a controller."
      : "";
  } finally {
    loading = false;
  }
}

window.addEventListener("controller-polling", async (event) => {
  if (event.detail.polling === false) {
    statusEl.textContent = "Data fetching is off.";
    return;
  }
  await load();
});

window.addEventListener("controller-tick", () => {
  load();
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
        from_suggestion: false,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      statusEl.textContent = detailMessage(payload);
      return;
    }
    pending = null;
    dialog.close();
    table.updateSetting(payload.setting);
    statusEl.textContent = payload.changed
      ? `${payload.setting.label} is now ${payload.setting.display}.`
      : `${payload.setting.label} was already ${payload.setting.display}.`;
  } finally {
    sending = false;
    confirmOk.disabled = false;
    confirmCancel.disabled = false;
  }
});

load();
