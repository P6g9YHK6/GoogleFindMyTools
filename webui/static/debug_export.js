document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("debug-export-btn");
  if (!btn) return;

  const passwordInput = document.getElementById("debug-export-password");
  const includeLiveInput = document.getElementById("debug-export-include-live");
  const includeLogsInput = document.getElementById("debug-export-include-logs");
  const anonymizeInput = document.getElementById("debug-export-anonymize");
  const status = document.getElementById("debug-export-status");

  btn.addEventListener("click", async () => {
    if (!includeLiveInput.checked && !includeLogsInput.checked) {
      status.textContent = "Select at least one of Live API query or Recent app logs to export.";
      return;
    }

    btn.disabled = true;
    status.textContent = includeLiveInput.checked
      ? "Generating export (this can take a while while every device is located)..."
      : "Generating export...";

    const body = new URLSearchParams();
    body.set("password", passwordInput.value);
    body.set("include_live_query", includeLiveInput.checked ? "true" : "");
    body.set("include_logs", includeLogsInput.checked ? "true" : "");
    body.set("anonymize_locations", anonymizeInput.checked ? "true" : "");

    try {
      const resp = await fetch("/auth/debug-export", { method: "POST", body });
      if (!resp.ok) {
        let message = `Server returned ${resp.status}`;
        try {
          const data = await resp.json();
          if (data.error) message = data.error;
        } catch (e) {
          // Non-JSON error body - fall back to the plain status message above.
        }
        throw new Error(message);
      }

      const blob = await resp.blob();
      const disposition = resp.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : "gfmt-debug-export.7z";

      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);

      status.textContent = `Export downloaded: ${filename}`;
    } catch (e) {
      status.textContent = `Export failed: ${e.message}`;
    } finally {
      btn.disabled = false;
      // Never leave the password sitting in the DOM/autofill longer than needed.
      passwordInput.value = "";
    }
  });
});
