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
      message.textContent = "Alle RTSP-Kameras sind zugeordnet.";
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

  document.querySelectorAll(".dropzone").forEach((zone) => {
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
  });

  chips().forEach(wireChip);

  const filter = document.getElementById("camera-filter");
  function applyFilter() {
    const term = (filter?.value || "").trim().toLocaleLowerCase("de");
    let visible = 0;
    pool.querySelectorAll(".camera-chip").forEach((chip) => {
      chip.hidden = Boolean(term && !chip.dataset.cameraSearch.includes(term));
      if (!chip.hidden) visible += 1;
    });
    const noMatch = document.getElementById("filter-empty");
    if (noMatch) noMatch.hidden = !term || visible > 0;
  }
  if (filter) filter.addEventListener("input", applyFilter);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") clearSelected();
  });
  form.addEventListener("submit", syncInputs);
  syncInputs();
})();
