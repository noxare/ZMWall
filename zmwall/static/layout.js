(() => {
  const pool = document.getElementById("camera-pool");
  const form = document.getElementById("layout-form");
  if (!pool || !form) return;

  let dragged = null;
  let selected = null;

  const chips = () => [...document.querySelectorAll(".camera-chip")];
  const tileZones = () => [...document.querySelectorAll('[data-dropzone="tile"]')];

  function destinationList(zone) {
    return zone.dataset.dropzone === "pool" ? zone : zone.querySelector(".tile-camera-list");
  }

  function clearSelected() {
    if (selected) selected.classList.remove("selected");
    selected = null;
    tileZones().forEach((zone) => zone.classList.remove("tap-target"));
  }

  function selectChip(chip) {
    clearSelected();
    selected = chip;
    chip.classList.add("selected");
    tileZones().forEach((zone) => zone.classList.add("tap-target"));
    pool.classList.add("tap-target");
  }

  function refreshPool() {
    const poolChips = [...pool.querySelectorAll(".camera-chip")];
    const empty = pool.querySelector(".pool-empty");
    if (empty) empty.remove();
    if (!poolChips.length) {
      const message = document.createElement("p");
      message.className = "pool-empty";
      message.textContent = document.body.dataset.i18nAllAssigned;
      pool.appendChild(message);
    }
    const count = document.getElementById("available-count");
    if (count) count.textContent = String(poolChips.length);
  }

  function syncInputs() {
    tileZones().forEach((zone) => {
      const keys = [...zone.querySelectorAll(".camera-chip")].map((chip) => chip.dataset.cameraKey);
      zone.querySelector('input[type="hidden"]').value = JSON.stringify(keys);
      zone.classList.toggle("has-cameras", keys.length > 0);
    });
    refreshPool();
  }

  function moveChip(chip, zone, before = null) {
    const destination = destinationList(zone);
    const empty = pool.querySelector(".pool-empty");
    if (empty) empty.remove();
    if (before && before !== chip && before.parentElement === destination) {
      destination.insertBefore(chip, before);
    } else {
      destination.appendChild(chip);
    }
    clearSelected();
    applyFilter();
    syncInputs();
  }

  function wireChip(chip) {
    chip.addEventListener("dragstart", (event) => {
      dragged = chip;
      chip.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", chip.dataset.cameraKey);
    });
    chip.addEventListener("dragend", () => {
      chip.classList.remove("dragging");
      dragged = null;
      document.querySelectorAll(".drag-over").forEach((zone) => zone.classList.remove("drag-over"));
      syncInputs();
    });
    chip.addEventListener("click", (event) => {
      if (event.target.closest(".unassign")) return;
      event.stopPropagation();
      if (selected === chip) clearSelected();
      else selectChip(chip);
    });
    chip.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (selected === chip) clearSelected();
        else selectChip(chip);
      }
    });
    const remove = chip.querySelector(".unassign");
    if (remove) {
      remove.addEventListener("click", (event) => {
        event.stopPropagation();
        moveChip(chip, pool);
      });
    }
  }

  function wireDropzone(zone) {
    if (zone.dataset.dropzoneWired === "true") return;
    zone.dataset.dropzoneWired = "true";
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", (event) => {
      if (!zone.contains(event.relatedTarget)) zone.classList.remove("drag-over");
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("drag-over");
      if (!dragged) return;
      const targetChip = event.target.closest(".camera-chip");
      moveChip(dragged, zone, targetChip);
    });
    zone.addEventListener("click", (event) => {
      if (!selected || event.target.closest(".camera-chip")) return;
      moveChip(selected, zone);
    });
  }

  document.querySelectorAll(".dropzone").forEach(wireDropzone);

  chips().forEach(wireChip);

  const filter = document.getElementById("camera-filter");
  function applyFilter() {
    const term = (filter?.value || "").trim().toLocaleLowerCase(document.documentElement.lang);
    let visible = 0;
    pool.querySelectorAll(".camera-chip").forEach((chip) => {
      chip.hidden = Boolean(term && !chip.dataset.cameraSearch.includes(term));
      if (!chip.hidden) visible += 1;
    });
    const noMatch = document.getElementById("filter-empty");
    if (noMatch) noMatch.hidden = !term || visible > 0;
  }
  if (filter) filter.addEventListener("input", applyFilter);

  function clampGridSize(value) {
    return Math.max(1, Math.min(8, Number(value) || 1));
  }

  function setGridSymbol(symbol, cols, rows) {
    symbol.style.setProperty("--symbol-cols", String(cols));
    symbol.style.setProperty("--symbol-rows", String(rows));
    symbol.replaceChildren(...Array.from({ length: cols * rows }, () => document.createElement("i")));
  }

  function createTile(screenId, position) {
    const zone = document.createElement("div");
    zone.className = "tile dropzone";
    zone.dataset.dropzone = "tile";
    const number = document.createElement("span");
    number.className = "tile-number";
    number.textContent = String(position + 1);
    const list = document.createElement("div");
    list.className = "tile-camera-list";
    const placeholder = document.createElement("p");
    placeholder.className = "tile-placeholder";
    placeholder.textContent = document.body.dataset.i18nDropCamera;
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = `tile_${screenId}_${position}`;
    input.value = "[]";
    zone.append(number, list, placeholder, input);
    wireDropzone(zone);
    return zone;
  }

  function resizeScreenGrid(card, colsValue, rowsValue) {
    const cols = clampGridSize(colsValue);
    const rows = clampGridSize(rowsValue);
    const grid = card.querySelector("[data-screen-grid]");
    const screenId = card.dataset.screenId;
    const targetCount = cols * rows;
    const existingTiles = [...grid.querySelectorAll(':scope > [data-dropzone="tile"]')];
    const removedTiles = existingTiles.slice(targetCount);
    const hasAssignedCameras = removedTiles.some((tile) => tile.querySelector(".camera-chip"));
    if (hasAssignedCameras && !window.confirm(document.body.dataset.i18nGridShrinkConfirm)) return false;

    removedTiles.forEach((tile) => {
      [...tile.querySelectorAll(".camera-chip")].forEach((chip) => moveChip(chip, pool));
      tile.remove();
    });
    for (let position = existingTiles.length; position < targetCount; position += 1) {
      grid.appendChild(createTile(screenId, position));
    }
    grid.style.setProperty("--cols", String(cols));
    card.querySelector(".grid-cols").value = String(cols);
    card.querySelector(".grid-rows").value = String(rows);
    card.querySelector(".grid-custom-cols").value = String(cols);
    card.querySelector(".grid-custom-rows").value = String(rows);
    card.querySelector(".grid-picker-label").textContent = `${cols} × ${rows}`;
    card.querySelector(".screen-grid-summary").textContent = `${cols} × ${rows}`;
    setGridSymbol(card.querySelector(".grid-picker-trigger .grid-symbol"), cols, rows);
    let matchedPreset = false;
    card.querySelectorAll(".grid-preset").forEach((button) => {
      const selectedPreset = Number(button.dataset.cols) === cols && Number(button.dataset.rows) === rows;
      button.setAttribute("aria-pressed", String(selectedPreset));
      matchedPreset ||= selectedPreset;
    });
    card.querySelector(".grid-custom-toggle").setAttribute("aria-pressed", String(!matchedPreset));
    syncInputs();
    return true;
  }

  function closeGridPopovers(except = null) {
    document.querySelectorAll(".grid-picker-popover").forEach((popover) => {
      if (popover === except) return;
      popover.hidden = true;
      popover.closest(".grid-picker").querySelector(".grid-picker-trigger")?.setAttribute("aria-expanded", "false");
    });
  }

  document.querySelectorAll(".screen-card").forEach((card) => {
    const picker = card.querySelector(".grid-picker");
    const trigger = picker.querySelector(".grid-picker-trigger");
    const popover = picker.querySelector(".grid-picker-popover");
    const customFields = picker.querySelector(".grid-custom-fields");
    const customToggle = picker.querySelector(".grid-custom-toggle");
    const customCols = picker.querySelector(".grid-custom-cols");
    const customRows = picker.querySelector(".grid-custom-rows");

    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = popover.hidden;
      closeGridPopovers(popover);
      popover.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", String(willOpen));
    });
    popover.addEventListener("click", (event) => event.stopPropagation());
    picker.querySelectorAll(".grid-preset").forEach((button) => button.addEventListener("click", () => {
      if (resizeScreenGrid(card, button.dataset.cols, button.dataset.rows)) {
        popover.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
      }
    }));
    customToggle.addEventListener("click", () => {
      customFields.hidden = !customFields.hidden;
      if (!customFields.hidden) customCols.focus();
    });
    const applyCustomGrid = () => {
      if (!resizeScreenGrid(card, customCols.value, customRows.value)) {
        customCols.value = card.querySelector(".grid-cols").value;
        customRows.value = card.querySelector(".grid-rows").value;
      }
    };
    customCols.addEventListener("change", applyCustomGrid);
    customRows.addEventListener("change", applyCustomGrid);
  });

  document.querySelectorAll(".add-grid-picker").forEach((picker) => {
    const rowsInput = picker.querySelector(".grid-rows");
    const colsInput = picker.querySelector(".grid-cols");
    const customFields = picker.querySelector(".grid-custom-fields");
    const customToggle = picker.querySelector(".grid-custom-toggle");
    const customCols = picker.querySelector(".grid-custom-cols");
    const customRows = picker.querySelector(".grid-custom-rows");
    const selectGrid = (colsValue, rowsValue, custom = false) => {
      const cols = clampGridSize(colsValue);
      const rows = clampGridSize(rowsValue);
      colsInput.value = String(cols);
      rowsInput.value = String(rows);
      customCols.value = String(cols);
      customRows.value = String(rows);
      picker.querySelectorAll(".grid-preset").forEach((button) => button.setAttribute("aria-pressed", String(
        !custom && Number(button.dataset.cols) === cols && Number(button.dataset.rows) === rows
      )));
      customToggle.setAttribute("aria-pressed", String(custom));
    };
    picker.querySelectorAll(".grid-preset").forEach((button) => button.addEventListener("click", () => {
      customFields.hidden = true;
      selectGrid(button.dataset.cols, button.dataset.rows);
    }));
    customToggle.addEventListener("click", () => {
      customFields.hidden = false;
      selectGrid(customCols.value, customRows.value, true);
      customCols.focus();
    });
    const applyCustomGrid = () => selectGrid(customCols.value, customRows.value, true);
    customCols.addEventListener("input", applyCustomGrid);
    customRows.addEventListener("input", applyCustomGrid);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      clearSelected();
      closeGridPopovers();
    }
  });
  document.addEventListener("click", () => closeGridPopovers());
  form.addEventListener("submit", syncInputs);
  syncInputs();
})();
