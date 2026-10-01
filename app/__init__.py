from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from .config import settings, ROOT
from .db import close_db, get_db
from .sessions import SQLiteSessions


def create_app(config=None):
    app = Flask(__name__, static_folder=str(ROOT / 'static'), template_folder=str(ROOT))
    app.config.update(settings())
    app.config.update(config or {})
    app.session_interface = SQLiteSessions()
    app.teardown_appcontext(close_db)
    from .auth import bp, load_user
    app.register_blueprint(bp)
    app.before_request(load_user)

    @app.get('/api/health')
    def health():
        get_db().execute('SELECT 1 FROM users LIMIT 1')
        return {'ok': True}

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response
    return app
