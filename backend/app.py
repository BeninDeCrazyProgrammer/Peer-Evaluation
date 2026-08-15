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

    # --- THE CRITICAL FIX: Global Error Handler ---
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Log the error to Render console
        print(f"SERVER CRASH: {e}")
        response = jsonify({"error": str(e)})
        response.status_code = 500
        # Manual CORS headers for the error response
        response.headers.add("Access-Control-Allow-Origin", request.headers.get("Origin", "*"))
        response.headers.add("Access-Control-Allow-Credentials", "true")
        return response

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)