document.addEventListener("DOMContentLoaded", () => {
  const mapEl = document.getElementById("map");
  if (!mapEl) return;

  const map = L.map("map").setView([0, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  // Shown until the devices table's (often slow) load actually reaches the
  // map - see seedMapMarkers and _not_signed_in.html's script.
  window.hideMapLoading = function () {
    document.getElementById("map-loading")?.remove();
  };

  // canonicId -> Map(locationIndex -> L.Marker) - a single device can report
  // more than one location at once (its own report plus a crowd-sourced
  // network estimate, older entries, etc, see decrypt_locations.py), so
  // markers are tracked per location slot rather than one-per-device. Map,
  // not a plain object, so a dynamic canonicId/index can never be read as a
  // prototype-chain key like __proto__.
  const markersByDevice = new Map();

  function markerForKey(key) {
    const sep = key.lastIndexOf(":");
    const canonicId = key.slice(0, sep);
    const index = Number(key.slice(sep + 1));
    return markersByDevice.get(canonicId)?.get(index);
  }

  // Each device gets one base hue, hashed from its canonic_id alone (stable
  // across reloads, independent of how many locations it currently has).
  // Each of that device's individual locations then gets a shade of that
  // same hue, picked from SHADE_LIGHTNESS by its position among the
  // device's dots - so several open locations for one device read as "the
  // same device, different fixes" instead of unrelated colors. Mirrored
  // server-side (identical hash loop + step/shade tables) by
  // webui/colors.py's location_color, so a location's list swatch always
  // matches its map pin.
  const SHADE_LIGHTNESS = [38, 48, 58, 68, 30]; // %, cycles past 5 locations

  // The hash is quantized to a small number of evenly-spaced hues rather
  // than used as a raw mod-360 value: two devices whose IDs happen to hash
  // close together (e.g. 40° apart) would otherwise render as
  // near-identical colors. 12 steps = 30° apart, which stays visually
  // distinct at these lightness levels; devices only share a hue once
  // there are more than 12 of them.
  const HUE_STEPS = 12;

  function hueForDevice(canonicId) {
    let hash = 0;
    for (let i = 0; i < canonicId.length; i++) {
      hash = (Math.imul(hash, 31) + canonicId.charCodeAt(i)) >>> 0;
    }
    return (hash % HUE_STEPS) * (360 / HUE_STEPS);
  }

  function colorForDeviceLocation(canonicId, index) {
    const lightness = SHADE_LIGHTNESS[index % SHADE_LIGHTNESS.length];
    return `hsl(${hueForDevice(canonicId)}, 70%, ${lightness}%)`;
  }

  function pinIcon(color) {
    return L.divIcon({
      className: "device-pin",
      html: `<svg width="25" height="41" viewBox="0 0 25 41" xmlns="http://www.w3.org/2000/svg">
        <path d="M12.5 0C5.6 0 0 5.6 0 12.5 0 21.9 12.5 41 12.5 41S25 21.9 25 12.5C25 5.6 19.4 0 12.5 0z" fill="${color}" stroke="rgba(0,0,0,0.35)" stroke-width="1"/>
        <circle cx="12.5" cy="12.5" r="5" fill="#fff"/>
      </svg>`,
      iconSize: [25, 41],
      iconAnchor: [12, 41],
      popupAnchor: [0, -34],
    });
  }

  function popupLabel(name, loc, source) {
    const bits = [];
    // A semantic reading with mapped coordinates (see
    // webui/forwarders/semantic_map.py) still carries is_own_report=true
    // (hardcoded at decode time, see decrypt_locations.py) - call out its
    // actual semantic name instead, that's the meaningful thing here.
    if (loc.is_semantic) bits.push(loc.semantic_name ? `mapped: ${loc.semantic_name}` : "semantic");
    else if (loc.is_own_report) bits.push("own report");
    else if (loc.status) bits.push(loc.status.toLowerCase());
    if (source) bits.push(source);
    return bits.length ? `${name} (${bits.join(", ")})` : name;
  }

  // Hovering a location's row in the table bounces its map pin; hovering a
  // pin glows its row's text back in the table - each direction just finds
  // the other side via the shared "<canonic_id>:<index>" key and toggles a
  // CSS class, see app.css for the actual animation/glow.
  function bounceMarker(marker, on) {
    const svg = marker.getElement()?.querySelector("svg");
    svg?.classList.toggle("bounce", on);
  }

  function glowRows(key, on) {
    document.querySelectorAll(`[data-loc-key="${CSS.escape(key)}"]`).forEach((el) => {
      el.classList.toggle("loc-glow", on);
    });
  }

  document.addEventListener("mouseover", (e) => {
    const row = e.target.closest("[data-loc-key]");
    if (!row) return;
    const marker = markerForKey(row.dataset.locKey);
    if (marker) bounceMarker(marker, true);
  });
  document.addEventListener("mouseout", (e) => {
    const row = e.target.closest("[data-loc-key]");
    if (!row) return;
    const marker = markerForKey(row.dataset.locKey);
    if (marker) bounceMarker(marker, false);
  });

  // Adds/updates/removes markers for one device's current set of locations,
  // keyed by position in the locations array so each dot keeps its own
  // color and identity across updates. Returns the latlngs it plotted, for
  // callers that need to fit/pan the map to them.
  function upsertDeviceMarkers(canonicId, name, locations, source) {
    const slots = markersByDevice.get(canonicId) || new Map();
    const seenIndexes = new Set();
    const latlngs = [];

    (locations || []).forEach((loc, index) => {
      // A semantic reading with mapped coordinates (see
      // webui/forwarders/semantic_map.py) gets a pin too now - gated on
      // having a latitude at all, not on is_semantic.
      if (loc.latitude == null) return;
      seenIndexes.add(index);

      const latlng = [loc.latitude, loc.longitude];
      const key = `${canonicId}:${index}`;
      const color = colorForDeviceLocation(canonicId, index);
      const label = popupLabel(name, loc, source);

      if (slots.has(index)) {
        slots.get(index).setLatLng(latlng).setPopupContent(label);
      } else {
        const marker = L.marker(latlng, { icon: pinIcon(color) }).addTo(map).bindPopup(label);
        marker.on("mouseover", () => glowRows(key, true));
        marker.on("mouseout", () => glowRows(key, false));
        slots.set(index, marker);
      }
      latlngs.push(latlng);
    });

    // A later update can report fewer locations than before (e.g. the
    // crowd-sourced estimate drops out) - clear any slot that's no longer
    // present instead of leaving a stale dot on the map.
    for (const idx of slots.keys()) {
      if (!seenIndexes.has(idx)) {
        map.removeLayer(slots.get(idx));
        slots.delete(idx);
      }
    }

    markersByDevice.set(canonicId, slots);
    return latlngs;
  }

  // Seeds the map with whatever locations are already on file, so pins show
  // up on page load instead of waiting for a live locate - called by
  // devices/_table.html's inline script once its htmx "load" response
  // (which carries each device's last known locations) lands.
  window.seedMapMarkers = function (devices) {
    const allLatLngs = [];
    for (const device of devices || []) {
      allLatLngs.push(...upsertDeviceMarkers(device.canonic_id, device.name, device.locations, null));
    }
    if (allLatLngs.length === 1) {
      map.setView(allLatLngs[0], 13);
    } else if (allLatLngs.length > 1) {
      map.fitBounds(allLatLngs, { padding: [30, 30] });
    }
    window.hideMapLoading();
  };

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${proto}//${location.host}/ws/locations`);

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type !== "locate_result") return;

      const latlngs = upsertDeviceMarkers(msg.canonic_id, msg.name, msg.locations, msg.source);
      if (latlngs.length) map.panTo(latlngs[latlngs.length - 1]);
    };

    socket.onclose = () => setTimeout(connect, 3000);
  }

  connect();
});

