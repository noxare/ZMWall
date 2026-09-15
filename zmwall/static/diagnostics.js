(() => {
  const format = (template, values) => Object.entries(values).reduce(
    (text, [name, value]) => text.replace(`{${name}}`, value), template,
  );
  const form = document.querySelector("[data-diagnostics-form]");
  form?.addEventListener("submit", () => {
    const submit = document.querySelector("[data-diagnostics-submit]");
    const running = document.querySelector("[data-diagnostics-running]");
    if (submit) {
      submit.disabled = true;
      submit.textContent = document.body.dataset.i18nDiagnosticsRunning;
    }
    if (running) running.hidden = false;
  });

  const output = document.querySelector("[data-diagnostic-output]");
  document.querySelector("[data-copy-diagnostic]")?.addEventListener("click", async (event) => {
    if (!output) return;
    await navigator.clipboard.writeText(output.textContent);
    event.currentTarget.textContent = document.body.dataset.i18nCopied;
  });
  document.querySelector("[data-download-diagnostic]")?.addEventListener("click", () => {
    if (!output) return;
    const blob = new Blob([output.textContent], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `zmwall-diagnose-${new Date().toISOString().replaceAll(":", "-")}.log`;
    link.click();
    URL.revokeObjectURL(link.href);
  });

  const batchButton = document.querySelector("[data-batch-start]");
  const batchProgress = document.querySelector("[data-batch-progress]");
  const batchBar = document.querySelector("[data-batch-progress-bar]");
  const batchLabel = document.querySelector("[data-batch-progress-label]");
  let observedRunning = false;

  function updateProbeStatus(state) {
    if (!state.camera_key || !state.probe_status) return;
    const row = [...document.querySelectorAll("[data-camera-key]")].find(
      (candidate) => candidate.dataset.cameraKey === state.camera_key,
    );
    const badge = row?.querySelector("[data-probe-status]");
    if (!badge) return;
    const key = `i18nProbe${state.probe_status.split("_").map(
      (part) => part.charAt(0).toUpperCase() + part.slice(1),
    ).join("")}`;
    badge.textContent = document.body.dataset[key] || state.probe_status;
    badge.title = state.probe_error || "";
    badge.className = `resolution-state ${state.probe_status === "ok" ? "ok" : "error"}`;
  }

  function showBatchState(state) {
    if (!batchProgress || !batchBar || !batchLabel) return;
    if (state.state === "running") {
      observedRunning = true;
      batchProgress.hidden = false;
      batchBar.max = Math.max(1, Number(state.total || 0));
      batchBar.value = Number(state.completed || 0);
      batchLabel.textContent = format(document.body.dataset.i18nBatchRunning, {
        completed: state.completed || 0, total: state.total || 0,
      });
      updateProbeStatus(state);
      if (batchButton) batchButton.disabled = true;
    } else if (state.state === "completed" && observedRunning) {
      batchProgress.hidden = false;
      batchBar.value = batchBar.max;
      batchLabel.textContent = document.body.dataset.i18nBatchComplete;
      window.setTimeout(() => window.location.reload(), 700);
    } else if (state.state === "error" || state.state === "busy") {
      batchProgress.hidden = false;
      batchLabel.textContent = state.message || document.body.dataset.i18nBatchFailed;
      if (batchButton) batchButton.disabled = false;
    } else if (batchButton) {
      batchButton.disabled = false;
    }
  }

  async function pollBatch() {
    try {
      const response = await fetch("/diagnostics/all/status", {
        credentials: "same-origin", headers: { Accept: "application/json" },
      });
      if (response.ok) showBatchState(await response.json());
    } catch (_error) {
      // The next poll will recover after a transient web-service restart.
    }
  }

  batchButton?.addEventListener("click", async () => {
    batchButton.disabled = true;
    batchProgress.hidden = false;
    try {
      const response = await fetch("/diagnostics/all/start", {
        method: "POST", credentials: "same-origin", headers: { Accept: "application/json" },
      });
      showBatchState(await response.json());
    } catch (_error) {
      showBatchState({ state: "error" });
    }
  });

  document.querySelector("[data-download-batch]")?.addEventListener("click", () => {
    const table = document.querySelector("[data-batch-table]");
    if (!table) return;
    const lines = [...table.querySelectorAll("tr")].map((row) =>
      [...row.querySelectorAll("th:not([data-export-ignore]),td:not([data-export-ignore])")].map((cell) => {
        const value = cell.innerText.trim().replace(/\s+/g, " ");
        return `"${value.replaceAll('"', '""')}"`;
      }).join("\t")
    );
    const blob = new Blob([lines.join("\n")], { type: "text/tab-separated-values;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `zmwall-streamuebersicht-${new Date().toISOString().replaceAll(":", "-")}.tsv`;
    link.click();
    URL.revokeObjectURL(link.href);
  });

  pollBatch();
  window.setInterval(pollBatch, 1000);
})();
