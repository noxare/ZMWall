(() => {
  const form = document.querySelector("[data-diagnostics-form]");
  form?.addEventListener("submit", () => {
    const submit = document.querySelector("[data-diagnostics-submit]");
    const running = document.querySelector("[data-diagnostics-running]");
    if (submit) {
      submit.disabled = true;
      submit.textContent = "Diagnose läuft …";
    }
    if (running) running.hidden = false;
  });

  const output = document.querySelector("[data-diagnostic-output]");
  document.querySelector("[data-copy-diagnostic]")?.addEventListener("click", async (event) => {
    if (!output) return;
    await navigator.clipboard.writeText(output.textContent);
    event.currentTarget.textContent = "Kopiert";
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
})();
