// comfyui_curu_auth: send an open ComfyUI tab to the login page when the
// gate rejects its session (spec 005, ADR-009).
//
// After a ComfyUI restart the in-memory sessions are gone. The tab keeps
// polling and opening /ws in the background, and the gate rejects each
// request with HTTP 401. Those requests do not ask for HTML, so the gate
// cannot redirect them. This module sees the rejection and moves the tab.
//
// The gate marks each of its rejections with this header. ComfyUI and
// other nodes do not send it, so their own HTTP 401 never moves the tab.

const LOGIN_PATH = "/curu-auth/login";
const REJECTION_HEADER = "X-Curu-Auth";
const REJECTION_VALUE = "login-required";

const originalFetch = window.fetch.bind(window);

function isGateRejection(response) {
  return response.headers.get(REJECTION_HEADER) === REJECTION_VALUE;
}

function endsAtLogin(response) {
  try {
    return response.redirected && new URL(response.url).pathname === LOGIN_PATH;
  } catch {
    return false;
  }
}

// One move for each page load. The time of the last move is kept for this
// tab only, and a second move within 5 seconds does not occur. A loop can
// occur only if a page loads with a valid session and loses it at once.
const LEFT_AT_KEY = "curu-auth:left-at";
const MOVE_INTERVAL_MS = 5000;
let leaving = false;

function movedRecently(now) {
  try {
    const leftAt = Number(window.sessionStorage.getItem(LEFT_AT_KEY));
    return Number.isFinite(leftAt) && now - leftAt < MOVE_INTERVAL_MS;
  } catch {
    return false;
  }
}

function leave() {
  const now = Date.now();
  if (leaving || movedRecently(now)) {
    return;
  }
  leaving = true;
  try {
    window.sessionStorage.setItem(LEFT_AT_KEY, String(now));
  } catch {
    // Storage can be off. The move still occurs.
  }
  window.location.assign(LOGIN_PATH);
}

window.fetch = async function fetchWithSessionCheck(...args) {
  const response = await originalFetch(...args);
  try {
    if (isGateRejection(response) || endsAtLogin(response)) {
      leave();
    }
  } catch {
    // An error here must never break the page.
  }
  return response;
};

// A browser does not show the status of a failed websocket handshake to
// the page: a gate rejection, a server that is down and a network error
// all close the socket before it opens. So the module asks the gate with
// one probe: a GET of this module itself, a gated route that always
// exists. An answer with the mark moves the tab. A network error means
// the server cannot be reached, and the tab stays.
//
// The frontend opens a new socket each 300 ms after a close. The module
// sends no more than one probe in 2 seconds.

const PROBE_INTERVAL_MS = 2000;
const PROBE_URL = import.meta.url;
const OriginalWebSocket = window.WebSocket;
let lastProbe = -Infinity;

async function probe() {
  const now = Date.now();
  if (now - lastProbe < PROBE_INTERVAL_MS) {
    return;
  }
  lastProbe = now;
  let response;
  try {
    response = await originalFetch(PROBE_URL, {
      cache: "no-store",
      credentials: "same-origin",
    });
  } catch {
    return;
  }
  if (isGateRejection(response)) {
    leave();
  }
}

class SessionCheckedWebSocket extends OriginalWebSocket {
  constructor(...args) {
    super(...args);
    let opened = false;
    this.addEventListener("open", () => {
      opened = true;
    });
    this.addEventListener("close", () => {
      if (!opened) {
        probe().catch(() => {});
      }
    });
  }
}

window.WebSocket = SessionCheckedWebSocket;
