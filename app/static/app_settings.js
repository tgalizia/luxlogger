const form = document.querySelector("#price-form");
const priceInput = document.querySelector("#price");
const currencyInput = document.querySelector("#currency");
const status = document.querySelector("#status");
const EUROPEAN_PRICE = /^\d{1,3},\d{2}$/;

function show(message) {
  status.textContent = message;
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

async function readError(response) {
  const body = await response.json().catch(() => ({}));
  if (typeof body.detail === "string") return body.detail;
  return response.statusText || "Could not save the price.";
}

async function load() {
  const response = await fetch("/api/app-settings");
  if (!response.ok) {
    show(await readError(response));
    return;
  }
  const saved = await response.json();
  currencyInput.value = saved.currency || "€";
  if (saved.price_per_kwh === null || saved.price_per_kwh === undefined) {
    show("No price saved yet.");
    return;
  }
  priceInput.value = formatEuropeanPrice(saved.price_per_kwh);
  show("Saved price loaded.");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  const price = europeanPrice(priceInput.value);
  if (price === null) {
    show("Enter the price as a European number, for example 0,30.");
    priceInput.focus();
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch("/api/app-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        price_per_kwh: price,
        currency: currencyInput.value,
      }),
    });
    if (!response.ok) {
      show(await readError(response));
      return;
    }
    const saved = await response.json();
    priceInput.value = formatEuropeanPrice(saved.price_per_kwh);
    currencyInput.value = saved.currency;
    show("Price saved.");
  } finally {
    button.disabled = false;
  }
});

load();
