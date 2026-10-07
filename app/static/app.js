const statusUrl = "/api/status";
const indoorUrl = "/api/indoor";

const RANGES = {
  hour: { unit: "minute", empty: "No samples in the last hour yet." },
  day: { unit: "hour", empty: "No samples in the last 24 hours yet." },
  week: { unit: "day", empty: "No samples this week yet." },
  month: { unit: "day", empty: "No samples this month yet." },
  year: { unit: "month", empty: "No samples this year yet." },
};
let chartRange = "day";

const fields = {
  connectionDetail: document.querySelector("#connection-detail"),
  modeBadges: document.querySelector("#mode-badges"),
  circuitLabel: document.querySelector("#circuit-label"),
  flow: document.querySelector("#flow"),
  returnTemp: document.querySelector("#return-temp"),
  actualTemp: document.querySelector("#actual-temp"),
  targetTemp: document.querySelector("#target-temp"),
  outdoor: document.querySelector("#outdoor"),
  compressor: document.querySelector("#compressor"),
  heater: document.querySelector("#heater"),
  chartMessage: document.querySelector("#chart-message"),
  energyNote: document.querySelector("#energy-note"),
  energyPeriod: document.querySelector("#energy-period"),
  energyMeter: document.querySelector("#energy-meter"),
  formMessage: document.querySelector("#form-message"),
};

const indoorForm = document.querySelector("#indoor-form");
let heatingChart;
let hotWaterChart;
let devicesChart;

function text(node, value) {
  node.textContent = value;
}

function missing(value) {
  return value === null || value === undefined || value === "";
}

const DISPLAY_LOCALE = "de-DE";
if (typeof Chart !== "undefined") Chart.defaults.locale = DISPLAY_LOCALE;

function formatNumber(value, digits, unit) {
  if (missing(value)) return "—";
  const text = new Intl.NumberFormat(DISPLAY_LOCALE, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
    useGrouping: false,
  }).format(Number(value));
  return `${text}${unit}`;
}

function formatWhen(iso) {
  if (!iso) return "No successful read yet";
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(iso));
}

const TIME_SCALE = {
  tooltipFormat: "dd.MM.yyyy HH:mm",
  displayFormats: {
    millisecond: "HH:mm:ss",
    second: "HH:mm:ss",
    minute: "HH:mm",
    hour: "HH:mm",
    day: "dd.MM",
    week: "dd.MM",
    month: "MM.yyyy",
    quarter: "MM.yyyy",
    year: "yyyy",
  },
};

async function readError(response) {
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  if (typeof detail === "string") return { message: detail, findings: null };
  if (detail && typeof detail === "object") {
    return { message: detail.message || "Request failed", findings: detail.findings || null };
  }
  return { message: response.statusText || "Request failed", findings: null };
}

function renderModeBadges(latest) {
  const badges = latest && latest.mode_badges;
  if (!badges) return;
  fields.modeBadges.setAttribute("aria-label", latest.mode_text || "Mode");
  fields.modeBadges.replaceChildren();
  for (const badge of badges) {
    const item = document.createElement("span");
    item.className = badge.on ? "badge on" : "badge";
    item.dataset.tone = badge.tone;
    item.setAttribute("role", "listitem");
    if (badge.on) item.setAttribute("aria-current", "true");
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("aria-hidden", "true");
    item.append(dot, document.createTextNode(badgeLabel(badge, latest)));
    fields.modeBadges.append(item);
  }
}

function badgeLabel(badge, latest) {
  if (badge.id !== "pump" || !badge.on) return badge.label;
  if (missing(latest.return_temp) || missing(latest.return_setpoint)) return badge.label;
  const current = formatNumber(latest.return_temp, 1, "");
  const target = formatNumber(latest.return_setpoint, 1, " °C");
  return `${badge.label} ${current} → ${target}`;
}

let pollingGeneration = 0;

