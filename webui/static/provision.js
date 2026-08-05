document.addEventListener("DOMContentLoaded", () => {
  const signinBtn = document.getElementById("signin-btn");
  if (!signinBtn) return;

  const panel = document.getElementById("provision-panel");
  const barFill = document.getElementById("provision-bar-fill");
  const messageEl = document.getElementById("provision-message");
  const logEl = document.getElementById("provision-log");
  const vncContainer = document.getElementById("vnc-container");
  const loginStatus = document.getElementById("login-status");

  const ACTIVE_PHASES = ["starting", "installing", "downloading", "extracting", "launching", "ready"];
  // Backstops the websocket: as long as a job looks active we keep polling
  // /auth/login/poll too, so a dropped/reconnecting socket (or a tab that was
  // backgrounded and throttled) can never leave the page stuck showing stale
  // progress - the next poll tick always drags it back in sync with the
  // server's actual state.
  const POLL_INTERVAL_MS = 2000;
  // How long to wait before retrying a dropped websocket, so a reconnect
  // storm can't pile up if the server is briefly unreachable.
  const SOCKET_RETRY_MS = 3000;

  let socket = null;
  let lastPhase = null;
  let pollTimer = null;
  let wantSocket = false;

  function ensureSocket() {
    wantSocket = true;
    if (socket && socket.readyState <= WebSocket.OPEN) return;

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${proto}//${location.host}/ws/provision`);
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "provision") handleUpdate(msg);
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
    signinBtn.disabled = ACTIVE_PHASES.includes(msg.phase);

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

    if (msg.phase === "ready") {
      if (!vncContainer.dataset.shown) {
        vncContainer.innerHTML =
          "<p>Complete the Google sign-in below:</p>" +
          '<iframe title="Embedded Chrome login" ' +
          'src="/vnc/vnc.html?autoconnect=true&resize=scale&path=websockify" ' +
          'style="width:100%; height:600px; border:1px solid #ccc;"></iframe>';
        vncContainer.dataset.shown = "1";
      }
    } else if (msg.phase === "done") {
      vncContainer.innerHTML = "";
      delete vncContainer.dataset.shown;
      loginStatus.innerHTML = "<p>Signed in.</p>";
    } else if (msg.phase === "error" || msg.phase === "timeout") {
      vncContainer.innerHTML = "";
      delete vncContainer.dataset.shown;
    }
  }

  async function pollState() {
    ensureSocket();
    try {
      const resp = await fetch("/auth/login/poll");
      const state = await resp.json();
      if (state.phase && state.phase !== "idle") {
        handleUpdate({ type: "provision", ...state });
      } else {
        // Nothing in flight - no need to keep polling until sign-in is
        // started again (handleUpdate will restart it via startPolling).
        stopPolling();
      }
    } catch (e) {
      // Network hiccup - the next poll tick (or the websocket, once it
      // reconnects) will drag the page back in sync.
    }
  }

  signinBtn.addEventListener("click", async () => {
    logEl.innerHTML = "";
    lastPhase = null;
    ensureSocket();

    const resp = await fetch("/auth/login/start", { method: "POST" });
    const data = await resp.json();
    if (data.state) handleUpdate({ type: "provision", ...data.state });
  });

  // Reflects an already-in-progress setup immediately, e.g. after navigating
  // away from /auth and back (or a plain page refresh) instead of showing a
  // blank page until clicked; keeps polling on its own for as long as the
  // job stays active, see startPolling/stopPolling above.
  pollState();
});
