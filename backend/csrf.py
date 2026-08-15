"""
CSRF protection via double-submit, with the token delivered over JSON
instead of relied on being readable from `document.cookie`.

Why this is needed: production sets SESSION_COOKIE_SAMESITE="None" (the
frontend on GitHub Pages and the API on Render are different origins, so the
session cookie has to be sendable cross-site or login wouldn't work at all).
CORS stops another origin's JS from *reading* our responses, but it does NOT
stop the browser from *sending* the session cookie on a plain HTML form
submission to us from a malicious page — that's classic CSRF, and CORS was
never meant to prevent it.

Classic double-submit has the frontend read the CSRF cookie's value via
`document.cookie` and echo it back as a header. That doesn't work here:
`document.cookie` only exposes cookies whose Domain matches the *current
page's* origin. Our cookie belongs to the API's domain (onrender.com); a
script running on the frontend's domain (github.io) can never see it via
`document.cookie`, no matter when it looks — this isn't a timing/race
problem, it's disallowed by the browser regardless of timing. (The browser
does still *send* that cookie automatically on requests to the API, since
that's governed by the request's target domain, not the script's origin —
so the cookie itself isn't broken, only JS's ability to read it is.)

Fix: GET /auth/csrf (see auth.py) hands the token to the frontend directly
in its JSON response body instead. CORS still protects this — only the
whitelisted frontend origin(s) can read that response body, so a malicious
page can't retrieve the token even though it can make the browser send the
cookie. The frontend keeps the value in memory and sends it as a header on
every state-changing request; the backend checks that header against the
cookie the browser actually attached. Same security property as classic
double-submit (a forged cross-site form post has no way to produce the
matching header), just delivered through a channel that's actually readable
in a cross-origin deployment.

Scope: applied to every POST/PUT/PATCH/DELETE except the `submissions`
blueprint, which is a public, unauthenticated student flow gated by a PIN in
the request body rather than a session cookie — there is no ambient
credential for a forged request to ride, so double-submit protects nothing
there and would just be friction.
"""
import hmac
import secrets

from flask import request, jsonify, g

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Blueprints that don't authenticate via session cookie, so CSRF (which is
# specifically about *cookie-riding*) doesn't apply to them.
EXEMPT_BLUEPRINTS = {"submissions"}


def generate_csrf_token():
    return secrets.token_urlsafe(32)


def get_or_create_csrf_token():
    """
    Returns the current request's CSRF token, generating one if this browser
    doesn't have a cookie yet. Stashed on `g` so a view (see /auth/csrf) can
    hand the *same* value back in its JSON body, and so ensure_csrf_cookie's
    after_request hook sets that exact value as the cookie rather than
    minting an independent one that wouldn't match.
    """
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if not token:
        token = getattr(g, "csrf_token", None) or generate_csrf_token()
        g.csrf_token = token
    return token


def ensure_csrf_cookie(response, local_dev):
    """
    after_request hook: makes sure every response carries a CSRF cookie,
    minting one the first time a given browser shows up. Must use the same
    SameSite/Secure policy as the session cookie, or the browser won't send
    it back cross-site either and the whole scheme breaks.
    """
    if not request.cookies.get(CSRF_COOKIE_NAME):
        token = getattr(g, "csrf_token", None) or generate_csrf_token()
        response.set_cookie(
            CSRF_COOKIE_NAME,
            token,
            httponly=False,  # frontend JS has to be able to read this one
            secure=not local_dev,
            samesite="Lax" if local_dev else "None",
            path="/",
        )
    return response


def csrf_protect():
    """
    before_request hook: rejects state-changing requests whose X-CSRF-Token
    header doesn't match their csrf_token cookie. Register with
    app.before_request(csrf_protect).
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    if request.blueprint in EXEMPT_BLUEPRINTS:
        return None

    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        return jsonify({"error": "Missing or invalid CSRF token. Refresh the page and try again."}), 403
    return None
