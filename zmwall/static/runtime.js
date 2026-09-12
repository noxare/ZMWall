(() => {
  const streamBadges = [...document.querySelectorAll("[data-decoder-camera]")];
  if (!streamBadges.length) return;

  async function refreshDecoderStatus() {
    try {
      const response = await fetch("/runtime/status", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const payload = await response.json();
      streamBadges.forEach((badge) => {
        badge.textContent = "wartet";
        badge.className = "stream-decoder waiting";
        badge.title = "Diese Kamera ist momentan nicht aktiv";
      });
      const runtimeStreams = Object.values(payload.screens || {}).flatMap((screen) => screen.streams || []);
      streamBadges.forEach((badge) => {
        const candidates = runtimeStreams.filter((stream) => stream.camera_key === badge.dataset.decoderCamera);
        const stream = candidates.find((item) => item.role === "active") || candidates[0];
        if (!stream) return;
        const isPreload = stream.role === "preload";
        const mode = stream.device === "gpu" ? "GPU" : stream.device === "cpu" ? "CPU" : isPreload ? "puffert" : "…";
        badge.textContent = isPreload && stream.device !== "unknown" ? `${mode} · puffert` : mode;
        badge.className = `stream-decoder ${stream.device} ${isPreload ? "preloading" : "active"}`;
        const resource = stream.device === "gpu"
          ? `Hardware-Decoding: ${payload.hardware.gpu} (${stream.hwdec})`
          : stream.device === "cpu"
            ? `Software-Decoding: ${payload.hardware.cpu}`
            : "Decoder wird ermittelt";
        badge.title = isPreload ? `Verdeckter Vorab-Stream – ${resource}` : resource;
      });
    } catch (_error) {
      // A transient restart or network interruption is resolved by the next poll.
    }
  }

  refreshDecoderStatus();
  window.setInterval(refreshDecoderStatus, 3000);
})();
