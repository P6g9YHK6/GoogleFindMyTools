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
    status: "CROWDSOURCED", own_report: "false",
    // current_timestamp isn't a fixed sample like the rest of these - it's
    // "right now" by definition, so the preview computes it fresh below
    // instead of hardcoding a value that would just go stale.
    google_timestamp: "1723137600", tracker_id: "a1b2c3d4e5",
    // manufacturer/model/type/image_url and the label_* variables (see
    // BUILTIN_VARIABLES_FROM_FIX/device_label_variables in presets.py) all
    // come from Google's own device-list response, synced into
    // forwarding.yaml at settings-page load time (webui/routers/
    // settings.py's _rows). blockVars() below prefers this device's real
    // synced/reported values (see realValuesFor) wherever it actually has
    // them; everything here is just the fallback for whatever it doesn't.
    manufacturer: "Chipolo", model: "ONE Point", type: "Beacon",
    image_url: "https://example.com/device-photo.png",
    label_carrier: "Vodafone", label_codename: "gauguin", label_imei: "354935091234567",
    label_registered_at: "1723000000", label_shared_with: "family@example.com",
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
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // ---- URL field autosize --------------------------------------------------
  // Height, not just scroll content, tracks .url-autosize's actual text -
  // resetting to "auto" first before reading scrollHeight is what makes it
  // shrink back down too, not just grow (scrollHeight of a still-tall
  // textarea never reports a smaller number).

  function autosizeUrlField(field) {
    if (!field) return;
    field.style.height = "auto";
    field.style.height = field.scrollHeight + "px";
  }

  function autosizeAll(scope) {
    (scope || document).querySelectorAll(".url-autosize").forEach(autosizeUrlField);
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
    if (url) {
      url.textContent = preset.url || "";
      autosizeUrlField(url);
    }

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

  // literal=true keeps a resolved token's own {{name}} text on screen
  // (just colored) instead of swapping in the sample value it resolves
  // to - used by the URL field itself, which edits the template, not a
  // preview of what it produces. The request preview below wants the
  // opposite (literal=false, the default): substituted, so it actually
  // shows "what goes out".
  function renderTemplate(str, vars, literal) {
    const escaped = escapeHtml(str || "");
    return escaped.replace(/\{\{(\w+)\}\}/g, (m, k) => {
      if (Object.prototype.hasOwnProperty.call(vars, k)) {
        const text = literal ? "{{" + k + "}}" : escapeHtml(String(vars[k]));
        return '<span class="tok-resolved">' + text + "</span>";
      }
      return '<span class="tok-unresolved">{{' + k + "}}</span>";
    });
  }

  // Same as renderTemplate(str, vars, true) - always literal, since this
  // is only ever used for the URL field's own edit surface - plus marks
  // the URL's own scheme and host so the request's shape (protocol vs
  // fqdn vs path) is visible at a glance. Splits the raw string into
  // scheme/host/tail first and runs each piece through renderTemplate()
  // on its own, so a {{var}} occurring inside the scheme or host (e.g.
  // "https://{{tracker_id}}.example.com/...") still gets its own nested
  // resolved/unresolved tint. No scheme means nothing typed yet looks
  // like "scheme://" - falls back to plain renderTemplate().
  function renderUrlTemplate(str, vars) {
    const raw = str || "";
    const schemeMatch = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.exec(raw);
    if (!schemeMatch) return renderTemplate(raw, vars, true);
    const scheme = schemeMatch[0];
    const rest = raw.slice(scheme.length);
    const hostMatch = /^[^/?#\s]*/.exec(rest);
    const host = hostMatch ? hostMatch[0] : "";
    const tail = rest.slice(host.length);
    let out = '<span class="tok-scheme">' + renderTemplate(scheme, vars, true) + "</span>";
    if (host) out += '<span class="tok-host">' + renderTemplate(host, vars, true) + "</span>";
    out += renderTemplate(tail, vars, true);
    return out;
  }

  // ---- contenteditable caret bookkeeping ---------------------------------
  // The URL field's own content gets fully rebuilt (innerHTML replaced)
  // every time it's re-highlighted, which would otherwise reset the caret
  // to the start on every keystroke. These convert between a DOM selection
  // and a plain character offset into the field's textContent, so the
  // offset survives a rebuild even though the actual text nodes it points
  // into don't.

  function charOffsetOf(el, node, offset) {
    const range = document.createRange();
    range.selectNodeContents(el);
    range.setEnd(node, offset);
    return range.toString().length;
  }

  // The caret's own offset (the selection's focus end) - null if the
  // field doesn't currently hold the selection at all.
  function getCaretOffset(el) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !el.contains(sel.focusNode)) return null;
    return charOffsetOf(el, sel.focusNode, sel.focusOffset);
  }

  // Both ends of an actual (non-collapsed) selection, low-to-high.
  function getSelectionRange(el) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !el.contains(sel.anchorNode) || !el.contains(sel.focusNode)) return null;
    const a = charOffsetOf(el, sel.anchorNode, sel.anchorOffset);
    const b = charOffsetOf(el, sel.focusNode, sel.focusOffset);
    return a <= b ? [a, b] : [b, a];
  }

  function setCaretOffset(el, offset) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    let remaining = offset;
    let target = null;
    let targetOffset = 0;
    while ((node = walker.nextNode())) {
      if (remaining <= node.length) {
        target = node;
        targetOffset = remaining;
        break;
      }
      remaining -= node.length;
    }
    const range = document.createRange();
    if (target) {
      range.setStart(target, targetOffset);
      range.collapse(true);
    } else {
      range.selectNodeContents(el);
      range.collapse(false);
    }
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  // This device's real last-reported/synced values (see
  // webui/routers/settings.py's _preview_values_json_for), embedded once
  // per device in _device_form.html as a class (not id, since a device
  // block can repeat - see that template's own comment) rather than a
  // page-wide id like #presets-data. Looked up relative to this block's own
  // enclosing form rather than cached at module load, so it stays correct
  // across an htmx swap to a different device's form.
  function realValuesFor(block) {
    const el = block.closest("form")?.querySelector(".device-preview-values");
    if (!el) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return {};
    }
  }

  function blockVars(block) {
    // Real values win per-key over the placeholder, wherever this device
    // actually has them - whatever it doesn't still falls through to
    // SAMPLE_VALUES, so this is never all-or-nothing for one device.
    const vars = Object.assign({}, SAMPLE_VALUES, realValuesFor(block));
    vars.current_timestamp = String(Math.floor(Date.now() / 1000));
    // device_name (the fixed Google account name) and device_alias (the
    // local nickname) are genuinely different values now - see
    // webui/forwarders/custom.py's build_context - rendered into these two
    // data attributes server-side (_endpoint_fields.html) so this preview
    // doesn't need its own copy of that fallback logic.
    vars.device_name = block.dataset.deviceName || block.dataset.deviceAlias || "";
    vars.device_alias = block.dataset.deviceAlias || "";
    const alias = block.querySelector(".endpoint-alias");
    vars.endpoint_alias = (alias && alias.value) || "";
    return vars;
  }

  // Repaints the URL field's own content in place - it's a contenteditable
  // div (see _endpoint_fields.html for why), so what's on screen IS the
  // real value, not a stand-in for it, and this just recolors it through
  // renderUrlTemplate(). Rebuilding innerHTML resets the caret, so it's
  // read before and restored after; skipped entirely if the field isn't
  // the one currently focused (nothing to preserve). The hidden input
  // beside it - the one that actually submits with the form - is kept in
  // sync every time too, focused or not.
  function updateUrlHighlight(field, vars) {
    if (!field) return;
    const plain = field.textContent || "";
    const focused = document.activeElement === field;
    const caret = focused ? getCaretOffset(field) : null;
    field.innerHTML = renderUrlTemplate(plain, vars);
    if (caret != null) setCaretOffset(field, caret);
    const hidden = field.closest(".url-field-wrap")?.querySelector(".url-input-value");
    if (hidden) hidden.value = plain;
  }

  function updatePreview(block) {
    const vars = blockVars(block);
    const urlField = block.querySelector(".url-input");
    updateUrlHighlight(urlField, vars);

    const preview = block.querySelector(".preview-block");
    if (!preview) return;

    const method = (block.querySelector(".method-select") || {}).value || "GET";
    const url = (urlField && urlField.textContent) || "";
    const headers = readKvTable(block, "header");
    const bodyType = (block.querySelector(".body-type-select") || {}).value || "none";
    const bodyText = (block.querySelector(".body-textarea") || {}).value || "";

    // Query params live directly in the URL's own querystring now, not a
    // separate table - the URL field's value already is the full URL.
    const urlHtml = renderTemplate(url || "(no url set)", vars);

    let out = '<span class="method-badge ' + escapeHtml(method.toLowerCase()) + '">' + escapeHtml(method) + "</span>" + urlHtml;

    if (headers.length) {
      out += "\n\n" + '<span class="preview-muted">Headers</span>\n';
      out += headers.map(([k, v]) => "  " + escapeHtml(k) + ": " + renderTemplate(v, vars)).join("\n");
    }

    if (bodyType !== "none" && bodyText.trim()) {
      out += "\n\n" + '<span class="preview-muted">Body (' + escapeHtml(bodyType.toUpperCase()) + ")</span>\n";
      out += renderTemplate(bodyText, vars);
    }

    preview.innerHTML = out;
  }

  // ---- dirty-state / unsaved-changes flag --------------------------------

  // Reflects row.dataset.dirty onto the banner/revert-button - split out
  // from setDirty() below because the banner and revert button both live
  // inside .device-editor, which htmx re-renders from scratch (defaulting
  // the button back to its template's static `hidden`) on every swap that
  // touches it, including ones that don't change the dirty flag itself
  // (e.g. a validation error re-render leaves this device still dirty, but
  // still needs its freshly-inserted revert button un-hidden to match).
  function syncDirtyUi(row) {
    const dirty = row.dataset.dirty === "1";
    const banner = row.querySelector(":scope > .unsaved-banner");
    if (banner) banner.hidden = !dirty;
    const revertBtn = row.querySelector(".btn-revert");
    if (revertBtn) revertBtn.hidden = !dirty;
  }

  function setDirty(row, dirty) {
    row.dataset.dirty = dirty ? "1" : "";
    syncDirtyUi(row);
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
      autosizeAll(block);
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
          // the existing cron-raw input handler below to clear any stale
          // invalid state, and triggers the live preview's own
          // hx-trigger="input" the same way typing would.
          const raw = block.querySelector(".cron-raw");
          raw.value = value;
          raw.dispatchEvent(new Event("input", { bubbles: true }));
        }
      } else if (event.target.classList.contains("skip-toggle")) {
        const hidden = event.target.closest("label")?.querySelector("input[type='hidden']");
        if (hidden) hidden.value = event.target.checked ? "1" : "0";
        applyToggleVisibility(event.target);
        updatePreview(block);
      } else if (event.target.classList.contains("status-choice-toggle")) {
        // Same hidden-input sync as skip-toggle above, minus
        // applyToggleVisibility - these share the "Filter by report type"
        // toggle's own .toggle-group, and aren't a visibility switch
        // themselves (see _endpoint_fields.html's status_choices loop).
        const hidden = event.target.closest("label")?.querySelector("input[type='hidden']");
        if (hidden) hidden.value = event.target.checked ? "1" : "0";
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
    if (event.target.classList.contains("url-autosize")) autosizeUrlField(event.target);
    const block = event.target.closest(".endpoint-block");
    if (block) {
      if (event.target.classList.contains("endpoint-alias")) {
        block.querySelector(".endpoint-legend-text").textContent = event.target.value.trim();
      } else if (event.target.classList.contains("cron-raw")) {
        const parts = event.target.value.trim().split(/\s+/);
        event.target.classList.toggle("cron-invalid", parts.length !== 5);
        syncCronPreset(block);
      }
      // The URL field is a contenteditable div, not an input/textarea (see
      // _endpoint_fields.html) - matched separately here since it wouldn't
      // match either tag.
      if (event.target.matches("input, textarea, [contenteditable]")) updatePreview(block);
    }
    const row = event.target.closest(".device-row");
    if (row && event.target.matches("input, select, textarea, [contenteditable]")) setDirty(row, true);
  });

  // The URL field reads as one flowing (wrapping, autosized) value, not
  // separate lines - a contenteditable div's default Enter behavior splits
  // it into a new <div>/<br>, which .textContent then joins back together
  // with no newline character to show where the split was, silently
  // merging text across the line the user thought they'd made. Blocking
  // Enter and routing paste through the same plain-text splice the
  // variable-chip insert above uses sidesteps both instead of trying to
  // undo whatever the browser already inserted.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches(".url-input[contenteditable]")) {
      event.preventDefault();
    }
  });

  document.addEventListener("paste", (event) => {
    const field = event.target;
    if (!field.matches || !field.matches(".url-input[contenteditable]")) return;
    event.preventDefault();
    const text = (event.clipboardData || window.clipboardData).getData("text/plain");
    const current = field.textContent || "";
    const caret = getCaretOffset(field);
    const [start, end] = getSelectionRange(field) || [caret ?? current.length, caret ?? current.length];
    field.textContent = current.slice(0, start) + text + current.slice(end);
    setCaretOffset(field, start + text.length);
    field.dispatchEvent(new Event("input", { bubbles: true }));
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
      // The YAML editor's own chip row (_device_yaml.html) isn't inside an
      // .endpoint-block - there's no per-endpoint structure or live Preview
      // panel there, just the one .yaml-editor textarea to insert into.
      const field = block
        ? (activeField && block.contains(activeField) ? activeField : block.querySelector(".url-input"))
        : chip.closest(".device-editor")?.querySelector(".yaml-editor");
      if (!field) return;
      if (field.isContentEditable) {
        // The URL field - no selectionStart/value here, insert by
        // character offset instead (see the caret helpers above).
        const text = field.textContent || "";
        const [start, end] = getSelectionRange(field) || [text.length, text.length];
        field.textContent = text.slice(0, start) + token + text.slice(end);
        field.focus();
        setCaretOffset(field, start + token.length);
        if (field.classList.contains("url-autosize")) autosizeUrlField(field);
      } else {
        const start = field.selectionStart ?? field.value.length;
        const end = field.selectionEnd ?? field.value.length;
        field.value = field.value.slice(0, start) + token + field.value.slice(end);
        field.focus();
        const caret = start + token.length;
        field.setSelectionRange(caret, caret);
        if (field.classList.contains("url-autosize")) autosizeUrlField(field);
      }
      if (block) updatePreview(block);
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
      if (block) {
        updatePreview(block);
        autosizeAll(block);
      }
      return;
    }

    if (triggerElt && triggerElt.matches(".btn-add-endpoint")) {
      relabelNewEndpointBlocks(target);
      setDirty(row, true);
      return;
    }

    // Whole-form save, revert, or the YAML view's save/switch: only a
    // render that actually carries a "saved" toast, or a revert (which
    // deliberately throws the in-progress edits away and reloads the
    // last-saved config), means the browser's copy now matches the
    // server - anything else (a validation error re-render, just
    // switching to the YAML view) leaves the unsaved flag as it was.
    const isRevert = triggerElt && triggerElt.matches(".btn-revert");
    if (target.querySelector(".save-toast") || isRevert) {
      setDirty(row, false);
    }
    target.querySelectorAll(".endpoint-block").forEach((block) => {
      updatePreview(block);
      block.querySelectorAll(".skip-toggle").forEach(applyToggleVisibility);
      updateBodyVisibility(block);
    });
    autosizeAll(target);
  });

  // Recompute on resize too, debounced - the field's width (and so how many
  // lines a given URL wraps to) changes with it, e.g. .endpoint-columns
  // going from stacked to side-by-side at wider viewports (see app.css).
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => autosizeAll(document), 100);
  });

  document.querySelectorAll(".endpoint-block").forEach((block) => {
    updatePreview(block);
    block.querySelectorAll(".skip-toggle").forEach(applyToggleVisibility);
    updateBodyVisibility(block);
  });
  autosizeAll(document);
})();
