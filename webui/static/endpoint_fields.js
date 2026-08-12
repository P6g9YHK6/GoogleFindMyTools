// Interactivity for the Forwarding Settings page: the generic query-builder
// endpoint block (webui/templates/settings/_endpoint_fields.html) - preset
// switching (only offered on a brand-new, not-yet-saved block), the headers
// key-value table, the body-type textarea, built-in variable-chip
// insertion, a client-only request preview, the cron builder, the
// toggle-gated skip fields, relabeling a freshly-added "+ Add endpoint"
// block's field names to a unique id, and flagging unsaved changes per
// device. Everything is delegated off `document` so blocks inserted later
// via htmx (a new endpoint, a device switching between its form/YAML views)
// are covered automatically with no re-init step, and nothing here
// hardcodes which/how many devices, endpoints or preset types exist - a new
// preset just needs an entry in webui/forwarders/presets.py.

(() => {
  const SAMPLE_VALUES = {
    latitude: "48.8566", longitude: "2.3522", altitude_m: "35", accuracy_m: "12",
    fix_timestamp: "1723137600", tracker_id: "a1b2c3d4e5",
  };

  let PRESETS = {};
  const presetsEl = document.getElementById("presets-data");
  if (presetsEl) {
    try {
      PRESETS = JSON.parse(presetsEl.textContent);
    } catch (e) {
      PRESETS = {};
    }
  }

  const KV_PLACEHOLDERS = {
    header: ["Header name", "Bearer {{token}}"],
  };

  let activeField = null;
  document.addEventListener("focusin", (e) => {
    if (e.target.matches(".templatable")) activeField = e.target;
  });

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ---- key/value rows (headers) ------------------------------------------

  function kvRow(block, kind, key, value) {
    const idx = block.dataset.epIdx;
    const [keyName, valueName] = { header: ["header_key", "header_value"] }[kind];
    const [kp, vp] = KV_PLACEHOLDERS[kind];
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td><input type="text" class="kv-key" name="ep-${idx}-${keyName}" placeholder="${kp}"></td>` +
      `<td><input type="text" class="kv-value templatable" name="ep-${idx}-${valueName}" placeholder="${vp}"></td>` +
      `<td class="kv-remove-cell"><button type="button" class="btn-remove-row" title="Remove row">✕</button></td>`;
    tr.querySelector(".kv-key").value = key || "";
    tr.querySelector(".kv-value").value = value || "";
    return tr;
  }

  function fillKvTable(block, kind, entries) {
    const tbody = block.querySelector(`.kv-body[data-kv="${kind}"]`);
    if (!tbody) return;
    tbody.innerHTML = "";
    Object.entries(entries || {}).forEach(([k, v]) => tbody.appendChild(kvRow(block, kind, k, v)));
  }

  function readKvTable(block, kind) {
    const tbody = block.querySelector(`.kv-body[data-kv="${kind}"]`);
    if (!tbody) return [];
    return Array.from(tbody.querySelectorAll("tr")).map((tr) => [
      tr.querySelector(".kv-key").value.trim(),
      tr.querySelector(".kv-value").value,
    ]).filter(([k]) => k.length > 0);
  }

  // ---- presets ------------------------------------------------------------

  function applyPreset(block, key) {
    const preset = PRESETS[key];
    if (!preset) return;

    const hint = block.querySelector(".preset-hint");
    if (hint) hint.textContent = preset.hint || "";

    const method = block.querySelector(".method-select");
    if (method) method.value = preset.method || "GET";

    const url = block.querySelector(".url-input");
    if (url) url.value = preset.url || "";

    fillKvTable(block, "header", preset.headers);

    const bodyType = block.querySelector(".body-type-select");
    if (bodyType) bodyType.value = preset.body_type || "none";
    const body = block.querySelector(".body-textarea");
    if (body) body.value = preset.body || "";
    updateBodyVisibility(block);
    updatePreview(block);
  }

  function updateBodyVisibility(block) {
    const bodyType = block.querySelector(".body-type-select");
    const body = block.querySelector(".body-textarea");
    if (!bodyType || !body) return;
    body.style.display = bodyType.value === "none" ? "none" : "";
  }

  // ---- toggle-gated fields --------------------------------------------

  function applyToggleVisibility(checkbox) {
    const group = checkbox.closest(".toggle-group");
    const controlled = group && group.querySelector(".toggle-controlled");
    if (controlled) controlled.hidden = !checkbox.checked;
  }

  // ---- schedule preset (distinct from the HTTP-request "preset-select"
  // above - this is the cron "How often" dropdown) --------------------------

  function syncCronPreset(block) {
    const select = block.querySelector(".cron-preset");
    const raw = block.querySelector(".cron-raw");
    if (!select || !raw) return;
    const value = raw.value.trim();
    // Reads the options already rendered by the server (webui/scheduler.py's
    // CRON_PRESETS, via _endpoint_fields.html) rather than keeping a second
    // copy of the preset list in JS - "Custom…" (value="") wins if nothing
    // matches.
    const match = Array.from(select.options).find((o) => o.value === value);
    select.value = match ? match.value : "";
  }

  // ---- request preview (client-only, sample data) -----------------------

  function renderTemplate(str, vars) {
    const escaped = escapeHtml(str || "");
    return escaped.replace(/\{\{(\w+)\}\}/g, (m, k) => {
      if (Object.prototype.hasOwnProperty.call(vars, k)) {
        return '<span class="tok-resolved">' + escapeHtml(String(vars[k])) + "</span>";
      }
      return '<span class="tok-unresolved">{{' + k + "}}</span>";
    });
  }

  function blockVars(block) {
    const vars = Object.assign({}, SAMPLE_VALUES);
    vars.device_name = block.dataset.deviceAlias || "";
    vars.device_alias = block.dataset.deviceAlias || "";
    const alias = block.querySelector(".endpoint-alias");
    vars.endpoint_alias = (alias && alias.value) || "";
    return vars;
  }

  function updatePreview(block) {
    const preview = block.querySelector(".preview-block");
    if (!preview) return;

    const vars = blockVars(block);
    const method = (block.querySelector(".method-select") || {}).value || "GET";
    const url = (block.querySelector(".url-input") || {}).value || "";
    const headers = readKvTable(block, "header");
    const bodyType = (block.querySelector(".body-type-select") || {}).value || "none";
    const bodyText = (block.querySelector(".body-textarea") || {}).value || "";

    // Query params live directly in the URL's own querystring now, not a
    // separate table - the URL field's value already is the full URL.
    const urlHtml = renderTemplate(url || "(no url set)", vars);

    let out = '<span class="method-badge ' + method.toLowerCase() + '">' + method + "</span>" + urlHtml;

    if (headers.length) {
      out += "\n\n" + '<span class="preview-muted">Headers</span>\n';
      out += headers.map(([k, v]) => "  " + escapeHtml(k) + ": " + renderTemplate(v, vars)).join("\n");
    }

    if (bodyType !== "none" && bodyText.trim()) {
      out += "\n\n" + '<span class="preview-muted">Body (' + bodyType.toUpperCase() + ")</span>\n";
      out += renderTemplate(bodyText, vars);
    }

    preview.innerHTML = out;
  }

  // ---- dirty-state / unsaved-changes flag --------------------------------

  function setDirty(row, dirty) {
    row.dataset.dirty = dirty ? "1" : "";
    const banner = row.querySelector(":scope > .unsaved-banner");
    if (banner) banner.hidden = !dirty;
    const anyDirty = document.querySelector('.device-row[data-dirty="1"]');
    window.onbeforeunload = anyDirty ? () => "" : null;
  }

  // ---- relabeling a freshly-added "+ Add endpoint" block -----------------

  let newBlockCounter = 0;

  // Every one of these can carry a literal "__NEW__" that needs swapping to
  // the block's real id: field names (form submission), and the cron
  // preview's id/hx-target/hx-params trio (see _endpoint_fields.html) -
  // without this, the live preview would keep posting to (and asking for)
  // an id that no longer matches anything once relabeled.
  const RELABELED_ATTRS = ["name", "id", "hx-target", "hx-params"];

  function relabelNewEndpointBlocks(scope) {
    scope.querySelectorAll('.endpoint-block[data-ep-idx="__NEW__"]').forEach((block) => {
      const idx = "new" + (++newBlockCounter);
      block.dataset.epIdx = idx;
      RELABELED_ATTRS.forEach((attr) => {
        block.querySelectorAll(`[${attr}]`).forEach((el) => {
          const value = el.getAttribute(attr);
          if (value.includes("__NEW__")) el.setAttribute(attr, value.replace("__NEW__", idx));
        });
      });
      updatePreview(block);
    });
  }

  // ---- event wiring -------------------------------------------------------

  document.addEventListener("change", (event) => {
    const block = event.target.closest(".endpoint-block");
    if (block) {
      if (event.target.matches(".preset-select")) {
        applyPreset(block, event.target.value);
      } else if (event.target.classList.contains("cron-preset")) {
        const value = event.target.value;
        if (value) {
          // "Custom…" (empty value) means "leave whatever's there alone" -
          // only a real preset overwrites the raw field. Dispatching a real
          // input event (rather than setting .value and stopping) reuses
          // the existing cron-raw input handler below to sync the 5-box
          // builder and clear any stale invalid state, and triggers the
          // live preview's own hx-trigger="input" the same way typing would.
          const raw = block.querySelector(".cron-raw");
          raw.value = value;
          raw.dispatchEvent(new Event("input", { bubbles: true }));
        }
      } else if (event.target.classList.contains("skip-toggle")) {
        const hidden = event.target.closest("label")?.querySelector("input[type='hidden']");
        if (hidden) hidden.value = event.target.checked ? "1" : "0";
        applyToggleVisibility(event.target);
        updatePreview(block);
      } else if (event.target.matches(".body-type-select")) {
        updateBodyVisibility(block);
        updatePreview(block);
      } else if (event.target.matches("select, input")) {
        updatePreview(block);
      }
    }
    const row = event.target.closest(".device-row");
    if (row && event.target.matches("input, select, textarea")) setDirty(row, true);
  });

  document.addEventListener("input", (event) => {
    const block = event.target.closest(".endpoint-block");
    if (block) {
      if (event.target.classList.contains("endpoint-alias")) {
        block.querySelector(".endpoint-legend-text").textContent = event.target.value.trim();
      } else if (event.target.classList.contains("cron-field")) {
        const raw = block.querySelector(".cron-raw");
        const fields = block.querySelectorAll(".cron-field");
        raw.value = Array.from(fields).map((f) => f.value.trim() || "*").join(" ");
        raw.classList.remove("cron-invalid");
        syncCronPreset(block);
      } else if (event.target.classList.contains("cron-raw")) {
        const parts = event.target.value.trim().split(/\s+/);
        if (parts.length === 5) {
          block.querySelectorAll(".cron-field").forEach((field, i) => { field.value = parts[i]; });
          event.target.classList.remove("cron-invalid");
        } else {
          event.target.classList.add("cron-invalid");
        }
        syncCronPreset(block);
      }
      if (event.target.matches("input, textarea")) updatePreview(block);
    }
    const row = event.target.closest(".device-row");
    if (row && event.target.matches("input, select, textarea")) setDirty(row, true);
  });

  document.addEventListener("click", (event) => {
    const addBtn = event.target.closest(".btn-add");
    if (addBtn) {
      const block = addBtn.closest(".endpoint-block");
      const row = addBtn.closest(".device-row");
      const tbody = block.querySelector(`.kv-body[data-kv="${addBtn.dataset.target}"]`);
      tbody.appendChild(kvRow(block, addBtn.dataset.target, "", ""));
      updatePreview(block);
      if (row) setDirty(row, true);
      return;
    }

    if (event.target.matches(".btn-remove-row")) {
      const block = event.target.closest(".endpoint-block");
      const row = event.target.closest(".device-row");
      event.target.closest("tr").remove();
      if (block) updatePreview(block);
      if (row) setDirty(row, true);
      return;
    }

    if (event.target.matches(".btn-remove")) {
      const block = event.target.closest(".endpoint-block");
      const row = event.target.closest(".device-row");
      if (block) block.remove();
      if (row) setDirty(row, true);
      return;
    }

    const chip = event.target.closest(".chip");
    if (chip) {
      const block = chip.closest(".endpoint-block");
      const token = "{{" + chip.dataset.var + "}}";
      const field = activeField && block.contains(activeField) ? activeField : block.querySelector(".url-input");
      if (!field) return;
      const start = field.selectionStart ?? field.value.length;
      const end = field.selectionEnd ?? field.value.length;
      field.value = field.value.slice(0, start) + token + field.value.slice(end);
      field.focus();
      const caret = start + token.length;
      field.setSelectionRange(caret, caret);
      updatePreview(block);
      const row = chip.closest(".device-row");
      if (row) setDirty(row, true);
    }
  });

  document.addEventListener("htmx:afterSwap", (event) => {
    const target = event.detail.target;
    const triggerElt = event.detail.elt;
    const row = target.closest(".device-row") || (target.matches(".device-row") ? target : null);
    if (!row) return;

    // "Send now" - a server-driven status update to one endpoint block, not
    // a user edit; leave the dirty flag exactly as it was. detail.elt (the
    // button that made the request) is used rather than detail.target here,
    // since an outerHTML swap's target can end up pointing at either the
    // old or the new element depending on htmx version.
    if (triggerElt && triggerElt.matches(".btn-send-now")) {
      const block = target.matches(".endpoint-block") ? target : target.querySelector(".endpoint-block");
      if (block) updatePreview(block);
      return;
    }

    if (triggerElt && triggerElt.matches(".btn-add-endpoint")) {
      relabelNewEndpointBlocks(target);
      setDirty(row, true);
      return;
    }

    // Whole-form save, or the YAML view's save/switch: only a render that
    // actually carries a "saved" toast represents data now matching the
    // server, anything else (a validation error re-render, just switching
    // to the YAML view) leaves the unsaved flag as it was.
    if (target.querySelector(".save-toast")) {
      setDirty(row, false);
    }
    target.querySelectorAll(".endpoint-block").forEach((block) => {
      updatePreview(block);
      block.querySelectorAll(".skip-toggle").forEach(applyToggleVisibility);
      updateBodyVisibility(block);
    });
  });

  document.querySelectorAll(".endpoint-block").forEach((block) => {
    updatePreview(block);
    block.querySelectorAll(".skip-toggle").forEach(applyToggleVisibility);
    updateBodyVisibility(block);
  });
})();
