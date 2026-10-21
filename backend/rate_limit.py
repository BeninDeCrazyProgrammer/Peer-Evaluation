"""
Database-backed rate limiter (drop-in replacement for the Flask-Limiter
instance this module used to expose).

Why: on Vercel every cold start or parallel instance is a fresh process, so
Flask-Limiter's in-memory counters reset constantly and the limits on login
and the 4-digit student PIN (only 10,000 combinations) could be sidestepped.
Counters now live in the same Turso database as everything else, so every
instance shares them. No extra service needed.

Usage is unchanged:

    @limiter.limit("8 per 15 minutes", key_func=pin_attempt_key)

`limiter.init_app(app)` is kept as a no-op so app.py doesn't change.

Fixed windows: each (endpoint, limit, key) bucket counts requests inside the
current N-second window and resets when the window rolls over. One atomic
upsert per check, so concurrent requests can't both read the same count.
"""
import functools
import hashlib
import random
import re
import time

from flask import request, jsonify

from db import execute

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_SPEC_RE = re.compile(r"^\s*(\d+)\s+per\s+(\d+)?\s*(second|minute|hour|day)s?\s*$", re.I)


def _parse(spec):
    m = _SPEC_RE.match(spec)
    if not m:
        raise ValueError(f"Unsupported rate limit spec: {spec!r}")
    count = int(m.group(1))
    window = int(m.group(2) or 1) * _UNIT_SECONDS[m.group(3).lower()]
    return count, window


def get_remote_address():
    """
    Client IP. Behind Vercel's proxy request.remote_addr is the proxy, not the
    visitor, which would put every student in one shared bucket — so prefer
    the first X-Forwarded-For entry. A forged header can dodge the per-IP
    limit, but not the per-student limit (pin_attempt_key), which is the one
    that actually protects the PINs.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


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


def _hit(bucket, window):
    """Records one request in `bucket`; returns (count_in_window, seconds_until_reset)."""
    now = int(time.time())
    window_start = now - (now % window)
    result = execute(
        "INSERT INTO rate_limits (bucket, window_start, count) VALUES (?, ?, 1) "
        "ON CONFLICT(bucket) DO UPDATE SET "
        "  count = CASE WHEN window_start = excluded.window_start THEN count + 1 ELSE 1 END, "
        "  window_start = excluded.window_start "
        "RETURNING count",
        [bucket, window_start],
    )
    count = int(result.rows[0][0])
    # Occasional cleanup so the table doesn't grow forever.
    if random.random() < 0.02:
        execute("DELETE FROM rate_limits WHERE window_start < ?", [now - 2 * 86400])
    return count, window_start + window - now


class DBLimiter:
    def init_app(self, app):  # kept for API compatibility with Flask-Limiter
        return None

    def limit(self, spec, key_func=None):
        max_count, window = _parse(spec)
        key_func = key_func or get_remote_address

        def decorator(view):
            @functools.wraps(view)
            def wrapper(*args, **kwargs):
                raw = f"{request.endpoint}|{spec}|{key_func()}"
                bucket = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
                count, retry_after = _hit(bucket, window)
                if count > max_count:
                    response = jsonify({"error": "Too many attempts. Please wait a while and try again."})
                    response.status_code = 429
                    response.headers["Retry-After"] = str(max(retry_after, 1))
                    return response
                return view(*args, **kwargs)
            return wrapper
        return decorator


limiter = DBLimiter()