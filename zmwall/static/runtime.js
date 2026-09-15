(() => {
  const streamBadges = [...document.querySelectorAll("[data-decoder-camera]")];
  const networkStatus = document.getElementById("network-status");
  if (!streamBadges.length && !networkStatus) return;
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
      if (networkStatus) {
        const connections = payload.network?.connections || [];
        networkStatus.textContent = connections.length
          ? connections.map((connection) => {
            const type = connection.type === "wifi" ? labels.i18nNetworkWifi : labels.i18nNetworkLan;
            return `${type} (${connection.interface})`;
          }).join(" + ")
          : labels.i18nNetworkOffline;
        networkStatus.className = `network-status ${connections.length ? "connected" : "offline"}`;
        networkStatus.title = connections.map((connection) => {
          const details = [connection.ipv4, connection.gateway ? `Gateway ${connection.gateway}` : "", connection.ssid || ""];
          return `${connection.interface}: ${details.filter(Boolean).join(" · ")}`;
        }).join("\n");
      }
      streamBadges.forEach((badge) => {
        badge.textContent = labels.i18nWaiting;
        badge.className = "stream-decoder waiting";
        badge.title = labels.i18nCameraInactive;
      });
      const recoveries = payload.recoveries || {};
      streamBadges.forEach((badge) => {
        const recovery = recoveries[badge.dataset.decoderCamera];
        if (!recovery) return;
        const running = recovery.state === "reregistering";
        const retrying = recovery.state === "retrying";
        badge.textContent = running
          ? labels.i18nRtspReregistering
          : retrying ? labels.i18nRtspRetrying : labels.i18nRtspMissing;
        badge.className = `stream-decoder ${running || retrying ? "recovering" : "error"}`;
        badge.title = badge.textContent;
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
