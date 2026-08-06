// Two-way sync between the 5-field cron builder and the raw cron expression
// input inside each ".endpoint-block". Uses event delegation on document so
// endpoint blocks inserted later via htmx (the "+ Add endpoint" button) are
// covered automatically, with no re-init step needed.
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