function renderStatus(payload) {
  const latest = payload.latest;
  const polling = payload.polling !== false;
  if (!polling) {
    const when = payload.last_success_at
      ? `Last read ${formatWhen(payload.last_success_at)}.`
      : "No successful read yet.";
    text(fields.connectionDetail, `Data fetching is off. ${when}`);
  } else {
    const detail = payload.last_error
      ? payload.last_error
      : `Last read ${formatWhen(payload.last_success_at)}`;
    text(fields.connectionDetail, detail);
  }
  renderModeBadges(latest);
  const hotWater = Boolean(latest) && latest.operating_mode === "hot water";
  text(fields.circuitLabel, hotWater ? "Hot water" : "Heating");
  text(fields.flow, formatNumber(latest && latest.flow_temp, 1, " °C"));
  text(fields.returnTemp, formatNumber(latest && latest.return_temp, 1, " °C"));
  text(fields.actualTemp, formatNumber(latest && (hotWater ? latest.dhw_temp : latest.return_temp), 1, " °C"));
  text(
    fields.targetTemp,
    formatNumber(latest && (hotWater ? latest.dhw_setpoint : latest.return_setpoint), 1, " °C"),
  );
  text(fields.outdoor, formatNumber(latest && latest.outdoor_temp, 1, " °C"));
  renderSwitch(fields.compressor, latest ? Boolean(latest.compressor_running) : null);
  renderSwitch(fields.heater, latest ? extraHeaterOn(latest) : null);
}

function renderSwitch(node, on) {
  if (on === null) {
    node.className = "state";
    text(node, "—");
    return;
  }
  node.className = on ? "badge on state on" : "badge on state off";
  text(node, on ? "On" : "Off");
}

const seriesColors = {
  "Heating Flow": "#dc2626",
  "Heating Return": "#7c3aed",
  "Temperature Outdoor": "#2563eb",
  "Hot water": "#e11d48",
  "Temperature Indoor": "#059669",
};

const HEATING_SCALE = { min: 18, max: 28 };
const HOT_WATER_SCALE = { min: 38, max: 48 };
const OUTDOOR_SCALE = { min: 5, max: 20 };
const MIN_TEMP_SPAN = 4;

function hotWaterCircuit(sample) {
  return sample.operating_mode === "hot water";
}

function series(label, samples, key, accept = () => true, yAxisID = "y") {
  const color = seriesColors[label];
  return {
    label,
    yAxisID,
    data: samples
      .filter((sample) => accept(sample) && !missing(sample[key]))
      .map((sample) => ({ x: sample.recorded_at, y: sample[key] })),
    borderColor: color,
    backgroundColor: color,
    pointRadius: 0,
    borderWidth: 3,
    tension: 0.2,
  };
}

function circuitSeries(name, samples, key, hotWater) {
  const label = hotWater ? `${name}, hot water` : `Heating ${name}`;
  const heating = (sample) => !hotWaterCircuit(sample);
  return series(label, samples, key, hotWater ? hotWaterCircuit : heating);
}

function legendOptions() {
  return {
    position: "bottom",
    labels: {
      usePointStyle: true,
      pointStyle: "rect",
      boxWidth: 28,
      boxHeight: 12,
      padding: 18,
      color: "#1c1917",
      font: { size: 13 },
    },
    onClick(_event, item, legend) {
      const index = item.datasetIndex;
      const visible = legend.chart.isDatasetVisible(index);
      legend.chart.setDatasetVisibility(index, !visible);
      legend.chart.update();
    },
    onHover(event) {
      if (event.native && event.native.target) event.native.target.style.cursor = "pointer";
    },
    onLeave(event) {
      if (event.native && event.native.target) event.native.target.style.cursor = "default";
    },
  };
}

function hiddenLabels(existing) {
  if (!existing) return new Set();
  return new Set(
    existing.data.datasets
      .filter((_, index) => !existing.isDatasetVisible(index))
      .map((dataset) => dataset.label),
  );
}

