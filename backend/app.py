import os
import logging
from flask import Flask, request
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
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        app.config["SESSION_COOKIE_SECURE"] = False
        # Local frontend serving logic...
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
        
        # Allow everything in local dev
        CORS(app, supports_credentials=True, origins="*")
    else:
        app.config["SESSION_COOKIE_SAMESITE"] = "None"
        app.config["SESSION_COOKIE_SECURE"] = True
        
        # PRODUCTION CORS:
        # We allow your specific GitHub Pages domain and the project path.
        # We also allow the "origin" to be the environment variable.
        allowed_origins = [
            "https://benindecrazyprogrammer.github.io",
            "https://benindecrazyprogrammer.github.io/Peer-Evaluation"
        ]
        
        frontend_env = os.environ.get("FRONTEND_URL")
        if frontend_env:
            allowed_origins.append(frontend_env.rstrip("/"))
            # Also allow with a slash just in case
            allowed_origins.append(frontend_env.rstrip("/") + "/")

        CORS(app, supports_credentials=True, origins=allowed_origins)

    init_auth(app)
    
    # Initialize DB within app context
    with app.app_context():
        try:
            init_db()
        except Exception as e:
            print(f"Database Init Error: {e}")

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(submissions_bp)
    app.register_blueprint(dashboard_bp)

    @app.route("/health")
    def health():
        return {"status": "ok", "origin_detected": request.headers.get("Origin")}

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)