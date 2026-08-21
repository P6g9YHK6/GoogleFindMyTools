// Build-progress half of this page follows webui/static/provision.js almost
// verbatim (websocket + poll backstop over a job state machine) - see that
// file for the reasoning behind the pattern. The WebSerial half below is new.

const ESPTOOL_JS_URL = "https://unpkg.com/esptool-js@0.4.6/bundle.js";

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("firmware-build-form");
  if (!form) return;

  const buildBtn = document.getElementById("build-btn");
  const panel = document.getElementById("firmware-build-panel");
  const barFill = document.getElementById("firmware-bar-fill");
  const messageEl = document.getElementById("firmware-message");
  const logEl = document.getElementById("firmware-log");
  const downloadLink = document.getElementById("firmware-download-link");
  const flashBtn = document.getElementById("flash-btn");
  const flashNote = document.getElementById("firmware-flash-note");

  const eidInput = document.getElementById("eid_hex");
  const advancedDetails = document.getElementById("firmware-advanced");
  const deviceNameInput = document.getElementById("device_name");
  const advIntervalInput = document.getElementById("adv_interval_ms");
  const txPowerSelect = document.getElementById("tx_power_dbm");
  const trackingProtectionSelect = document.getElementById("tracking_protection");
  let buildSettingsByEid = {};
  try {
    buildSettingsByEid = JSON.parse(
      document.getElementById("firmware-build-settings-by-eid").textContent);
  } catch (e) {
    // Empty/malformed blob - Advanced section just keeps its defaults.
  }

  // Pre-fills the Advanced section from a previous build's settings for this
  // EID (see webui/firmware_store.py), but only while the user hasn't opened
  // it themselves - once they have, assume they're mid-edit and leave it alone.
  let advancedTouchedByUser = false;
  advancedDetails.addEventListener("toggle", () => {
    if (advancedDetails.open) advancedTouchedByUser = true;
  });

  function applyKnownEidSettings() {
    if (advancedTouchedByUser) return;
    const settings = buildSettingsByEid[eidInput.value.trim().toLowerCase()]
      || buildSettingsByEid[eidInput.value.trim()];
    if (!settings) return;
    deviceNameInput.value = settings.device_name;
    advIntervalInput.value = settings.adv_interval_ms;
    txPowerSelect.value = String(settings.tx_power_dbm);
    trackingProtectionSelect.value = settings.tracking_protection ? "1" : "0";
  }

  eidInput.addEventListener("input", applyKnownEidSettings);
  eidInput.addEventListener("change", applyKnownEidSettings);
  applyKnownEidSettings();

  // Register Tracker and the build form are now one page (see
  // webui/templates/firmware/_register_result.html) - carry a freshly
  // registered EID straight into the build form instead of making the user
  // copy-paste the one-time key shown above.
  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (event.target.id !== "result") return;
    const newEid = document.getElementById("new-eid-hex");
    if (!newEid) return;
    eidInput.value = newEid.textContent.trim();
    applyKnownEidSettings();
  });

  const ACTIVE_PHASES = ["provisioning", "cloning", "installing_toolchain", "preparing", "building", "merging"];
  // Backstops the websocket, same reasoning as provision.js: a dropped/
  // reconnecting socket or a throttled background tab must never leave the
  // page stuck showing stale progress.
  const POLL_INTERVAL_MS = 2000;
  const SOCKET_RETRY_MS = 3000;

  let socket = null;
  let lastPhase = null;
  let pollTimer = null;
  let wantSocket = false;

  function ensureSocket() {
    wantSocket = true;
    if (socket && socket.readyState <= WebSocket.OPEN) return;

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${proto}//${location.host}/ws/firmware`);
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "firmware") handleUpdate(msg);
    };
    socket.onclose = () => {
      if (wantSocket) setTimeout(ensureSocket, SOCKET_RETRY_MS);
    };
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(pollState, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    wantSocket = false;
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function handleUpdate(msg) {
    panel.style.display = "block";
    barFill.style.width = `${msg.percent}%`;
    messageEl.textContent = msg.message;
    buildBtn.disabled = ACTIVE_PHASES.includes(msg.phase);

    if (msg.phase !== lastPhase) {
      const li = document.createElement("li");
      li.textContent = msg.message;
      logEl.appendChild(li);
      lastPhase = msg.phase;
    }

    if (ACTIVE_PHASES.includes(msg.phase)) {
      startPolling();
    } else {
      stopPolling();
    }

    if (msg.phase === "done") {
      downloadLink.style.display = "inline-block";
      downloadLink.setAttribute("download", msg.download_name || "firmware.bin");
      updateFlashAvailability();
    } else {
      downloadLink.style.display = "none";
      flashBtn.style.display = "none";
      flashNote.textContent = "";
    }
  }

  async function pollState() {
    ensureSocket();
    try {
      const resp = await fetch("/firmware/build/poll");
      const state = await resp.json();
      if (state.phase && state.phase !== "idle") {
        handleUpdate({ type: "firmware", ...state });
      } else {
        stopPolling();
      }
    } catch (e) {
      // Network hiccup - next poll tick (or the websocket, once reconnected)
      // drags the page back in sync.
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    logEl.innerHTML = "";
    lastPhase = null;
    ensureSocket();

    const resp = await fetch("/firmware/build/start", {
      method: "POST",
      body: new FormData(form),
    });
    const data = await resp.json();
    if (data.state) handleUpdate({ type: "firmware", ...data.state });
    else if (data.error) messageEl.textContent = data.error;
  });

  // Reflects an already-in-progress or just-finished build immediately on
  // load/refresh instead of showing a blank panel, same as provision.js.
  pollState();

  // --- WebSerial flashing -------------------------------------------------

  function updateFlashAvailability() {
    if (!navigator.serial) {
      flashBtn.style.display = "none";
      flashNote.textContent = "In-browser flashing needs a secure context (this page loaded over " +
        "HTTPS, or from localhost) and a browser that supports the Web Serial API (Chrome/Edge). " +
        "Download the .bin above and flash it manually instead, e.g.: " +
        "esptool.py --chip <board> write_flash 0x0 <file>.bin";
      return;
    }
    flashBtn.style.display = "inline-block";
    flashBtn.disabled = false;
    flashNote.textContent = "";
  }

  flashBtn.addEventListener("click", async () => {
    flashBtn.disabled = true;
    flashNote.textContent = "Requesting serial port...";
    try {
      const { ESPLoader, Transport } = await import(ESPTOOL_JS_URL);

      const port = await navigator.serial.requestPort();
      const transport = new Transport(port);
      const loader = new ESPLoader({
        transport,
        baudrate: 115200,
        terminal: {
          clean() {},
          writeLine: (line) => { flashNote.textContent = line; },
          write: (data) => { flashNote.textContent = data; },
        },
      });

      flashNote.textContent = "Connecting to device...";
      await loader.main();

      flashNote.textContent = "Downloading built firmware...";
      const buf = await (await fetch("/firmware/build/download")).arrayBuffer();
      const binaryStr = Array.from(new Uint8Array(buf), (b) => String.fromCharCode(b)).join("");

      flashNote.textContent = "Flashing... do not disconnect the device.";
      await loader.writeFlash({
        fileArray: [{ data: binaryStr, address: 0x0 }],
        // Without this, esptool-js calls its internal flashSizeBytes(undefined)
        // to sanity-check the image against flash size and throws
        // "Cannot read properties of undefined (reading 'indexOf')". The
        // merged binary already has bootloader/partition/app at the right
        // offsets with flash params baked in by the build, so there's
        // nothing for esptool-js to rewrite here anyway.
        flashSize: "keep",
        // esptool-js's non-compressed write path is unimplemented (it just
        // throws "Yet to handle Non Compressed writes"), so compression is
        // not optional here.
        compress: true,
        reportProgress: (_fileIndex, written, total) => {
          flashNote.textContent = `Flashing... ${Math.round((written / total) * 100)}%`;
        },
      });

      flashNote.textContent = "Flashed successfully. The device should now be advertising.";
    } catch (e) {
      flashNote.textContent = `Flashing failed: ${e.message || e}`;
    } finally {
      flashBtn.disabled = false;
    }
  });

  updateFlashAvailability();
});
