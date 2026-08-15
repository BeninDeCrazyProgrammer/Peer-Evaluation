import os
from flask import Blueprint, request, jsonify, redirect, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth

from models import Lecturer as LecturerModel

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
login_manager = LoginManager()
oauth = OAuth()


class LecturerSession(UserMixin):
    """Flask-Login's view of a lecturer — wraps the Lecturer model row."""
    def __init__(self, lecturer):
        self.id = lecturer.id
        self.name = lecturer.name
        self.email = lecturer.email


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
    lecturer = LecturerModel.find(user_id)
    return LecturerSession(lecturer) if lecturer else None


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    name, email, password = data.get("name"), data.get("email"), data.get("password")
    if not all([name, email, password]):
        return jsonify({"error": "name, email and password are all required"}), 400

    if LecturerModel.exists(email=email):
        return jsonify({"error": "An account with that email already exists"}), 409

    LecturerModel.create(name=name, email=email, password_hash=generate_password_hash(password))
    return jsonify({"message": "Account created — you can now log in"}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email, password = data.get("email"), data.get("password")
    lecturer = LecturerModel.first(email=email)
    if not lecturer or not lecturer.password_hash or not check_password_hash(lecturer.password_hash, password):
        return jsonify({"error": "Invalid email or password"}), 401

    login_user(LecturerSession(lecturer))
    return jsonify({"message": "Logged in", "name": lecturer.name, "email": lecturer.email})


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

    lecturer = LecturerModel.first(google_id=google_id) or LecturerModel.first(email=email)
    if lecturer:
        lecturer.update(google_id=google_id)
    else:
        lecturer = LecturerModel.create(name=name or email, email=email, google_id=google_id)

    login_user(LecturerSession(lecturer))
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