// Live "time until next poll" under the Devices table's "Next poll" column
// (see devices/_table.html's data-next-poll-ts) - deliberately not nested
// inside the #map-guarded block above, since this has nothing to do with
// whether the map itself exists. One shared interval for every row rather
// than one per element, and called fresh (clearing any previous interval)
// each time devices/_table.html's own inline script runs, since that
// fragment - and every data-next-poll-ts element in it - gets replaced
// wholesale on every htmx load of that fragment.
let _nextPollTimer = null;

function _formatCountdown(diffMs) {
  if (diffMs <= 0) return "due now";
  const totalSeconds = Math.floor(diffMs / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `in ${h}h ${m}m`;
  if (m > 0) return `in ${m}m ${s}s`;
  return `in ${s}s`;
}

window.startNextPollCountdowns = function () {
  if (_nextPollTimer) clearInterval(_nextPollTimer);

  function tick() {
    document.querySelectorAll("[data-next-poll-ts]").forEach((el) => {
      const ts = Number(el.dataset.nextPollTs);
      if (!ts) return;
      el.textContent = _formatCountdown(ts * 1000 - Date.now());
    });
  }

  tick();
  _nextPollTimer = setInterval(tick, 1000);
};

// Staleness page: live "Xh Ym ago" under the "Last update" column (see
// staleness/_table.html's data-last-fix-ts) - the inverse of the next-poll
// countdown above, same one-shared-interval-per-page, re-armed-on-every-
// htmx-reload approach. Also listens on the same /ws/locations channel the
// map/devices page already uses (see connect() above) - a locate_result for
// a device shown in this table bumps its row's last-fix timestamp and
// re-derives fresh/stale client-side against the threshold already embedded
// in that row's data attributes (see webui/staleness.py's compute_status,
// which this intentionally mirrors in miniature - just enough to flip a
// badge between "Fresh" and "Stale" without waiting for the next full
// /staleness/table reload; the background sweep, not this, is what still
// actually sends the alert).
let _stalenessAgoTimer = null;

function _formatElapsed(diffMs) {
  if (diffMs <= 0) return "just now";
  const totalSeconds = Math.floor(diffMs / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ago`;
  if (hours > 0) return `${hours}h ${minutes}m ago`;
  if (minutes > 0) return `${minutes}m ago`;
  return `${totalSeconds}s ago`;
}

window.startStalenessAgoTicker = function () {
  if (_stalenessAgoTimer) clearInterval(_stalenessAgoTimer);

  function tick() {
    document.querySelectorAll("[data-last-fix-ts]").forEach((el) => {
      const ts = Number(el.dataset.lastFixTs);
      if (!ts) return;
      el.textContent = _formatElapsed(Date.now() - ts * 1000);
    });
  }

  tick();
  _stalenessAgoTimer = setInterval(tick, 1000);
};

function _updateStalenessRow(canonicId, newestFixTs) {
  const row = document.querySelector(`#staleness-table tr[data-canonic-id="${CSS.escape(canonicId)}"]`);
  if (!row || !newestFixTs) return;

  const agoEl = row.querySelector("[data-last-fix-ts]");
  if (agoEl) agoEl.dataset.lastFixTs = String(newestFixTs);

  const enabled = row.dataset.enabled === "1";
  const muted = row.dataset.muted === "1";
  const thresholdS = Number(row.dataset.thresholdS || 0);
  if (!enabled || muted || !thresholdS) return; // status label for these cases doesn't depend on fix age

  const ageS = Date.now() / 1000 - newestFixTs;
  const statusCell = row.querySelector(".staleness-status");
  if (!statusCell) return;
  statusCell.innerHTML = ageS > thresholdS
    ? '<span class="log-error">Stale</span>'
    : '<span class="log-ok">Fresh</span>';
}

document.addEventListener("DOMContentLoaded", () => {
  if (!document.getElementById("staleness-table")) return;

  const proto = location.protocol === "https:" ? "wss:" : "ws:";

  function connectStalenessSocket() {
    const socket = new WebSocket(`${proto}//${location.host}/ws/locations`);
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type !== "locate_result") return;
      const times = (msg.locations || [])
        .filter((loc) => !loc.is_semantic && loc.time)
        .map((loc) => loc.time);
      if (times.length) _updateStalenessRow(msg.canonic_id, Math.max(...times));
    };
    socket.onclose = () => setTimeout(connectStalenessSocket, 3000);
  }

  connectStalenessSocket();
});

// Devices table photo -> full-size popup (see devices/_table.html's
// .device-thumb-btn and devices/list.html's #device-image-modal) - also
// deliberately not nested inside the #map-guarded block above, same reason
// as the poll countdown just above: nothing to do with the map. Delegated
// off `document` so it keeps working across the table's own htmx reloads
// with no re-init step.
document.addEventListener("click", (event) => {
  const modal = document.getElementById("device-image-modal");
  if (!modal) return;

  const thumbBtn = event.target.closest(".device-thumb-btn");
  if (thumbBtn) {
    modal.querySelector(".image-modal-img").src = thumbBtn.dataset.imageUrl;
    modal.querySelector(".image-modal-img").alt = thumbBtn.dataset.imageLabel || "";
    modal.querySelector(".image-modal-caption").textContent = thumbBtn.dataset.imageLabel || "";
    modal.showModal();
    return;
  }

  // Closes on the x button, or on the dialog's own ::backdrop - a native
  // <dialog>'s backdrop click bubbles with the dialog element itself as
  // the target, which is what the equality check below actually detects
  // (a click landing on the image or caption instead leaves event.target
  // as that inner element, so it's excluded automatically).
  if (event.target.closest(".image-modal-close") || event.target === modal) {
    modal.close();
  }
});