function withHidden(datasets, hidden) {
  datasets.forEach((dataset) => {
    if (hidden.has(dataset.label)) dataset.hidden = true;
  });
  return datasets;
}

function chartWindow(range) {
  const end = new Date();
  const start = new Date(end);
  if (range === "hour") start.setTime(end.getTime() - 60 * 60 * 1000);
  else if (range === "week") {
    const daysSinceMonday = (start.getDay() + 6) % 7;
    start.setDate(start.getDate() - daysSinceMonday);
    start.setHours(0, 0, 0, 0);
  } else if (range === "month") {
    start.setDate(1);
    start.setHours(0, 0, 0, 0);
  } else if (range === "year") {
    start.setMonth(0, 1);
    start.setHours(0, 0, 0, 0);
  } else start.setTime(end.getTime() - 24 * 60 * 60 * 1000);
  return { start, end };
}

function timeAxis(range, window) {
  return {
    type: "time",
    min: window.start.toISOString(),
    max: window.end.toISOString(),
    time: { ...TIME_SCALE, unit: RANGES[range].unit },
    ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
  };
}

function temperatureBounds(datasets) {
  const values = datasets.flatMap((dataset) =>
    dataset.data.map((point) => point.y).filter((value) => !missing(value)),
  );
  if (!values.length) return null;
  let low = Math.min(...values);
  let high = Math.max(...values);
  if (high - low < MIN_TEMP_SPAN) {
    const mid = (low + high) / 2;
    low = mid - MIN_TEMP_SPAN / 2;
    high = mid + MIN_TEMP_SPAN / 2;
  }
  const pad = Math.max(0.4, (high - low) * 0.05);
  return { min: Math.floor(low - pad), max: Math.ceil(high + pad) };
}

function degreeScale(scale, position, title) {
  const axis = {
    position,
    min: scale.min,
    max: scale.max,
    title: { display: true, text: title },
    ticks: { maxTicksLimit: 8 },
  };
  if (position === "right") axis.grid = { drawOnChartArea: false };
  return axis;
}

function chartOptions(range, window, bounds, fallback, showLegend = true) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: showLegend ? legendOptions() : { display: false } },
    scales: {
      x: timeAxis(range, window),
      y: degreeScale(bounds || fallback, "left", "°C"),
    },
  };
}

function heatingChartOptions(range, window, circuitBounds, outdoorBounds) {
  const options = chartOptions(range, window, circuitBounds, HEATING_SCALE);
  options.scales.yOutdoor = degreeScale(outdoorBounds || OUTDOOR_SCALE, "right", "Outdoor °C");
  return options;
}

function extraHeaterOn(sample) {
  if (sample.backup_heater_running === true || sample.backup_heater_running === false) {
    return sample.backup_heater_running;
  }
  return !missing(sample.backup_heater_runtime_s) && Number(sample.backup_heater_runtime_s) > 0;
}

function deviceSeries(label, samples, on, color, lane) {
  return {
    label,
    data: samples.map((sample) => ({
      x: sample.recorded_at,
      y: on(sample) ? lane + 0.82 : lane + 0.08,
    })),
    borderColor: color,
    backgroundColor: `${color}33`,
    pointRadius: 0,
    borderWidth: 2,
    stepped: true,
    fill: { target: { value: lane }, above: `${color}33` },
  };
}

function deviceChartOptions(range, window) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: legendOptions(),
      tooltip: {
        callbacks: {
          label(context) {
            const on = context.parsed.y % 1 > 0.4;
            return `${context.dataset.label}: ${on ? "On" : "Off"}`;
          },
        },
      },
    },
    scales: {
      x: timeAxis(range, window),
      y: {
        min: 0,
        max: 2,
        ticks: {
          stepSize: 0.5,
          autoSkip: false,
          font: { size: 12 },
          callback(value) {
            if (value === 0.5) return "Extra heater";
            if (value === 1.5) return "Compressor";
            return "";
          },
        },
        grid: {
          color(context) {
            return context.tick.value === 1 ? "#e7e0d6" : "transparent";
          },
        },
      },
    },
  };
}

