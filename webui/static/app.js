document.addEventListener("DOMContentLoaded", () => {
  const mapEl = document.getElementById("map");
  if (!mapEl) return;

  const map = L.map("map").setView([0, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  const markers = {};

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${proto}//${location.host}/ws/locations`);

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type !== "locate_result") return;

      for (const loc of msg.locations || []) {
        if (loc.is_semantic || loc.latitude == null) continue;

        const key = msg.canonic_id;
        const latlng = [loc.latitude, loc.longitude];

        if (markers[key]) {
          markers[key].setLatLng(latlng);
        } else {
          markers[key] = L.marker(latlng).addTo(map);
        }
        markers[key].bindPopup(`${msg.name} (${msg.source})`);
        map.panTo(latlng);
      }
    };

    socket.onclose = () => setTimeout(connect, 3000);
  }

  connect();
});
