import os
import hmac
from flask import Blueprint, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from models import Lecturer as LecturerModel
from rate_limit import limiter
from csrf import get_or_create_csrf_token

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
login_manager = LoginManager()


class LecturerSession(UserMixin):
    """Flask-Login's view of a lecturer — wraps the Lecturer model row."""
    def __init__(self, lecturer):
        self.id = lecturer.id
        self.name = lecturer.name
        self.email = lecturer.email


def init_auth(app):
    login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    lecturer = LecturerModel.find(user_id)
    return LecturerSession(lecturer) if lecturer else None


def _check_system_key(submitted):
    expected = os.environ.get("SYSTEM_KEY")
    if not expected:
        # Misconfiguration, not an open door: if no key is set on the server,
        # registration is closed rather than silently unprotected.
        return False
    # Constant-time comparison — plain == short-circuits on the first
    # mismatched byte, which leaks (via response timing) how many leading
    # characters of a guess are correct. Low-value secret, but free to fix.
    return hmac.compare_digest((submitted or "").strip(), expected)


@auth_bp.route("/csrf")
def csrf_token():
    """
    The frontend can't read the csrf_token cookie via document.cookie (it
    belongs to this API's domain, not the frontend's — see csrf.py's module
    docstring), so it fetches the value here instead, over a channel CORS
    actually lets it read. Called once per page load before the first
    state-changing request.
    """
    return jsonify({"csrf_token": get_or_create_csrf_token()})


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("5 per hour")
def register():
    data = request.get_json(force=True)
    name, email, password = data.get("name"), data.get("email"), data.get("password")
    system_key = data.get("system_key")
    if not all([name, email, password]):
        return jsonify({"error": "name, email and password are all required"}), 400
    if not _check_system_key(system_key):
        return jsonify({"error": "Invalid system key. Ask your department admin for the current key."}), 403

    if LecturerModel.exists(email=email):
        return jsonify({"error": "An account with that email already exists"}), 409

    LecturerModel.create(name=name, email=email, password_hash=generate_password_hash(password))
    return jsonify({"message": "Account created — you can now log in"}), 201


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per 5 minutes")
def login():
    data = request.get_json(force=True)
    email, password = data.get("email"), data.get("password")
    lecturer = LecturerModel.first(email=email)
    if not lecturer or not lecturer.password_hash or not check_password_hash(lecturer.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    login_user(LecturerSession(lecturer))
    return jsonify({"message": "Logged in", "name": lecturer.name, "email": lecturer.email})


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("5 per hour")
def reset_password():
    """
    Body: {email, system_key, new_password}
    This app has no email-sending infrastructure, so there's no "click the
    link we emailed you" reset flow. Instead, a lecturer who's forgotten
    their password proves they still belong to the department the same way
    they proved it at registration — the shared system key — and sets a new
    password directly. That means anyone who knows the department's system
    key AND a colleague's email could reset that colleague's password; this
    isn't a new trust boundary though, it's the exact same one registration
    already relies on (the key is what gates who can create an account at
    all) — this just extends it to resets instead of introducing a weaker one.
    """
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    system_key = data.get("system_key")
    new_password = data.get("new_password")

    if not email or not new_password:
        return jsonify({"error": "Email and new password are required"}), 400
    if not _check_system_key(system_key):
        return jsonify({"error": "Invalid system key. Ask your department admin for the current key."}), 403

    lecturer = LecturerModel.first(email=email)
    if not lecturer:
        return jsonify({"error": "No account found with that email"}), 404

    lecturer.update(password_hash=generate_password_hash(new_password))
    return jsonify({"message": "Password updated — you can now log in with your new password"})


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out"})


@auth_bp.route("/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})
    return jsonify({"authenticated": True, "name": current_user.name, "email": current_user.email})
