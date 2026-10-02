from flask import Flask, jsonify, render_template
from werkzeug.exceptions import HTTPException
from .config import settings, ROOT
from .db import close_db, get_db
from .sessions import SQLiteSessions


def create_app(config=None):
    app = Flask(__name__, static_folder=str(ROOT / 'static'), template_folder=str(ROOT))
    app.config.update(settings())
    app.config.update(config or {})
    app.session_interface = SQLiteSessions()
    from .cli import register_cli
    register_cli(app)
    app.teardown_appcontext(close_db)
    from .auth import bp, load_user
    app.register_blueprint(bp)
    app.before_request(load_user)
    from .attempts import bp as attempts_bp
    app.register_blueprint(attempts_bp)
    from .teacher import bp as teacher_bp
    app.register_blueprint(teacher_bp)

    @app.get('/api/health')
    def health():
        get_db().execute('SELECT 1 FROM users LIMIT 1')
        return {'ok': True}

    @app.errorhandler(HTTPException)
    def http_error(error):
        defaults = {400:'Некоректний запит.',401:'Увійдіть в обліковий запис.',403:'Доступ заборонено.',404:'Сторінку не знайдено.',405:'Дію не підтримано.',413:'Запит завеликий.',500:'Помилка сервера. Спробуйте ще раз.'}
        message = defaults.get(error.code, 'Не вдалося виконати запит.') if error.description == type(error).description else error.description
        return jsonify(error=message), error.code

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response
    @app.get('/')
    def index():
        return render_template('index.html')

    if app.config.get('TRUST_PROXY', False):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    if app.config['BASE_PATH']:
        from .prefix import PrefixMiddleware
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, app.config['BASE_PATH'])
    return app
