// Central place for the backend URL. Change this one line once the Flask API
// is deployed (e.g. to Render) — everything else in the frontend uses it.
const API_BASE = "https://peer-evaluation-eight.vercel.app/";
// this is a new deployment
async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const message = (data && data.error) || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

function showError(el, err) {
  el.textContent = err.message || String(err);
  el.style.display = "block";
}

function hideError(el) {
  el.style.display = "none";
  el.textContent = "";
}

function qs(name) {
  return new URLSearchParams(window.location.search).get(name);
}
