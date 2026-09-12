(() => {
  const badges = [...document.querySelectorAll("[data-decoder-screen]")];
  if (!badges.length) return;

  async function refreshDecoderStatus() {
    try {
      const response = await fetch("/runtime/status", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const payload = await response.json();
      badges.forEach((badge) => {
        const status = payload.screens?.[badge.dataset.decoderScreen];
        if (!status) return;
        badge.textContent = status.label;
        badge.className = `decoder-status ${status.state}`;
        const details = [
          `CPU: ${status.cpu_model}`,
          `GPU: ${status.gpu_model}`,
          "",
          ...(status.streams || []).map((stream) =>
            `${stream.camera}: ${stream.device === "gpu" ? "GPU" : stream.device === "cpu" ? "CPU" : "wird ermittelt"}`
          ),
        ];
        badge.title = details.join("\n");
      });
    } catch (_error) {
      // A transient restart or network interruption is resolved by the next poll.
    }
  }

  refreshDecoderStatus();
  window.setInterval(refreshDecoderStatus, 3000);
})();
