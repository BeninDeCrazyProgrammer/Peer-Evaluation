import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

from auth import auth_bp, init_auth
from routes.courses import courses_bp
from routes.groups import groups_bp
from routes.evaluations import evaluations_bp
from routes.submissions import submissions_bp
from routes.dashboard import dashboard_bp
from models import init_db


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

    local_dev = os.environ.get("LOCAL_DEV", "").lower() in ("1", "true", "yes")

    if local_dev:
        # Same-origin locally (frontend served by this same Flask process)
        # — the default cookie rules just work, no https needed.
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        app.config["SESSION_COOKIE_SECURE"] = False
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        app.static_folder = frontend_dir
        app.static_url_path = ""

        @app.route("/", defaults={"path": "index.html"})
        @app.route("/<path:path>")
        def serve_frontend(path):
            from flask import send_from_directory
            full = os.path.join(frontend_dir, path)
            if not os.path.isfile(full):
                return send_from_directory(frontend_dir, "index.html")
            return send_from_directory(frontend_dir, path)
    else:
        # Production: cross-origin (GH Pages <-> Render), both https.
        app.config["SESSION_COOKIE_SAMESITE"] = "None"
        app.config["SESSION_COOKIE_SECURE"] = True

    CORS(app, supports_credentials=True, origins=[os.environ.get("FRONTEND_URL", "*")])

    init_auth(app)
    init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(submissions_bp)
    app.register_blueprint(dashboard_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
