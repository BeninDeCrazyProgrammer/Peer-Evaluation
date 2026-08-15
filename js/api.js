// Central place for the backend URL. Change this one line once the Flask API
// is deployed (e.g. to Render) — everything else in the frontend uses it.
const API_BASE = "https://peer-evaluation-ngg4.onrender.com"

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

// The CSRF cookie is only ever *set* by the backend on a response (see
// csrf.py's after_request hook) — so a browser's very first contact with
// the API, if it happens to be a POST/PUT/PATCH/DELETE (e.g. submitting the
// login form as soon as the page loads), has no cookie yet to echo back and
// gets rejected before one can be minted. Priming with a cheap GET first
// guarantees the cookie exists before any state-changing call needs it.
let csrfPrimed = false;
async function ensureCsrfCookie() {
  if (csrfPrimed || getCookie("csrf_token")) { csrfPrimed = true; return; }
  try {
    await fetch(`${API_BASE}/health`, { credentials: "include" });
  } catch (e) { /* if this fails, the real request below will surface the error */ }
  csrfPrimed = true;
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = options.body instanceof FormData ? {} : { "Content-Type": "application/json" };

  // Double-submit CSRF: echo the csrf_token cookie back as a header on any
  // state-changing request, so the backend can confirm this call actually
  // came from JS running on our own origin (a forged cross-site form post
  // can make the browser send our cookies, but can't read them to produce
  // a matching header). GET/HEAD are read-only and exempt on the server too.
  if (!["GET", "HEAD"].includes(method)) {
    await ensureCsrfCookie();
    const csrfToken = getCookie("csrf_token");
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
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
