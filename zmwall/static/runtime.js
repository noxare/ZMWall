(() => {
  const streamBadges = [...document.querySelectorAll("[data-decoder-camera]")];
  if (!streamBadges.length) return;
  const labels = document.body.dataset;
  const format = (template, values) => Object.entries(values).reduce(
    (text, [name, value]) => text.replace(`{${name}}`, value), template,
  );

  async function refreshDecoderStatus() {
    try {
      const response = await fetch("/runtime/status", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) return;
      const payload = await response.json();
      streamBadges.forEach((badge) => {
        badge.textContent = labels.i18nWaiting;
        badge.className = "stream-decoder waiting";
        badge.title = labels.i18nCameraInactive;
      });
      const runtimeStreams = Object.values(payload.screens || {}).flatMap((screen) => screen.streams || []);
      streamBadges.forEach((badge) => {
        const candidates = runtimeStreams.filter((stream) => stream.camera_key === badge.dataset.decoderCamera);
        const stream = candidates.find((item) => item.role === "active") || candidates[0];
        if (!stream) return;
        const isPreload = stream.role === "preload";
        const mode = stream.device === "gpu" ? "GPU" : stream.device === "cpu" ? "CPU" : isPreload ? labels.i18nBuffering : "…";
        badge.textContent = isPreload && stream.device !== "unknown" ? `${mode} · ${labels.i18nBuffering}` : mode;
        badge.className = `stream-decoder ${stream.device} ${isPreload ? "preloading" : "active"}`;
        const resource = stream.device === "gpu"
          ? format(labels.i18nHardwareDecoding, { device: payload.hardware.gpu, method: stream.hwdec })
          : stream.device === "cpu"
            ? format(labels.i18nSoftwareDecoding, { device: payload.hardware.cpu })
            : labels.i18nDecoderDetecting;
        badge.title = isPreload ? format(labels.i18nHiddenPreload, { resource }) : resource;
      });
    } catch (_error) {
      // A transient restart or network interruption is resolved by the next poll.
    }
  }

  refreshDecoderStatus();
  window.setInterval(refreshDecoderStatus, 3000);
})();
