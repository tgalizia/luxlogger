(() => {
const pollingInput = document.querySelector("#controller-query");
const fetchState = document.querySelector("#fetch-state");
const connection = document.querySelector("#connection");
const gauge = document.querySelector("#refresh-gauge");
const ring = document.querySelector("#refresh-ring");
const secondsEl = document.querySelector("#refresh-seconds");

const fallbackSeconds = Number(gauge.dataset.refreshSeconds);
let intervalSeconds = Number.isFinite(fallbackSeconds) && fallbackSeconds >= 5 ? fallbackSeconds : 60;
let refreshDueAt = Date.now() + intervalSeconds * 1000;
let refreshTimer = 0;
let pollingBusy = false;
let pollingEnabled = true;

function text(node, value) {
  node.textContent = value;
}

function paintSwitch(on) {
  if (!pollingInput) return;
  pollingInput.checked = on;
  if (fetchState) fetchState.textContent = on ? "On" : "Off";
}

function renderConnection(payload) {
  const polling = payload.polling !== false;
  pollingEnabled = polling;
  if (!pollingBusy) paintSwitch(polling);
  if (!polling) {
    connection.className = "pill pause";
    text(connection, "Paused");
    holdGauge();
    return;
  }
  const connected = Boolean(payload.connected);
  connection.className = connected ? "pill ok" : "pill bad";
  text(connection, payload.demo_mode ? "Demo data" : connected ? "Connected" : "Not connected");
}

function holdGauge() {
  clearTimeout(refreshTimer);
  refreshTimer = 0;
  text(secondsEl, "—");
  ring.style.strokeDashoffset = "100";
  gauge.setAttribute("aria-label", "Data fetching is paused");
}

function paintGauge() {
  if (!pollingEnabled) return;
  const remaining = Math.max(0, refreshDueAt - Date.now());
  const seconds = Math.ceil(remaining / 1000);
  const fraction = Math.min(1, remaining / (intervalSeconds * 1000));
  text(secondsEl, String(seconds));
  ring.style.strokeDashoffset = String(100 * (1 - fraction));
  gauge.setAttribute("aria-label", `Next read in ${seconds} seconds`);
}

function applySchedule(payload) {
  const seconds = Number(payload.poll_interval_seconds);
  if (Number.isFinite(seconds) && seconds >= 5) intervalSeconds = seconds;
  const due = Date.parse(payload.next_poll_at || "");
  if (Number.isFinite(due)) refreshDueAt = due;
}

async function fetchStatus() {
  const response = await fetch("/api/status");
  if (!response.ok) {
    connection.className = "pill bad";
    text(connection, "Not connected");
    return null;
  }
  const payload = await response.json();
  renderConnection(payload);
  applySchedule(payload);
  return payload;
}

function arm() {
  clearTimeout(refreshTimer);
  if (!pollingEnabled) {
    holdGauge();
    return;
  }
  if (refreshDueAt <= Date.now()) refreshDueAt = Date.now() + intervalSeconds * 1000;
  paintGauge();
  refreshTimer = setTimeout(onDue, Math.max(0, refreshDueAt - Date.now()));
}

async function onDue() {
  if (!pollingEnabled) {
    holdGauge();
    return;
  }
  const dueAt = refreshDueAt;
  const started = Date.now();
  while (Date.now() - started < 20000) {
    if (!pollingEnabled) {
      holdGauge();
      return;
    }
    const payload = await fetchStatus();
    if (!pollingEnabled || !payload || payload.polling === false) {
      holdGauge();
      return;
    }
    const upcoming = Date.parse(payload.next_poll_at || "");
    if (Number.isFinite(upcoming) && upcoming > dueAt + 1000) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  if (!pollingEnabled) {
    holdGauge();
    return;
  }
  window.dispatchEvent(new CustomEvent("controller-tick"));
  arm();
}

pollingInput?.addEventListener("change", async () => {
  const enabled = pollingInput.checked;
  pollingBusy = true;
  pollingInput.disabled = true;
  if (fetchState) fetchState.textContent = enabled ? "On" : "Off";
  try {
    const response = await fetch("/api/polling", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      paintSwitch(!enabled);
      return;
    }
    renderConnection(body);
    window.dispatchEvent(new CustomEvent("controller-polling", { detail: body }));
    if (body.polling !== false) {
      applySchedule(body);
      window.dispatchEvent(new CustomEvent("controller-tick"));
      arm();
    }
  } finally {
    pollingBusy = false;
    pollingInput.disabled = false;
  }
});

fetchStatus().finally(arm);
setInterval(paintGauge, 100);
})();
