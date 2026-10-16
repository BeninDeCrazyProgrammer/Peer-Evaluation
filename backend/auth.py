import os
from flask import Blueprint, request, jsonify, redirect, url_for, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth

from db import execute

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
login_manager = LoginManager()
oauth = OAuth()


class Lecturer(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]


def init_auth(app):
    login_manager.init_app(app)
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


@login_manager.user_loader
def load_user(user_id):
    rs = execute("SELECT id, name, email FROM lecturers WHERE id = ?", [user_id])
    if not rs.rows:
        return None
    return Lecturer(dict(zip(rs.columns, rs.rows[0])))


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    name, email, password = data.get("name"), data.get("email"), data.get("password")
    if not all([name, email, password]):
        return jsonify({"error": "name, email and password are all required"}), 400

    existing = execute("SELECT id FROM lecturers WHERE email = ?", [email])
    if existing.rows:
        return jsonify({"error": "An account with that email already exists"}), 409

    password_hash = generate_password_hash(password)
    execute(
        "INSERT INTO lecturers (name, email, password_hash) VALUES (?, ?, ?)",
        [name, email, password_hash],
    )
    return jsonify({"message": "Account created — you can now log in"}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email, password = data.get("email"), data.get("password")
    rs = execute("SELECT id, name, email, password_hash FROM lecturers WHERE email = ?", [email])
    if not rs.rows:
        return jsonify({"error": "Invalid email or password"}), 401

    row = dict(zip(rs.columns, rs.rows[0]))
    if not row["password_hash"] or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    login_user(Lecturer(row))
    return jsonify({"message": "Logged in", "name": row["name"], "email": row["email"]})


@auth_bp.route("/google/start")
def google_start():
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/google/callback")
def google_callback():
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or {}
    google_id, email, name = userinfo.get("sub"), userinfo.get("email"), userinfo.get("name")
    if not email:
        return jsonify({"error": "Google did not return an email address"}), 400

    rs = execute("SELECT id, name, email FROM lecturers WHERE google_id = ? OR email = ?", [google_id, email])
    if rs.rows:
        row = dict(zip(rs.columns, rs.rows[0]))
        execute("UPDATE lecturers SET google_id = ? WHERE id = ?", [google_id, row["id"]])
    else:
        execute(
            "INSERT INTO lecturers (name, email, google_id) VALUES (?, ?, ?)",
            [name or email, email, google_id],
        )
        rs = execute("SELECT id, name, email FROM lecturers WHERE google_id = ?", [google_id])
        row = dict(zip(rs.columns, rs.rows[0]))

    login_user(Lecturer(row))
    frontend_url = os.environ.get("FRONTEND_URL", "/")
    return redirect(f"{frontend_url}/lecturer/dashboard.html")


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
