from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask import session, request, abort
import secrets
import hmac

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.login"

    from .routes import main
    app.register_blueprint(main)

    @app.context_processor
    def inject_csrf_token():
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["_csrf_token"]}

    @app.before_request
    def csrf_protect():
        if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            return

        if request.endpoint == "main.github_webhook":
            return

        session_token = session.get("_csrf_token")
        request_token = request.form.get("_csrf_token") or request.headers.get("X-CSRFToken")

        if not session_token or not request_token:
            abort(400)

        if not hmac.compare_digest(session_token, request_token):
            abort(400)

    return app
