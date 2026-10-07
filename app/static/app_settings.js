const connectionForm = document.querySelector("#connection-form");
const equipmentForm = document.querySelector("#equipment-form");
const aiForm = document.querySelector("#ai-form");
const priceForm = document.querySelector("#price-form");
const hostInput = document.querySelector("#host");
const portInput = document.querySelector("#port");
const pumpMakerInput = document.querySelector("#pump-maker");
const pumpModelInput = document.querySelector("#pump-model");
const controllerModelInput = document.querySelector("#controller-model");
const softwareInput = document.querySelector("#controller-software");
const providerInput = document.querySelector("#ai-provider");
const modelInput = document.querySelector("#ai-model");
const advicePromptInput = document.querySelector("#advice-prompt");
const settingsPromptInput = document.querySelector("#settings-prompt");
const readButton = document.querySelector("#read-equipment");
const resetButton = document.querySelector("#reset-prompts");
const priceInput = document.querySelector("#price");
const currencyInput = document.querySelector("#currency");
const connectionStatus = document.querySelector("#connection-status");
const equipmentStatus = document.querySelector("#equipment-status");
const aiStatus = document.querySelector("#ai-status");
const priceStatus = document.querySelector("#status");
const EUROPEAN_PRICE = /^\d{1,3},\d{2}$/;

let modelChoices = {};
let promptDefaults = { advice: "", settings: "" };

function show(element, message, tone) {
  element.classList.remove("ok", "error");
  element.replaceChildren();
  if (!message) {
    element.hidden = true;
    return;
  }
  element.hidden = false;
  if (tone === "ok" || tone === "error") {
    element.classList.add(tone);
    const icon = document.createElement("i");
    icon.className = tone === "ok" ? "fa-solid fa-circle-check" : "fa-solid fa-circle-xmark";
    icon.setAttribute("aria-hidden", "true");
    element.append(icon);
  }
  element.append(document.createTextNode(message));
}

function formatEuropeanPrice(value) {
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    useGrouping: false,
  }).format(Number(value));
}

function europeanPrice(value) {
  const text = String(value).trim();
  if (!EUROPEAN_PRICE.test(text)) return null;
  const number = Number(text.replace(",", "."));
  if (number > 100) return null;
  return text;
}

function fillModels(provider, selected) {
  const choices = modelChoices[provider] || [];
  modelInput.replaceChildren();
  for (const name of choices) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    modelInput.append(option);
  }
  if (choices.includes(selected)) modelInput.value = selected;
  else if (choices.length) modelInput.value = choices[0];
}

async function readError(response) {
  const body = await response.json().catch(() => ({}));
  if (typeof body.detail === "string") return body.detail;
  return response.statusText || "Could not save.";
}

async function save(form, body, status, success) {
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const response = await fetch("/api/app-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      show(status, await readError(response), "error");
      return null;
    }
    const saved = await response.json();
    show(status, success, "ok");
    return saved;
  } finally {
    button.disabled = false;
  }
}

priceInput.addEventListener("input", () => {
  let value = priceInput.value.replace(/[^\d,]/g, "");
  const comma = value.indexOf(",");
  if (comma !== -1) {
    const whole = value.slice(0, comma);
    const fraction = value.slice(comma + 1).replace(/,/g, "").slice(0, 2);
    value = `${whole},${fraction}`;
  }
  if (priceInput.value !== value) priceInput.value = value;
});

providerInput.addEventListener("change", () => {
  fillModels(providerInput.value, modelInput.value);
});

connectionForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const saved = await save(
    connectionForm,
    { luxtronik_host: hostInput.value, luxtronik_port: Number(portInput.value) },
    connectionStatus,
    "Address saved. The next read uses it.",
  );
  if (!saved) return;
  hostInput.value = saved.luxtronik_host;
  portInput.value = saved.luxtronik_port;
});

equipmentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const saved = await save(
    equipmentForm,
    {
      pump_maker: pumpMakerInput.value,
      pump_model: pumpModelInput.value,
      controller_model: controllerModelInput.value,
      controller_software: softwareInput.value,
    },
    equipmentStatus,
    "Equipment saved.",
  );
  if (!saved) return;
  pumpMakerInput.value = saved.pump_maker;
  pumpModelInput.value = saved.pump_model;
  controllerModelInput.value = saved.controller_model;
  softwareInput.value = saved.controller_software;
});

readButton.addEventListener("click", async () => {
  readButton.disabled = true;
  show(equipmentStatus, "Reading the controller…");
  try {
    const response = await fetch("/api/app-settings/equipment", { method: "POST" });
    if (!response.ok) {
      show(equipmentStatus, await readError(response), "error");
      return;
    }
    const body = await response.json();
    if (body.pump_model) pumpModelInput.value = body.pump_model;
    if (body.controller_software) softwareInput.value = body.controller_software;
    const found = [body.pump_model ? "pump model" : "", body.controller_software ? "software version" : ""]
      .filter(Boolean)
      .join(" and ");
    if (!found) {
      show(equipmentStatus, "The controller did not report a pump model or software version.", "error");
      return;
    }
    show(equipmentStatus, `Filled the ${found} from the controller. Save to keep them.`, "ok");
  } finally {
    readButton.disabled = false;
  }
});

aiForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const saved = await save(
    aiForm,
    {
      ai_provider: providerInput.value,
      ai_model: modelInput.value,
      advice_prompt: advicePromptInput.value,
      settings_prompt: settingsPromptInput.value,
    },
    aiStatus,
    "Advisor settings saved.",
  );
  if (!saved) return;
  providerInput.value = saved.ai_provider;
  fillModels(saved.ai_provider, saved.ai_model);
  advicePromptInput.value = saved.advice_prompt;
  settingsPromptInput.value = saved.settings_prompt;
});

resetButton.addEventListener("click", () => {
  advicePromptInput.value = promptDefaults.advice;
  settingsPromptInput.value = promptDefaults.settings;
  show(aiStatus, "Default prompts are in the form. Save to keep them.", "ok");
});

priceForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const price = europeanPrice(priceInput.value);
  if (price === null) {
    show(priceStatus, "Enter the price as a European number, for example 0,30.", "error");
    priceInput.focus();
    return;
  }
  const saved = await save(
    priceForm,
    { price_per_kwh: price, currency: currencyInput.value },
    priceStatus,
    "Price saved.",
  );
  if (!saved) return;
  priceInput.value = formatEuropeanPrice(saved.price_per_kwh);
  currencyInput.value = saved.currency;
});

async function load() {
  const response = await fetch("/api/app-settings");
  if (!response.ok) {
    const message = await readError(response);
    show(connectionStatus, message, "error");
    show(equipmentStatus, message, "error");
    show(aiStatus, message, "error");
    show(priceStatus, message, "error");
    return;
  }
  const saved = await response.json();
  hostInput.value = saved.luxtronik_host || "";
  portInput.value = saved.luxtronik_port || "";
  pumpMakerInput.value = saved.pump_maker || "";
  pumpModelInput.value = saved.pump_model || "";
  controllerModelInput.value = saved.controller_model || "";
  softwareInput.value = saved.controller_software || "";
  modelChoices = saved.model_choices || {};
  promptDefaults = {
    advice: saved.advice_prompt_default || "",
    settings: saved.settings_prompt_default || "",
  };
  providerInput.value = saved.ai_provider || "openai";
  fillModels(providerInput.value, saved.ai_model);
  advicePromptInput.value = saved.advice_prompt || "";
  settingsPromptInput.value = saved.settings_prompt || "";
  currencyInput.value = saved.currency || "€";
  if (saved.price_per_kwh === null || saved.price_per_kwh === undefined) return;
  priceInput.value = formatEuropeanPrice(saved.price_per_kwh);
}

load();
