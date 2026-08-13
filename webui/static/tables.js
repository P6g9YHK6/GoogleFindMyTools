// Click-to-sort + drag-to-resize columns for the app's real data tables
// (Devices, Logs - see the "sortable-table" class in their templates).
// Deliberately opt-in via that class rather than every <table> in the DOM -
// the endpoint editor's Headers key/value table (settings/_endpoint_fields.html)
// is editable form input, not browsable data, and reordering/resizing it
// would just fight with its own add/remove-row behavior.
//
// Re-runs on every htmx swap, not just DOMContentLoaded, since both the
// Devices and Logs tables load (and reload, e.g. after filtering) via htmx -
// a per-table "already initialized" flag makes that safe to call repeatedly
// without double-binding listeners or losing an in-progress resize.
(() => {
  function initTables(scope) {
    (scope || document).querySelectorAll("table.sortable-table:not([data-tables-init])").forEach(setupTable);
  }

  function setupTable(table) {
    table.dataset.tablesInit = "1";
    const ths = Array.from(table.querySelectorAll(":scope > thead > tr > th"));
    if (!ths.length) return;

    // Pin every column to its current natural width before switching to
    // table-layout:fixed, so opting a table into this doesn't itself cause
    // a visible reflow - only a later drag should ever change a width.
    const widths = ths.map((th) => th.getBoundingClientRect().width);
    table.style.tableLayout = "fixed";
    ths.forEach((th, i) => {
      th.style.width = `${widths[i]}px`;
      addSortHandle(table, th, i);
      addResizeHandle(th);
    });
  }

  function addSortHandle(table, th, colIndex) {
    const indicator = document.createElement("span");
    indicator.className = "sort-indicator";
    th.appendChild(indicator);

    th.addEventListener("click", (e) => {
      if (e.target.closest(".col-resize-handle")) return; // a resize drag, not a sort click
      sortByColumn(table, colIndex, th);
    });
  }

  function sortByColumn(table, colIndex, th) {
    const tbody = table.querySelector(":scope > tbody");
    const rows = Array.from(tbody.querySelectorAll(":scope > tr"));
    if (rows.length < 2) return; // nothing to reorder (incl. the single "no results" row)

    const nextDir = th.dataset.sortDir === "asc" ? "desc" : "asc";
    table.querySelectorAll(":scope > thead > tr > th").forEach((h) => {
      delete h.dataset.sortDir;
      h.querySelector(".sort-indicator").textContent = "";
    });
    th.dataset.sortDir = nextDir;
    th.querySelector(".sort-indicator").textContent = nextDir === "asc" ? " ▲" : " ▼";

    const valueOf = (row) => (row.children[colIndex]?.textContent || "").trim();
    // {numeric: true} makes this do the right thing for plain numbers,
    // zero-padded "YYYY-MM-DD HH:MM:SS" timestamps (already sort correctly
    // as plain text, since they're fixed-width and most-significant-first),
    // and mixed text-with-numbers (e.g. "Endpoint 2" before "Endpoint 10")
    // alike - one comparison rule for every column instead of guessing
    // each one's data type up front.
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
    rows.sort((a, b) => collator.compare(valueOf(a), valueOf(b)));
    if (nextDir === "desc") rows.reverse();

    rows.forEach((row) => tbody.appendChild(row));
  }

  function addResizeHandle(th) {
    const handle = document.createElement("span");
    handle.className = "col-resize-handle";
    handle.setAttribute("aria-hidden", "true");
    th.appendChild(handle);

    let startX = 0;
    let startWidth = 0;

    const onPointerMove = (e) => {
      th.style.width = `${Math.max(48, startWidth + (e.clientX - startX))}px`;
    };
    const stopResize = (e) => {
      handle.releasePointerCapture(e.pointerId);
      handle.removeEventListener("pointermove", onPointerMove);
      handle.removeEventListener("pointerup", stopResize);
      document.body.classList.remove("col-resizing");
    };

    // Pointer Events (not separate mouse/touch listeners) so mouse, touch
    // and pen all drag the same way with one code path - setPointerCapture
    // routes every subsequent move/up here regardless of where the pointer
    // physically ends up, so no document-level listeners are needed either.
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation(); // don't also trigger the header's sort click
      startX = e.clientX;
      startWidth = th.getBoundingClientRect().width;
      document.body.classList.add("col-resizing");
      handle.setPointerCapture(e.pointerId);
      handle.addEventListener("pointermove", onPointerMove);
      handle.addEventListener("pointerup", stopResize);
    });
  }

  document.addEventListener("DOMContentLoaded", () => initTables(document));
  document.addEventListener("htmx:afterSwap", (e) => initTables(e.detail.target));
})();
