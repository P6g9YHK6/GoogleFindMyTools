// Interactivity for one ".endpoint-block" (see
// webui/templates/settings/_endpoint_fields.html): switching which
// destination's fields are shown, and syncing the 5-field cron builder with
// the raw cron expression. Both use event delegation on document, so
// endpoint blocks inserted later via htmx (the "+ Add endpoint" button) are
// covered automatically with no re-init step needed, and neither hardcodes
// which/how many forwarder types exist - a new type just needs its fieldset
// tagged with data-forwarder-type, same as the existing ones.

document.addEventListener("change", (event) => {
  if (!event.target.matches("select[name='endpoint_type']")) return;
  const block = event.target.closest(".endpoint-block");
  if (!block) return;

  const selected = event.target.value;
  block.querySelectorAll(".destination-fields").forEach((fieldset) => {
    fieldset.style.display = fieldset.dataset.forwarderType === selected ? "" : "none";
  });
});

document.addEventListener("input", (event) => {
  const block = event.target.closest(".endpoint-block");
  if (!block) return;

  if (event.target.classList.contains("cron-field")) {
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
