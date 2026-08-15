// Central place for the backend URL. Change this one line once the Flask API
// is deployed (e.g. to Render) — everything else in the frontend uses it.
const API_BASE = "https://peer-evaluation-ngg4.onrender.com"

// The CSRF token can't be read via document.cookie: that cookie belongs to
// the API's domain (onrender.com), not this page's domain (github.io), and
// document.cookie only ever exposes cookies matching the current page's own
// origin — no amount of waiting or retrying changes that. Instead, the
// backend hands the token to us directly in this endpoint's JSON body (a
// channel CORS *does* let same-origin-approved JS read), and the browser
// still attaches the matching cookie automatically on every request to the
// API regardless of what page the JS is running on — so the two line up.
let csrfTokenPromise = null;
async function getCsrfToken() {
  if (!csrfTokenPromise) {
    csrfTokenPromise = fetch(`${API_BASE}/auth/csrf`, { credentials: "include" })
      .then(res => res.json())
      .then(data => data.csrf_token)
      .catch(err => { csrfTokenPromise = null; throw err; }); // let a later call retry
  }
  return csrfTokenPromise;
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };

  // Double-submit CSRF: attach the token as a header on any state-changing
  // request, so the backend can confirm it matches the cookie the browser
  // sent automatically. A forged cross-site form post can make the browser
  // send our cookies, but can't read the JSON response above to discover
  // the token — so it can't produce a matching header. GET/HEAD are
  // read-only and exempt on the server too.
  if (!["GET", "HEAD"].includes(method)) {
    try {
      const csrfToken = await getCsrfToken();
      if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    } catch (e) { /* let the real request below surface the failure */ }
  }

  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
    headers: { ...headers, ...(options.headers || {}) },
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

/**
 * Wires up a set of dedicated sections (tabs) inside a page.
 * Expects markup:
 *   <div class="section-nav">
 *     <button class="section-nav__item" data-section="groups">Groups</button>
 *     ...
 *   </div>
 *   <div class="section-panel" data-section="groups">...</div>
 *   ...
 * The first nav item is activated by default. Returns a function you can
 * call to switch sections programmatically, e.g. sections("results").
 */
function initSections(root = document) {
  const navItems = [...root.querySelectorAll(".section-nav__item")];
  const panels = [...root.querySelectorAll(".section-panel")];

  function activate(name) {
    navItems.forEach(btn => btn.classList.toggle("is-active", btn.dataset.section === name));
    panels.forEach(panel => panel.classList.toggle("is-active", panel.dataset.section === name));
  }

  navItems.forEach(btn => btn.addEventListener("click", () => activate(btn.dataset.section)));
  if (navItems.length) activate(navItems[0].dataset.section);

  return activate;
}
