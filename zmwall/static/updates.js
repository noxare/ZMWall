(() => {
  const control = document.getElementById("update-control");
  if (!control) return;

  const initialState = control.dataset.state;

  async function refreshStatus() {
    try {
      const response = await fetch("/updates/status", {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("status request failed");
      const status = await response.json();
      if (status.state !== initialState || status.version !== document.body.dataset.version) {
        window.location.reload();
      }
    } catch (error) {
      // During a successful update the web process is unavailable briefly.
      // The next poll reloads the page after the watchdog has restarted it.
    }
  }

  const interval = initialState === "updating" ? 3000 : 60000;
  window.setInterval(refreshStatus, interval);
  window.setTimeout(refreshStatus, initialState === "checking" ? 1500 : interval);
})();
