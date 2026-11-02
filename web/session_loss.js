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

function leave() {
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