function upsertChart(existing, canvas, datasets, options) {
  if (!existing) {
    return new Chart(canvas, { type: "line", data: { datasets }, options });
  }
  existing.data.datasets = datasets;
  existing.options.scales = options.scales;
  existing.update();
  return existing;
}

function renderChart(samples, indoor, range, window) {
  if (typeof Chart === "undefined") {
    text(fields.chartMessage, "Chart library did not load. Temperature numbers above are still live.");
    return;
  }
  text(fields.chartMessage, samples.length ? "" : RANGES[range].empty);
  const heatingHidden = hiddenLabels(heatingChart);
  const circuit = [
    circuitSeries("Flow", samples, "flow_temp", false),
    circuitSeries("Return", samples, "return_temp", false),
    {
      label: "Temperature Indoor",
      yAxisID: "y",
      data: indoor.map((reading) => ({ x: reading.recorded_at, y: reading.temperature_c })),
      borderColor: seriesColors["Temperature Indoor"],
      backgroundColor: seriesColors["Temperature Indoor"],
      pointRadius: 4,
      borderWidth: 3,
      showLine: true,
      spanGaps: true,
    },
  ];
  const outdoor = series("Temperature Outdoor", samples, "outdoor_temp", () => true, "yOutdoor");
  const heating = withHidden([...circuit, outdoor], heatingHidden);
  const hotWaterSeries = [series("Hot water", samples, "dhw_temp")];
  const hotWaterHidden = hiddenLabels(hotWaterChart);
  const hotWater = withHidden(hotWaterSeries, hotWaterHidden);
  const devices = withHidden(
    [
      deviceSeries("Compressor", samples, (sample) => Boolean(sample.compressor_running), "#2563eb", 1),
      deviceSeries("Extra heater", samples, extraHeaterOn, "#dc2626", 0),
    ],
    hiddenLabels(devicesChart),
  );
  const shown = (datasets, hidden) => datasets.filter((dataset) => !hidden.has(dataset.label));
  heatingChart = upsertChart(
    heatingChart,
    document.querySelector("#chart"),
    heating,
    heatingChartOptions(
      range,
      window,
      temperatureBounds(shown(circuit, heatingHidden)),
      temperatureBounds(shown([outdoor], heatingHidden)),
    ),
  );
  hotWaterChart = upsertChart(
    hotWaterChart,
    document.querySelector("#dhw-chart"),
    hotWater,
    chartOptions(range, window, temperatureBounds(shown(hotWaterSeries, hotWaterHidden)), HOT_WATER_SCALE, false),
  );
  devicesChart = upsertChart(
    devicesChart,
    document.querySelector("#devices-chart"),
    devices,
    deviceChartOptions(range, window),
  );
}

function formatPrice(value, currency) {
  const text = new Intl.NumberFormat(DISPLAY_LOCALE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    useGrouping: true,
  }).format(Number(value));
  return `${text} ${currency}`;
}

function formatMeterKwh(value) {
  if (missing(value)) return "—";
  const text = new Intl.NumberFormat(DISPLAY_LOCALE, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    useGrouping: true,
  }).format(Number(value));
  return `${text} kWh`;
}

function energyAmount(item, currency, showCost, meter) {
  const kwh = meter ? formatMeterKwh(item.kwh) : formatNumber(item.kwh, 1, " kWh");
  if (!showCost || missing(item.cost)) return kwh;
  return `${kwh} · ${formatPrice(item.cost, currency)}`;
}

