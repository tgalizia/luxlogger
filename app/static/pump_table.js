const MODE_IDS = ["ID_Ba_Hz_akt", "ID_Ba_Bw_akt"];

function detailMessage(body) {
  if (body && typeof body.detail === "string") return body.detail;
  if (body && body.detail && body.detail.message) return body.detail.message;
  return "Request failed.";
}

function optionLabel(setting, value) {
  const labels = setting.option_labels || {};
  return labels[value] || String(value);
}

function mountPumpTable(root, config = {}) {
  const editable = Boolean(config.editable);
  const announce = config.announce !== false;
  const state = { sections: [], error: "", chosen: {}, demo: false };

  function rememberChoices() {
    if (!editable) return;
    for (const select of root.querySelectorAll("select")) {
      if (select.value !== select.dataset.current) state.chosen[select.dataset.id] = select.value;
      else delete state.chosen[select.dataset.id];
    }
  }

  function render() {
    root.replaceChildren();
    if (state.error && announce) {
      const note = document.createElement("p");
      note.className = "pump-note";
      note.textContent = state.error;
      root.append(note);
    }
    if (!state.sections.length) {
      if (!state.error) {
        const note = document.createElement("p");
        note.className = "pump-note";
        note.textContent = "No reading stored yet.";
        root.append(note);
      }
      return;
    }
    const grid = document.createElement("div");
    grid.className = "pump-sections";
    for (const section of state.sections) grid.append(renderSection(section));
    root.append(grid);
  }

  function renderSection(section) {
    const article = document.createElement("section");
    article.className = "card pump-section";
    if (section.id === "settings") article.classList.add("pump-settings");
    if (section.id === "system") article.classList.add("pump-system");
    if (section.id === "errors") article.classList.add("pump-errors");
    const heading = document.createElement("h2");
    heading.id = `pump-${section.id}`;
    heading.textContent = section.title;
    const table = section.id === "errors" ? renderErrorTable(section, heading.id) : renderValueTable(section, heading.id);
    article.append(heading, table);
    return article;
  }

  function renderValueTable(section, labelledBy) {
    const table = document.createElement("table");
    table.setAttribute("aria-labelledby", labelledBy);
    const body = document.createElement("tbody");
    for (const row of section.rows) body.append(renderRow(row));
    table.append(body);
    return table;
  }

  function renderErrorTable(section, labelledBy) {
    const table = document.createElement("table");
    table.className = "pump-error-table";
    table.setAttribute("aria-labelledby", labelledBy);
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const title of ["Time", "Code", "Description"]) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = title;
      headRow.append(cell);
    }
    head.append(headRow);
    const body = document.createElement("tbody");
    for (const row of section.rows) {
      const line = document.createElement("tr");
      for (const value of [row.time || row.label, row.code, row.name]) {
        const cell = document.createElement("td");
        cell.textContent = value || "—";
        line.append(cell);
      }
      body.append(line);
    }
    table.append(head, body);
    return table;
  }

  function renderRow(row) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = row.label;
    const td = document.createElement("td");
    if (editable && MODE_IDS.includes(row.id) && row.kind === "choice") td.append(renderMode(row));
    else td.textContent = row.display || "—";
    tr.append(th, td);
    return tr;
  }

  function renderMode(setting) {
    const control = document.createElement("div");
    control.className = "pump-control";
    const select = document.createElement("select");
    select.dataset.id = setting.id;
    select.dataset.current = String(setting.value ?? "");
    select.setAttribute("aria-label", setting.label);
    const currentValue = String(setting.value ?? "");
    const choices = setting.options ? [...setting.options] : [];
    if (currentValue && !choices.includes(currentValue)) choices.unshift(currentValue);
    for (const option of choices) {
      const item = document.createElement("option");
      item.value = option;
      item.textContent = optionLabel(setting, option);
      if (!setting.options || !setting.options.includes(option)) item.disabled = true;
      select.append(item);
    }
    const preferred = state.chosen[setting.id];
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
    set.addEventListener("click", () => {
      if (typeof config.onSet === "function") config.onSet(setting, select.value);
    });
    refresh();
    control.append(select, set);
    return control;
  }

  function settingsSection() {
    let section = state.sections.find((item) => item.id === "settings");
    if (!section) {
      section = { id: "settings", title: "Settings", rows: [] };
      state.sections.unshift(section);
    }
    return section;
  }

  function settings() {
    const section = state.sections.find((item) => item.id === "settings");
    return section ? section.rows : [];
  }

  function updateSetting(setting) {
    if (!setting) return;
    rememberChoices();
    const section = settingsSection();
    const index = section.rows.findIndex((row) => row.id === setting.id);
    if (index >= 0) section.rows[index] = setting;
    else section.rows.push(setting);
    delete state.chosen[setting.id];
    render();
  }

  function setSettings(rows) {
    rememberChoices();
    settingsSection().rows = rows || [];
    render();
  }

  async function load() {
    const response = await fetch("/api/pump-info");
    const body = await response.json().catch(() => ({}));
    rememberChoices();
    if (!response.ok) {
      state.error = detailMessage(body);
      render();
      return { ok: false, demo: false, message: state.error, body };
    }
    state.error = "";
    state.demo = Boolean(body.demo);
    state.sections = body.sections || [];
    render();
    return { ok: true, demo: state.demo, message: "", body };
  }

  return { load, settings, updateSetting, setSettings };
}

window.mountPumpTable = mountPumpTable;
