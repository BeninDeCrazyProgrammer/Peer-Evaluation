import os
from flask import Flask, request, jsonify
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

    # Global CORS configuration
    origins = [
        "https://benindecrazyprogrammer.github.io",
        "https://benindecrazyprogrammer.github.io/Peer-Evaluation"
    ]
    if os.environ.get("FRONTEND_URL"):
        origins.append(os.environ.get("FRONTEND_URL").rstrip("/"))

    CORS(app, supports_credentials=True, origins=origins)

    if local_dev:
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        app.config["SESSION_COOKIE_SECURE"] = False
        # Serve frontend/ from this same Flask process so local testing is
        # same-origin (no cross-site cookie rules to fight without HTTPS).
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
        app.config["SESSION_COOKIE_SAMESITE"] = "None"
        app.config["SESSION_COOKIE_SECURE"] = True

    init_auth(app)
    
    with app.app_context():
        init_db()

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(submissions_bp)
    app.register_blueprint(dashboard_bp)

    # --- Global error handler: keeps error responses as clean JSON instead of
    # an HTML traceback page, without swallowing the real status code. ---
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            # e.g. flask-login's 401 on @login_required, a 404 from an
            # unmatched route, a 405 on the wrong HTTP verb — these already
            # have the correct status/message, so pass them through as-is
            # rather than flattening everything to 500.
            response = jsonify({"error": e.description})
            response.status_code = e.code
        else:
            # A genuine unhandled exception (bug, DB error, etc.) — log it
            # for the Render console and return a generic 500.
            print(f"SERVER CRASH: {e}")
            response = jsonify({"error": str(e)})
            response.status_code = 500
        request_origin = request.headers.get("Origin")
        if request_origin in origins:
            response.headers.add("Access-Control-Allow-Origin", request_origin)
            response.headers.add("Access-Control-Allow-Credentials", "true")
        return response

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)