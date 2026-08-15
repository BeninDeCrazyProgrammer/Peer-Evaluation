"""
CSRF protection via the double-submit cookie pattern.

Why this is needed: production sets SESSION_COOKIE_SAMESITE="None" (the
frontend on GitHub Pages and the API on Render are different origins, so the
session cookie has to be sendable cross-site or login wouldn't work at all).
CORS stops another origin's JS from *reading* our responses, but it does NOT
stop the browser from *sending* the session cookie on a plain HTML form
submission to us from a malicious page — that's classic CSRF, and CORS was
never meant to prevent it.

Double-submit cookie fixes this without server-side session storage: we set
a second, JS-readable cookie (not httponly) holding a random token. The
frontend reads it and echoes it back as a custom header on every
state-changing request. A malicious page can trigger the browser into
*sending* our cookies, but same-origin policy stops it from *reading* our
cookies to discover the token value — so it can't produce a matching header.

Scope: applied to every POST/PUT/PATCH/DELETE except the `submissions`
blueprint, which is a public, unauthenticated student flow gated by a PIN in
the request body rather than a session cookie — there is no ambient
credential for a forged request to ride, so double-submit protects nothing
there and would just be friction.
"""
import hmac
import secrets

from flask import request, jsonify

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

# Blueprints that don't authenticate via session cookie, so CSRF (which is
# specifically about *cookie-riding*) doesn't apply to them.
EXEMPT_BLUEPRINTS = {"submissions"}


def generate_csrf_token():
    return secrets.token_urlsafe(32)


def ensure_csrf_cookie(response, local_dev):
    """
    after_request hook: makes sure every response carries a CSRF cookie,
    minting one the first time a given browser shows up. Must use the same
    SameSite/Secure policy as the session cookie, or the browser won't send
    it back cross-site either and the whole scheme breaks.
    """
    if not request.cookies.get(CSRF_COOKIE_NAME):
        response.set_cookie(
            CSRF_COOKIE_NAME,
            generate_csrf_token(),
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
