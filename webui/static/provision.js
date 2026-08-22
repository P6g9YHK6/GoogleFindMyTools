document.addEventListener("DOMContentLoaded", () => {
  const signinBtn = document.getElementById("signin-btn");
  if (!signinBtn) return;

  const clearBtn = document.getElementById("clear-btn");

  const panel = document.getElementById("provision-panel");
  const barFill = document.getElementById("provision-bar-fill");
  const messageEl = document.getElementById("provision-message");
  const logEl = document.getElementById("provision-log");
  const vncContainer = document.getElementById("vnc-container");
  const loginStatus = document.getElementById("login-status");

  const ACTIVE_PHASES = ["starting", "installing", "downloading", "extracting", "launching", "ready", "logging_in"];
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
    panel.hidden = false;
    barFill.style.width = `${msg.percent}%`;
    messageEl.textContent = msg.message;
    signinBtn.disabled = ACTIVE_PHASES.includes(msg.phase);
    // Clearing credentials mid-flow wipes state out from under an in-progress
    // sign-in (the server rejects it too, see webui/routers/auth.py, but
    // disabling it here means the button doesn't even offer the footgun).
    if (clearBtn) clearBtn.disabled = ACTIVE_PHASES.includes(msg.phase);

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

    if (msg.phase === "ready" || msg.phase === "logging_in") {
      // Same embedded VNC view serves both the account sign-in ("ready") and
      // the follow-up encryption confirmation ("logging_in") - it's the same
      // display, just a second Chrome window opening on it, so leave an
      // already-shown iframe alone instead of tearing it down and back up.
      if (!vncContainer.dataset.shown) {
        vncContainer.innerHTML =
          "<p>Complete the Google sign-in below:</p>" +
          '<iframe title="Embedded Chrome login" class="vnc-frame" ' +
          'src="/vnc/vnc.html?autoconnect=true&resize=scale&path=websockify"></iframe>';
        vncContainer.dataset.shown = "1";
      }
    } else if (msg.phase === "done") {
      vncContainer.innerHTML = "";
      delete vncContainer.dataset.shown;
      // Pull the real status fragment (username, E2EE confirmation state)
      // instead of a hardcoded "Signed in." that doesn't reflect either.
      // The progress panel's job ends here too - its last message would
      // otherwise sit on screen forever since nothing else ever clears it.
      panel.hidden = true;
      fetch("/auth/status")
        .then(resp => resp.text())
        .then(html => { loginStatus.innerHTML = html; })
        .catch(() => { loginStatus.innerHTML = "<p>Signed in.</p>"; });
    } else if (msg.phase === "error" || msg.phase === "timeout") {
      vncContainer.innerHTML = "";
      delete vncContainer.dataset.shown;
      // Leave the panel visible here (unlike "done") so the error/timeout
      // message stays readable instead of vanishing right when it matters.
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

    try {
      const resp = await fetch("/auth/login/start", { method: "POST" });
      if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
      const data = await resp.json();
      if (data.state) handleUpdate({ type: "provision", ...data.state });
    } catch (e) {
      // Without this, a failed/unparseable response here leaves the button
      // looking like it did nothing at all - show something instead of
      // silence, and leave the button clickable again so retrying doesn't
      // need a page reload.
      handleUpdate({
        phase: "error",
        message: `Couldn't start sign-in: ${e.message}. Check the server logs and try again.`,
        percent: 0,
      });
    }
  });

  // Reflects an already-in-progress setup immediately, e.g. after navigating
  // away from /auth and back (or a plain page refresh) instead of showing a
  // blank page until clicked; keeps polling on its own for as long as the
  // job stays active, see startPolling/stopPolling above.
  pollState();
});
