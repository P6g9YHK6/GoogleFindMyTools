document.addEventListener("DOMContentLoaded", () => {
  const mapEl = document.getElementById("map");
  if (!mapEl) return;

  const map = L.map("map").setView([0, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  // canonicId -> { [locationIndex]: L.Marker } - a single device can report
  // more than one location at once (its own report plus a crowd-sourced
  // network estimate, older entries, etc, see decrypt_locations.py), so
  // markers are tracked per location slot rather than one-per-device.
  const markersByDevice = {};

  // Colors are assigned per location dot, not per device (a device with
  // several open dots would otherwise be a single color repeated), and the
  // dot count is unbounded, so this generates from a hash instead of
  // indexing into a small fixed palette. Fixed saturation/lightness keeps
  // every generated hue legible on the light OSM tiles and readable against
  // the white center dot.
  function colorForKey(key) {
    let hash = 0;
    for (let i = 0; i < key.length; i++) {
      hash = (Math.imul(hash, 31) + key.charCodeAt(i)) >>> 0;
    }
    const hue = hash % 360;
    return `hsl(${hue}, 72%, 40%)`;
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
    if (loc.is_own_report) bits.push("own report");
    else if (loc.status) bits.push(loc.status.toLowerCase());
    if (source) bits.push(source);
    return bits.length ? `${name} (${bits.join(", ")})` : name;
  }

  // Adds/updates/removes markers for one device's current set of locations,
  // keyed by position in the locations array so each dot keeps its own
  // color and identity across updates. Returns the latlngs it plotted, for
  // callers that need to fit/pan the map to them.
  function upsertDeviceMarkers(canonicId, name, locations, source) {
    const slots = markersByDevice[canonicId] || {};
    const seenIndexes = new Set();
    const latlngs = [];

    (locations || []).forEach((loc, index) => {
      if (loc.is_semantic || loc.latitude == null) return;
      seenIndexes.add(index);

      const latlng = [loc.latitude, loc.longitude];
      const color = colorForKey(`${canonicId}:${index}`);
      const label = popupLabel(name, loc, source);

      if (slots[index]) {
        slots[index].setLatLng(latlng).setPopupContent(label);
      } else {
        slots[index] = L.marker(latlng, { icon: pinIcon(color) }).addTo(map).bindPopup(label);
      }
      latlngs.push(latlng);
    });

    // A later update can report fewer locations than before (e.g. the
    // crowd-sourced estimate drops out) - clear any slot that's no longer
    // present instead of leaving a stale dot on the map.
    for (const indexStr of Object.keys(slots)) {
      if (!seenIndexes.has(Number(indexStr))) {
        map.removeLayer(slots[indexStr]);
        delete slots[indexStr];
      }
    }

    markersByDevice[canonicId] = slots;
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