function renderEnergyBlock(container, block, currency, showCost, emptyText, meter) {
  container.replaceChildren();
  const channels = block && block.channels ? block.channels : [];
  const known = channels.some((channel) => !missing(channel.kwh));
  if (!known) {
    const empty = document.createElement("p");
    empty.className = "energy-empty";
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  for (const channel of channels) {
    container.append(energyRow(channel.label, channel, currency, showCost, false, meter));
  }
  container.append(energyRow("Total", block.total, currency, showCost, true, meter));
}

function energyRow(label, item, currency, showCost, total, meter) {
  const row = document.createElement("div");
  row.className = total ? "energy-row total" : "energy-row";
  const name = document.createElement("span");
  name.textContent = label;
  const value = document.createElement("span");
  value.textContent = energyAmount(item, currency, showCost, meter);
  row.append(name, value);
  return row;
}

function renderEnergy(payload) {
  const currency = (payload && payload.currency) || "€";
  const priced = Boolean(payload) && !missing(payload.price_per_kwh);
  fields.energyNote.replaceChildren();
  if (!payload) {
    text(fields.energyNote, "Heat figures appear after the next read.");
  } else if (!priced) {
    const link = document.createElement("a");
    link.href = "/app-settings";
    link.textContent = "price per kWh";
    fields.energyNote.append(
      document.createTextNode("Heat delivered is shown below. Add a "),
      link,
      document.createTextNode(" to see the cost of this range."),
    );
  } else {
    text(
      fields.energyNote,
      `Using ${formatPrice(payload.price_per_kwh, currency)} per kWh for this range. The heat meter shows the counter totals.`,
    );
  }
  renderEnergyBlock(
    fields.energyPeriod,
    payload && payload.period,
    currency,
    priced,
    "Not enough history in this range yet.",
  );
  renderEnergyBlock(
    fields.energyMeter,
    payload && payload.meter,
    currency,
    false,
    "The heat meter has not been read yet.",
    true,
  );
}

let refreshGeneration = 0;

async function refresh() {
  const generation = ++refreshGeneration;
  const pollingSeen = pollingGeneration;
  const range = chartRange;
  const window = chartWindow(range);
  const since = encodeURIComponent(window.start.toISOString());
  const [statusResponse, telemetryResponse, indoorResponse, energyResponse] = await Promise.all([
    fetch(statusUrl),
    fetch(`/api/telemetry?since=${since}`),
    fetch(`${indoorUrl}?since=${since}`),
    fetch(`/api/energy?since=${since}`),
  ]);
  if (generation !== refreshGeneration) return;
  if (statusResponse.ok) {
    const payload = await statusResponse.json();
    if (pollingSeen === pollingGeneration) renderStatus(payload);
  }
  const samples = telemetryResponse.ok ? (await telemetryResponse.json()).samples : [];
  const indoor = indoorResponse.ok ? (await indoorResponse.json()).readings : [];
  renderChart(samples, indoor, range, window);
  if (!telemetryResponse.ok) {
    const error = await readError(telemetryResponse);
    text(fields.chartMessage, error.message);
  }
  if (energyResponse.ok) {
    renderEnergy(await energyResponse.json());
  } else {
    const error = await readError(energyResponse);
    renderEnergy(null);
    text(fields.energyNote, error.message);
  }
}

window.addEventListener("controller-polling", (event) => {
  pollingGeneration += 1;
  renderStatus(event.detail);
});

window.addEventListener("controller-tick", () => {
  refresh();
});

indoorForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(indoorForm);
  const response = await fetch(indoorUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      temperature_c: Number(data.get("temperature_c")),
    }),
  });
  if (!response.ok) {
    const error = await readError(response);
    text(fields.formMessage, error.message);
    return;
  }
  const saved = await response.json();
  text(fields.formMessage, `Saved ${formatNumber(saved.temperature_c, 1, " °C")}.`);
  indoorForm.reset();
  refresh();
});

document.querySelectorAll(".ranges button").forEach((button) => {
  button.addEventListener("click", () => {
    if (!RANGES[button.dataset.range]) return;
    chartRange = button.dataset.range;
    document.querySelectorAll(".ranges button").forEach((item) => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", active ? "true" : "false");
    });
    refresh();
  });
});

refresh();
