import os
import hmac
from flask import Blueprint, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from models import Lecturer as LecturerModel
from rate_limit import limiter

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
