// Interactivity for one ".endpoint-block" (see
// webui/templates/settings/_endpoint_fields.html): switching which
// destination's fields are shown, syncing the 5-field cron builder with the
// raw cron expression, reflecting the alias field into the block's legend as
// you type, and mirroring the "skip if it hasn't moved" checkbox into its
// always-submitted hidden field. All of this uses event delegation on
// document, so endpoint blocks inserted later via htmx (the "+ Add endpoint"
// button) are covered automatically with no re-init step needed, and neither
// hardcodes which/how many forwarder types exist - a new type just needs its
// fieldset tagged with data-forwarder-type, same as the existing ones.

document.addEventListener("change", (event) => {
  const block = event.target.closest(".endpoint-block");
  if (!block) return;

  if (event.target.matches("select[name='endpoint_type']")) {
    const selected = event.target.value;
    block.querySelectorAll(".destination-fields").forEach((fieldset) => {
      fieldset.style.display = fieldset.dataset.forwarderType === selected ? "" : "none";
    });
  } else if (event.target.classList.contains("skip-toggle")) {
    event.target.closest("label").querySelector("input[type='hidden']").value = event.target.checked ? "1" : "0";
  }
});

document.addEventListener("input", (event) => {
  const block = event.target.closest(".endpoint-block");
  if (!block) return;

  if (event.target.classList.contains("endpoint-alias")) {
    block.querySelector(".endpoint-legend-text").textContent = event.target.value.trim();
  } else if (event.target.classList.contains("cron-field")) {
    const raw = block.querySelector(".cron-raw");
    const fields = block.querySelectorAll(".cron-field");
    raw.value = Array.from(fields).map((f) => f.value.trim() || "*").join(" ");
    raw.classList.remove("cron-invalid");
  } else if (event.target.classList.contains("cron-raw")) {
    const parts = event.target.value.trim().split(/\s+/);
    if (parts.length === 5) {
      block.querySelectorAll(".cron-field").forEach((field, i) => {
        field.value = parts[i];
      });
      event.target.classList.remove("cron-invalid");
    } else {
      event.target.classList.add("cron-invalid");
    }
  }
});
