const form = document.querySelector("#price-form");
const priceInput = document.querySelector("#price");
const currencyInput = document.querySelector("#currency");
const status = document.querySelector("#status");

function show(message) {
  status.textContent = message;
}

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
  priceInput.value = String(saved.price_per_kwh);
  show("Saved price loaded.");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch("/api/app-settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        price_per_kwh: priceInput.value,
        currency: currencyInput.value,
      }),
    });
    if (!response.ok) {
      show(await readError(response));
      return;
    }
    const saved = await response.json();
    priceInput.value = String(saved.price_per_kwh);
    currencyInput.value = saved.currency;
    show("Price saved.");
  } finally {
    button.disabled = false;
  }
});

load();
