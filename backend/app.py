import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

# Load local .env file if it exists
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
    
    # 1. Configuration
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
    
    # Check if we are running in local development mode
    local_dev = os.environ.get("LOCAL_DEV", "").lower() in ("1", "true", "yes")

    # 2. CORS & Cookie Security Logic
    if local_dev:
        # Local Development Settings
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
        app.config["SESSION_COOKIE_SECURE"] = False
        
        # In local dev, we allow everything
        allowed_origins = "*"
        
        # Logic to serve the frontend folder locally via Flask
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
        # Production Settings (GitHub Pages <-> Render)
        app.config["SESSION_COOKIE_SAMESITE"] = "None"
        app.config["SESSION_COOKIE_SECURE"] = True
        
        # FIX: Define allowed origins. 
        # We must allow the base domain even if the project is in a subfolder.
        frontend_url = os.environ.get("FRONTEND_URL", "").rstrip("/")
        allowed_origins = [
            "https://benindecrazyprogrammer.github.io", # Base domain
            frontend_url                                # Full project path
        ]

    # Initialize CORS with the flexible origin list
    CORS(app, supports_credentials=True, origins=allowed_origins)

    # 3. Initialize Auth and Database
    init_auth(app)
    
    # This creates the tables on Turso if they don't exist
    with app.app_context():
        init_db()

    # 4. Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(courses_bp)
    app.register_blueprint(groups_bp)
    app.register_blueprint(evaluations_bp)
    app.register_blueprint(submissions_bp)
    app.register_blueprint(dashboard_bp)

    # 5. Health Check
    @app.route("/health")
    def health():
        return {"status": "ok", "mode": "production" if not local_dev else "local"}

    return app

# Main entry point
app = create_app()

if __name__ == "__main__":
    # Local development run
    app.run(debug=True, port=5000)