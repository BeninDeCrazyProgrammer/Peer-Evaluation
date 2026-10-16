"""
Shared Flask-Limiter instance.

Login, registration, and the student PIN endpoints (identify/claim-pin/lookup/
submit) are unauthenticated by design — anyone with the link can hit them.
Without limits, a 4-digit student PIN is only 10,000 combinations and is
brute-forceable in well under a minute at LAN speed. Rate limiting lives in
its own module (not app.py) so route files like auth.py and submissions.py
can import `limiter` without importing app.py and creating a circular import
— app.py is the one that calls limiter.init_app(app).

Storage: in-memory by default, which is fine for a single-process deploy
(e.g. one Render web service instance) but does NOT share counters across
multiple processes/dynos — with more than one worker, each process enforces
the limit independently, so the *effective* limit is (configured limit) x
(number of processes). If this ever runs with more than one worker, set
RATE_LIMIT_STORAGE_URI to a shared backend (e.g. a Redis URL).
"""
import os
from flask import request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://"),
)


def pin_attempt_key():
    """
    Per-identity limit key for PIN-guessing endpoints: keyed on the specific
    student identifier being targeted within a course/evaluation, not just
    the caller's IP — an attacker can rotate IPs but not the identifier
    they're trying to guess a PIN for. Routes stack this alongside a plain
    per-IP limit (the default key_func) so both a targeted attack on one
    student and a broad sweep across many identifiers from one IP get caught.
    """
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or "").strip().lower()
    course_id = request.view_args.get("course_id") if request.view_args else None
    evaluation_id = request.view_args.get("evaluation_id") if request.view_args else None
    return f"{course_id}:{evaluation_id}:{identifier}"
