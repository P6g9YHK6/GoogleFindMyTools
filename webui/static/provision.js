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

  let socket = null;
  let lastPhase = null;

  function ensureSocket() {
    if (socket && socket.readyState <= WebSocket.OPEN) return;

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(`${proto}//${location.host}/ws/provision`);
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "provision") handleUpdate(msg);
    };
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

  async function syncCurrentState() {
    ensureSocket();
    try {
      const resp = await fetch("/auth/login/poll");
      const state = await resp.json();
      if (state.phase && state.phase !== "idle") {
        handleUpdate({ type: "provision", ...state });
      }
    } catch (e) {
      // ignore - live updates will still arrive over the websocket once it's open
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
  // away from /auth and back, instead of showing a blank page until clicked.
  syncCurrentState();
});
