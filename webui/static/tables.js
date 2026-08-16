// Click-to-sort, drag-to-resize, drag-to-reorder and hide/show for the
// app's real data tables (Devices, Logs - see the "sortable-table" class
// in their templates). Deliberately opt-in via that class rather than
// every <table> in the DOM - the endpoint editor's Headers key/value table
// (settings/_endpoint_fields.html) is editable form input, not browsable
// data, and reordering/resizing it would just fight with its own
// add/remove-row behavior.
//
// Re-runs on every htmx swap, not just DOMContentLoaded, since both the
// Devices and Logs tables load (and reload, e.g. after filtering) via htmx -
// a per-table "already initialized" flag makes that safe to call repeatedly
// without double-binding listeners or losing an in-progress resize.
//
// Column width/order/visibility are persisted to localStorage, keyed by
// each table's data-table-id, so the layout survives a reload instead of
// resetting every time (see loadPrefs/savePrefs/updatePrefs below). Hidden
// columns are applied via a <style> block in <head>, scoped by column
// position rather than by touching the individual <th>/<td> nodes - two
// Devices-table cells (Map, Polled at) get replaced wholesale by htmx
// out-of-band swaps after every Locate click, and any hidden/reordered
// state stashed directly on those specific cells would be lost the next
// time one fires. Position-based hiding sidesteps that entirely.
(() => {
  const PREFS_PREFIX = "tablePrefs:";

  function loadPrefs(tableId) {
    const defaults = { order: [], hidden: [], widths: {} };
    if (!tableId) return defaults;
    try {
      const raw = localStorage.getItem(PREFS_PREFIX + tableId);
      if (!raw) return defaults;
      const parsed = JSON.parse(raw);
      return {
        order: Array.isArray(parsed.order) ? parsed.order : [],
        hidden: Array.isArray(parsed.hidden) ? parsed.hidden : [],
        widths: parsed.widths && typeof parsed.widths === "object" ? parsed.widths : {},
      };
    } catch {
      return defaults; // corrupt/foreign value under this key - fall back rather than throw
    }
  }

  function savePrefs(tableId, prefs) {
    if (!tableId) return;
    try {
      localStorage.setItem(PREFS_PREFIX + tableId, JSON.stringify(prefs));
    } catch {
      // localStorage unavailable (private browsing, quota) - customization
      // just won't survive a reload, not worth surfacing an error for.
    }
  }

  // Load-mutate-save in one step so a resize doesn't clobber a saved
  // order, a reorder doesn't clobber saved widths, etc.
  function updatePrefs(tableId, mutate) {
    if (!tableId) return loadPrefs(tableId);
    const prefs = loadPrefs(tableId);
    mutate(prefs);
    savePrefs(tableId, prefs);
    return prefs;
  }

  function initTables(scope) {
    (scope || document).querySelectorAll("table.sortable-table:not([data-tables-init])").forEach(setupTable);
  }

  function setupTable(table) {
    table.dataset.tablesInit = "1";
    let ths = Array.from(table.querySelectorAll(":scope > thead > tr > th"));
    if (!ths.length) return;

    const tableId = table.dataset.tableId;
    const prefs = loadPrefs(tableId);

    // Reorder before measuring widths, so a saved column order is already
    // in place by the time layout gets pinned below.
    ths = applyOrder(table, ths, prefs.order);

    // Pin every column to its saved width, or its current natural width if
    // it doesn't have one yet, before switching to table-layout:fixed - so
    // opting a table into this doesn't itself cause a visible reflow, only
    // a later drag (resize or reorder) should ever change a width.
    const widths = ths.map((th) => {
      const saved = th.dataset.col && prefs.widths[th.dataset.col];
      return saved || `${th.getBoundingClientRect().width}px`;
    });
    table.style.tableLayout = "fixed";
    ths.forEach((th, i) => {
      th.style.width = widths[i];
      addSortHandle(table, th);
      addResizeHandle(table, th);
      if (tableId) addDragHandle(table, th);
    });

    if (tableId) {
      applyHiddenColumns(table, tableId, prefs.hidden);
      wireColumnsMenu(table, tableId);
    }
  }

  // Reorders the <th>s (and every row's corresponding <td>s) to match a
  // saved list of column keys. Unknown saved keys (a column removed from
  // the template since) are dropped; columns not mentioned in the saved
  // order (new ones added to the template since) keep their server-
  // rendered position instead of being pushed somewhere unexpected.
  // Returns the (possibly reordered) array of <th> elements.
  function applyOrder(table, ths, order) {
    const colKeys = ths.map((th) => th.dataset.col);
    if (!order || !order.length) return ths;

    const known = order.filter((k) => colKeys.includes(k));
    const rest = colKeys.filter((k) => !known.includes(k));
    const finalOrder = known.concat(rest);
    if (finalOrder.join(" ") === colKeys.join(" ")) return ths; // already matches, no DOM churn

    const thByKey = {};
    ths.forEach((th) => (thByKey[th.dataset.col] = th));
    const theadRow = ths[0].parentElement;
    finalOrder.forEach((key) => theadRow.appendChild(thByKey[key])); // appendChild moves an existing node

    const indexByKey = {};
    colKeys.forEach((key, i) => (indexByKey[key] = i));
    table.querySelectorAll(":scope > tbody > tr").forEach((row) => {
      const cells = Array.from(row.children);
      if (cells.length !== colKeys.length) return; // e.g. a colspan "no results" row - nothing to reorder
      finalOrder.forEach((key) => row.appendChild(cells[indexByKey[key]]));
    });

    return finalOrder.map((key) => thByKey[key]);
  }

  function addSortHandle(table, th) {
    const indicator = document.createElement("span");
    indicator.className = "sort-indicator";
    th.appendChild(indicator);

    th.addEventListener("click", (e) => {
      if (e.target.closest(".col-resize-handle, .col-drag-handle")) return; // a resize/reorder drag, not a sort click
      // Computed at click time, not captured at setup - dragging a column
      // to a new position must not leave this pointing at a stale index.
      const colIndex = Array.from(table.querySelectorAll(":scope > thead > tr > th")).indexOf(th);
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

  function addResizeHandle(table, th) {
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

      const tableId = table.dataset.tableId;
      const key = th.dataset.col;
      if (tableId && key) {
        updatePrefs(tableId, (prefs) => {
          prefs.widths[key] = th.style.width;
        });
      }
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

  function addDragHandle(table, th) {
    const handle = document.createElement("span");
    handle.className = "col-drag-handle";
    handle.setAttribute("aria-hidden", "true");
    handle.title = "Drag to reorder";
    th.insertBefore(handle, th.firstChild);

    const onPointerMove = (e) => {
      // closest("th") rather than a direct match, since the point under
      // the cursor is often the sort-indicator or resize-handle span
      // inside a neighboring <th>, not the <th> itself.
      const overTh = document.elementFromPoint(e.clientX, e.clientY)?.closest("th");
      if (!overTh || overTh === th || overTh.parentElement !== th.parentElement) return;
      const rect = overTh.getBoundingClientRect();
      const before = e.clientX < rect.left + rect.width / 2;
      moveColumn(table, th, overTh, before);
    };
    const stopDrag = (e) => {
      handle.releasePointerCapture(e.pointerId);
      handle.removeEventListener("pointermove", onPointerMove);
      handle.removeEventListener("pointerup", stopDrag);
      th.classList.remove("col-dragging");
      document.body.classList.remove("col-reordering");

      const tableId = table.dataset.tableId;
      if (!tableId) return;
      const order = Array.from(table.querySelectorAll(":scope > thead > tr > th")).map((h) => h.dataset.col);
      const prefs = updatePrefs(tableId, (p) => {
        p.order = order;
      });
      // Hidden columns are hidden by visual position (see
      // applyHiddenColumns) - that position just changed.
      applyHiddenColumns(table, tableId, prefs.hidden);
    };

    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation(); // don't also trigger the header's sort click
      th.classList.add("col-dragging");
      document.body.classList.add("col-reordering");
      handle.setPointerCapture(e.pointerId);
      handle.addEventListener("pointermove", onPointerMove);
      handle.addEventListener("pointerup", stopDrag);
    });
  }

  // Moves th (and every row's corresponding <td>) to just before/after
  // targetTh, live during a drag - id-based htmx targeting (e.g. the
  // Devices table's OOB-swapped Map/Polled-at cells) only cares about an
  // element's id, not its position, so this stays compatible with those.
  function moveColumn(table, th, targetTh, before) {
    const theadRow = th.parentElement;
    const fromIndex = Array.from(theadRow.children).indexOf(th);
    const toIndex = Array.from(theadRow.children).indexOf(targetTh);
    if (before) theadRow.insertBefore(th, targetTh);
    else theadRow.insertBefore(th, targetTh.nextSibling);

    table.querySelectorAll(":scope > tbody > tr").forEach((row) => {
      const cells = row.children;
      if (cells.length <= Math.max(fromIndex, toIndex)) return; // e.g. a colspan "no results" row
      const cell = cells[fromIndex];
      const targetCell = cells[toIndex];
      if (before) row.insertBefore(cell, targetCell);
      else row.insertBefore(cell, targetCell.nextSibling);
    });
  }

  // Hides columns by position via a single <style> block in <head>
  // (id table-col-style-<tableId>), rather than a class/style on the
  // individual <th>/<td> nodes - see the top-of-file comment for why
  // (Devices' Map/Polled-at cells get replaced wholesale by htmx OOB
  // swaps, which would silently drop any per-cell hidden state).
  function applyHiddenColumns(table, tableId, hidden) {
    const styleId = `table-col-style-${tableId}`;
    let styleEl = document.getElementById(styleId);
    if (!styleEl) {
      styleEl = document.createElement("style");
      styleEl.id = styleId;
      document.head.appendChild(styleEl);
    }
    if (!hidden || !hidden.length) {
      styleEl.textContent = "";
      return;
    }
    const ths = Array.from(table.querySelectorAll(":scope > thead > tr > th"));
    const rules = ths
      .map((th, i) => (hidden.includes(th.dataset.col) ? i + 1 : null))
      .filter((n) => n !== null)
      .map(
        (n) =>
          `table[data-table-id="${tableId}"] > thead > tr > th:nth-child(${n}), ` +
          `table[data-table-id="${tableId}"] > tbody > tr > td:nth-child(${n}) { display: none; }`
      );
    styleEl.textContent = rules.join("\n");
  }

  // Binds the server-rendered "Columns" checkboxes (see the .table-toolbar
  // markup right before .table-scroll in devices/_table.html and
  // logs/_table.html) to the same hidden-columns state. Lives outside the
  // table itself so it's untouched by htmx's per-cell OOB swaps.
  function wireColumnsMenu(table, tableId) {
    const toolbar = table.closest(".table-scroll")?.previousElementSibling;
    if (!toolbar || !toolbar.classList.contains("table-toolbar")) return;

    const prefs = loadPrefs(tableId);
    const checkboxes = toolbar.querySelectorAll(".columns-menu input[type=checkbox]");
    checkboxes.forEach((cb) => {
      cb.checked = !prefs.hidden.includes(cb.dataset.col);
      cb.addEventListener("change", () => {
        const key = cb.dataset.col;
        const updated = updatePrefs(tableId, (p) => {
          const hiddenSet = new Set(p.hidden);
          if (cb.checked) hiddenSet.delete(key);
          else hiddenSet.add(key);
          p.hidden = Array.from(hiddenSet);
        });
        applyHiddenColumns(table, tableId, updated.hidden);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => initTables(document));
  document.addEventListener("htmx:afterSwap", (e) => initTables(e.detail.target));
})();
