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
      const streamBadges = [...document.querySelectorAll("[data-decoder-camera]")];
      streamBadges.forEach((badge) => {
        badge.textContent = "wartet";
        badge.className = "stream-decoder waiting";
        badge.title = "Diese Kamera ist momentan nicht aktiv";
      });
      const activeStreams = Object.values(payload.screens || {}).flatMap((screen) => screen.streams || []);
      activeStreams.forEach((stream) => {
        const badge = streamBadges.find((item) => item.dataset.decoderCamera === stream.camera_key);
        if (!badge) return;
        const mode = stream.device === "gpu" ? "GPU" : stream.device === "cpu" ? "CPU" : "…";
        badge.textContent = mode;
        badge.className = `stream-decoder ${stream.device}`;
        badge.title = stream.device === "gpu"
          ? `Hardware-Decoding: ${payload.hardware.gpu} (${stream.hwdec})`
          : stream.device === "cpu"
            ? `Software-Decoding: ${payload.hardware.cpu}`
            : "Decoder wird ermittelt";
      });
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
