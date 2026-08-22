// Build-progress half of this page follows webui/static/provision.js almost
// verbatim (websocket + poll backstop over a job state machine) - see that
// file for the reasoning behind the pattern. The WebSerial half below is new.

const ESPTOOL_JS_URL = "https://unpkg.com/esptool-js@0.4.6/bundle.js";

// Maps webui/firmware_build.py's _BOARDS/flasher_args target strings (what the
// server reports as state.built_chip) to esptool-js's ROM.CHIP_NAME strings
// (what loader.chip.CHIP_NAME reads after a real serial ROM sync with the
// connected device) - see the pre-flash chip-mismatch guard below. Add an
// entry here whenever another target is wired into _BOARDS server-side.
const CHIP_NAME_BY_TARGET = {
  esp32: "ESP32",
  esp32c3: "ESP32-C3",
};

// USB vendor IDs of the UART bridge chips actually found on ESP32/ESP32-C3 dev
// boards, passed as requestPort()'s `filters` below - with no filters at all
// the browser's native port picker lists every serial-capable device on the
// system (Bluetooth SPP ports, modems, other boards entirely), which is a lot
// of noise to pick a flashing target out of. Same short list ESPHome's own
// web flasher uses. Doesn't cover every clone board in existence - if yours
// isn't picked up, it's on a chip not in this list (or Firefox's still-new
// Web Serial support not yet recognizing it - see updateFlashAvailability()
// below); the Download .bin + esptool.py fallback always works regardless.
const ESP_USB_FILTERS = [
  { usbVendorId: 0x10c4 }, // Silicon Labs CP210x - most ESP32 DevKits
  { usbVendorId: 0x1a86 }, // WCH CH340/CH341 - many ESP32-CAM boards and clones
  { usbVendorId: 0x0403 }, // FTDI - some ESP32 boards
  { usbVendorId: 0x303a }, // Espressif's own vendor ID - native USB CDC/JTAG on ESP32-C3
];

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
  const connectConsoleBtn = document.getElementById("connect-console-btn");
  const disconnectConsoleBtn = document.getElementById("disconnect-console-btn");
  const rebootBootloaderBtn = document.getElementById("reboot-bootloader-btn");
  const rebootNormalBtn = document.getElementById("reboot-normal-btn");
  const consoleNote = document.getElementById("device-console-note");
  const consoleLogEl = document.getElementById("device-console-log");

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

  // ---- identity presets (webui/registration_presets.py) --------------------
  // Fills in the "Customize identity" fields for a common build (keys, bag,
  // bike, ...) so it's not a blank form by default - purely a client-side
  // convenience, nothing about which preset (if any) was picked is submitted.
  const identityPresetSelect = document.getElementById("identity_preset");
  const identityPresetHint = document.getElementById("identity-preset-hint");
  const displayNameInput = document.getElementById("display_name");
  const deviceTypeSelect = document.getElementById("device_type");
  const manufacturerInput = document.getElementById("manufacturer_name");
  const modelNameInput = document.getElementById("model_name");
  const imageUrlInput = document.getElementById("image_url");
  let identityPresets = {};
  try {
    identityPresets = JSON.parse(document.getElementById("identity-presets-data").textContent);
  } catch (e) {
    // Empty/malformed blob - Preset dropdown just won't fill anything in.
  }

  if (identityPresetSelect) {
    identityPresetSelect.addEventListener("change", () => {
      const preset = identityPresets[identityPresetSelect.value];
      identityPresetHint.textContent = preset ? preset.hint : "";
      if (!preset) return;
      displayNameInput.value = preset.display_name;
      deviceTypeSelect.value = preset.device_type;
      manufacturerInput.value = preset.manufacturer_name;
      modelNameInput.value = preset.model_name;
      imageUrlInput.value = preset.image_url;
    });
  }

  // ---- flash presets (webui/flash_presets.py) ------------------------------
  // Same idea as the identity presets above, but for the Advanced section's
  // build settings (device name, advertising interval, TX power, tracking
  // protection).
  const flashPresetSelect = document.getElementById("flash_preset");
  const flashPresetHint = document.getElementById("flash-preset-hint");
  let flashPresets = {};
  try {
    flashPresets = JSON.parse(document.getElementById("flash-presets-data").textContent);
  } catch (e) {
    // Empty/malformed blob - Preset dropdown just won't fill anything in.
  }

  if (flashPresetSelect) {
    flashPresetSelect.addEventListener("change", () => {
      const preset = flashPresets[flashPresetSelect.value];
      flashPresetHint.textContent = preset ? preset.hint : "";
      if (!preset) return;
      // A deliberately-picked preset should win over the known-EID autofill
      // above, same as the user opening the section by hand would.
      advancedTouchedByUser = true;
      deviceNameInput.value = preset.device_name;
      advIntervalInput.value = preset.adv_interval_ms;
      txPowerSelect.value = String(preset.tx_power_dbm);
      trackingProtectionSelect.value = preset.tracking_protection ? "1" : "0";
    });
  }

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
    panel.hidden = false;
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
      lastBuiltChip = msg.built_chip || null;
      downloadLink.hidden = false;
      downloadLink.setAttribute("download", msg.download_name || "firmware.bin");
      updateFlashAvailability();
    } else {
      downloadLink.hidden = true;
      flashBtn.hidden = true;
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

  // --- WebSerial flashing, rebooting, and live console --------------------
  // Flash / Reboot to Bootloader / Reboot to Normal Mode / the log monitor
  // all coordinate on one shared SerialPort (see acquirePort() below) so the
  // browser's port picker only has to run once per session, and so only one
  // of them ever holds port.readable's reader lock at a time - see
  // stopMonitor() for how each action hands the port back before another
  // one takes it.

  // Which target the last completed build (this tab's own, or one already
  // finished before the page loaded, via pollState() below) was built for -
  // set from state.built_chip, checked against the WebSerial ROM handshake's
  // detected chip right before flashing.
  let lastBuiltChip = null;

  let sharedPort = null;            // the one SerialPort every action coordinates on
  let portReader = null;            // set only while the monitor loop holds port.readable's lock
  let monitorStopRequested = false; // suppresses the "stopped" note on our own handoff cancels
  let consoleBuffer = "";
  const MAX_CONSOLE_CHARS = 200000; // caps memory/DOM size over a long-running session

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // Reuses an already-granted port when there's exactly one, so actions after
  // the first don't re-show the browser's serial port picker.
  async function acquirePort() {
    if (sharedPort) return sharedPort;
    const known = await navigator.serial.getPorts();
    sharedPort = known.length === 1 ? known[0] : await navigator.serial.requestPort({ filters: ESP_USB_FILTERS });
    return sharedPort;
  }

  // Classic ESP32 reset-into-bootloader sequence - the same DTR/RTS toggle
  // esptool-js's own ESPLoader.main() performs internally, reimplemented
  // directly against the raw Web Serial API so entering download mode
  // doesn't require pulling in a full ROM sync/stub upload.
  async function resetToBootloaderMode(port) {
    await port.setSignals({ dataTerminalReady: false, requestToSend: true });
    await sleep(100);
    await port.setSignals({ dataTerminalReady: true, requestToSend: false });
    await sleep(50);
    await port.setSignals({ dataTerminalReady: false });
  }

  // Normal (run-mode) reset - same idea as esptool-js's ESPLoader.hardReset(),
  // but explicit about DTR so it boots the app regardless of what a prior
  // bootloader-entry sequence left DTR set to.
  async function resetToNormalMode(port) {
    await port.setSignals({ dataTerminalReady: false, requestToSend: true });
    await sleep(100);
    await port.setSignals({ requestToSend: false });
  }

  // Flushes consoleBuffer to the DOM at most once per animation frame -
  // startMonitor()'s read() loop below can resolve hundreds of times a
  // second (e.g. a board stuck boot-looping and spamming ROM output), and
  // reassigning a growing textContent on every single chunk was pegging the
  // main thread hard enough to look like a browser crash.
  let consoleFlushPending = false;
  function scheduleConsoleFlush() {
    if (consoleFlushPending) return;
    consoleFlushPending = true;
    requestAnimationFrame(() => {
      consoleFlushPending = false;
      const atBottom = consoleLogEl.scrollTop + consoleLogEl.clientHeight >= consoleLogEl.scrollHeight - 4;
      consoleLogEl.textContent = consoleBuffer;
      if (atBottom) consoleLogEl.scrollTop = consoleLogEl.scrollHeight;
    });
  }

  // Streams sharedPort's raw bytes into the console panel until stopMonitor()
  // cancels it or the port itself errors/disconnects. Not awaited by callers -
  // it runs in the background for as long as the port stays open.
  async function startMonitor() {
    if (portReader || !sharedPort || !sharedPort.readable) return;
    let reader;
    try {
      reader = sharedPort.readable.getReader();
    } catch (e) {
      consoleNote.textContent = `Could not start console: ${e.message || e}`;
      return;
    }
    portReader = reader;
    const decoder = new TextDecoder(); // stateful: handles multi-byte UTF-8 split across chunks
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) {
          consoleBuffer += decoder.decode(value, { stream: true });
          if (consoleBuffer.length > MAX_CONSOLE_CHARS) {
            consoleBuffer = consoleBuffer.slice(consoleBuffer.length - MAX_CONSOLE_CHARS);
          }
          scheduleConsoleFlush();
        }
      }
    } catch (e) {
      if (!monitorStopRequested) consoleNote.textContent = `Console stopped: ${e.message || e}`;
    } finally {
      portReader = null;
      monitorStopRequested = false;
    }
  }

  // Cancels the monitor's in-flight read() (which resolves it as done, so the
  // loop above exits cleanly) so another consumer - a reboot action or the
  // Flash button - can take over the port's reader lock.
  async function stopMonitor() {
    if (!portReader) return;
    monitorStopRequested = true;
    try {
      await portReader.cancel();
    } catch (e) {
      // Already released/disconnected - nothing to clean up.
    }
  }

  async function doReboot(intoBootloader, btn) {
    btn.disabled = true;
    try {
      await stopMonitor();
      const port = await acquirePort();
      if (!port.readable) await port.open({ baudRate: 115200 });
      await (intoBootloader ? resetToBootloaderMode(port) : resetToNormalMode(port));
      consoleNote.textContent = intoBootloader
        ? "Reset into bootloader/flash mode."
        : "Reset into normal mode.";
      startMonitor();
    } catch (e) {
      consoleNote.textContent = `Reboot failed: ${e.message || e}`;
    } finally {
      btn.disabled = false;
    }
  }

  // Opens the port and starts the monitor without touching DTR/RTS - unlike
  // the reboot buttons, this doesn't reset the board, so it picks up
  // whatever's already running (or lets you watch a device that only prints
  // on its own, e.g. one boot-looping on its own bad firmware).
  async function doConnect() {
    connectConsoleBtn.disabled = true;
    try {
      const port = await acquirePort();
      if (!port.readable) await port.open({ baudRate: 115200 });
      consoleNote.textContent = "Connected.";
      startMonitor();
    } catch (e) {
      consoleNote.textContent = `Connect failed: ${e.message || e}`;
    } finally {
      connectConsoleBtn.disabled = false;
    }
  }

  // Stops the monitor and closes the port (but keeps sharedPort's permission
  // grant, so Connect/reboot afterwards don't re-show the port picker) -
  // lets you end the session without power-cycling or resetting the board.
  async function doDisconnect() {
    disconnectConsoleBtn.disabled = true;
    try {
      await stopMonitor();
      if (sharedPort && sharedPort.readable) {
        await sharedPort.close();
      }
      consoleNote.textContent = "Disconnected.";
    } catch (e) {
      consoleNote.textContent = `Disconnect failed: ${e.message || e}`;
    } finally {
      disconnectConsoleBtn.disabled = false;
    }
  }

  // Console/reboot buttons are general debug tools, not gated on having a
  // completed build - kept separate from updateFlashAvailability() below.
  function initDeviceConsole() {
    if (!navigator.serial) {
      connectConsoleBtn.hidden = true;
      disconnectConsoleBtn.hidden = true;
      rebootBootloaderBtn.hidden = true;
      rebootNormalBtn.hidden = true;
      consoleNote.textContent = "Live device console needs the same Web Serial support as flashing above.";
      return;
    }
    connectConsoleBtn.hidden = false;
    disconnectConsoleBtn.hidden = false;
    rebootBootloaderBtn.hidden = false;
    rebootNormalBtn.hidden = false;
    connectConsoleBtn.disabled = false;
    disconnectConsoleBtn.disabled = false;
    rebootBootloaderBtn.disabled = false;
    rebootNormalBtn.disabled = false;
    navigator.serial.addEventListener("disconnect", (event) => {
      if (event.target !== sharedPort) return;
      sharedPort = null;
      portReader = null;
      consoleNote.textContent = "Device disconnected.";
    });
  }

  connectConsoleBtn.addEventListener("click", doConnect);
  disconnectConsoleBtn.addEventListener("click", doDisconnect);
  rebootBootloaderBtn.addEventListener("click", () => doReboot(true, rebootBootloaderBtn));
  rebootNormalBtn.addEventListener("click", () => doReboot(false, rebootNormalBtn));

  function updateFlashAvailability() {
    if (!navigator.serial) {
      flashBtn.hidden = true;
      flashNote.textContent = "In-browser flashing needs a secure context (this page loaded over " +
        "HTTPS, or from localhost) and a browser that supports the Web Serial API (Chrome, Edge, " +
        "or Firefox 151+ - Firefox's support is new as of mid-2026, so it may not yet recognize " +
        "every board's USB-serial chip the way Chrome does). " +
        "Download the .bin above and flash it manually instead, e.g.: " +
        "esptool.py --chip <board> write_flash 0x0 <file>.bin";
      return;
    }
    flashBtn.hidden = false;
    flashBtn.disabled = false;
    flashNote.textContent = "";
  }

  flashBtn.addEventListener("click", async () => {
    flashBtn.disabled = true;
    flashNote.textContent = "Requesting serial port...";
    let transport = null;
    let handedOffToConsole = false;
    try {
      // The console monitor and Transport can't both hold the port open at
      // once - release the monitor's reader lock and close the port first so
      // Transport's own device.open() below doesn't fail on an already-open port.
      await stopMonitor();
      if (sharedPort) {
        try { await sharedPort.close(); } catch (e) {}
      }

      const { ESPLoader, Transport } = await import(ESPTOOL_JS_URL);

      const port = await acquirePort();
      sharedPort = port;
      transport = new Transport(port);
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

      // loader.chip.CHIP_NAME comes from esptool-js's own ROM sync handshake
      // with the physically connected device - a stronger source of truth
      // than trusting the board dropdown or the downloaded file's bytes.
      // Only blocks on a positively confirmed mismatch: if lastBuiltChip is
      // unset/unmapped (e.g. stale state, or a future board not yet added to
      // CHIP_NAME_BY_TARGET), the check is skipped rather than blocking a
      // legitimate flash.
      const detectedChip = loader.chip && loader.chip.CHIP_NAME;
      const expectedChip = CHIP_NAME_BY_TARGET[lastBuiltChip];
      if (expectedChip && detectedChip && detectedChip !== expectedChip) {
        throw new Error(
          `Chip mismatch: this firmware was built for ${expectedChip}, but the connected device ` +
          `identified itself as ${detectedChip}. Build firmware for the ${detectedChip} board instead.`
        );
      }

      flashNote.textContent = detectedChip
        ? `Detected ${detectedChip} - matches built firmware. Downloading...`
        : "Downloading built firmware...";
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

      // esptool-js leaves the chip halted in the bootloader/stub it flashed
      // through - writeFlash() alone never reboots it, so without this the
      // "flashed successfully" message would be a lie: the device stays
      // stuck until someone manually resets or power-cycles it. Reuses the
      // same reset the "Reboot to Normal Mode" button uses, then hands the
      // port to the console monitor so the app's boot log shows up right away.
      flashNote.textContent = "Rebooting into normal mode...";
      await resetToNormalMode(port);
      await transport.disconnect();
      await port.open({ baudRate: 115200 });
      handedOffToConsole = true;
      startMonitor();
      flashNote.textContent = "Flashed and rebooted. The device should now be advertising.";
    } catch (e) {
      flashNote.textContent = `Flashing failed: ${e.message || e}`;
    } finally {
      if (transport && !handedOffToConsole) {
        try { await transport.disconnect(); } catch (e) {}
      }
      flashBtn.disabled = false;
    }
  });

  updateFlashAvailability();
  initDeviceConsole();
});
