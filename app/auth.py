import secrets
from functools import wraps
from flask import Blueprint, current_app, g, request, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from .db import get_db, transaction
from .sessions import now

bp = Blueprint('auth', __name__)
DUMMY_HASH = generate_password_hash('unusable-random-' + secrets.token_urlsafe(32), method='scrypt')


def create_local_teacher(email, password):
    email = email.strip().lower()
    if len(password) < 20:
        raise ValueError('Initial password must contain at least 20 characters')
    db = get_db()
    return db.execute("INSERT INTO users(issuer,subject,email,role,password_hash,first_name) VALUES('local',?,?,'teacher',?,'Викладач')",
                      (email, email, generate_password_hash(password, method='scrypt'))).lastrowid


def google_enabled():
    return bool(current_app.config['GOOGLE_CLIENT_ID'] and current_app.config['GOOGLE_CLIENT_SECRET'])


def load_user():
    g.user = None
    uid = session.get('user_id')
    if uid:
        row = get_db().execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if row and (row['issuer'] != 'local' or (current_app.config['LOCAL_TEACHER_LOGIN_ENABLED'] and session.get('auth_version') == row['auth_version'])):
            g.user = dict(row)
        else:
            session.pop('user_id', None)
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        token = request.headers.get('X-CSRF-Token', '')
        if not token or not secrets.compare_digest(token, session.get('csrf', '')):
            abort(403, 'Сесію оновлено. Оновіть сторінку та повторіть дію.')


def require_user(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not g.user:
                abort(401, 'Увійдіть в обліковий запис.')
            if role and g.user['role'] != role:
                abort(403, 'Недостатньо прав доступу.')
            return fn(*args, **kwargs)
        return wrapped
    return decorator


def public_user():
    return {k: g.user[k] for k in ('id','email','first_name','last_name','role','issuer')} if g.user else None


def establish_session(uid, auth_version=None):
    session.rotate()
    session['user_id'] = uid
    if auth_version is not None:
        session['auth_version'] = auth_version
    session['csrf'] = secrets.token_urlsafe(32)


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, 'Некоректний запит.')
    return data


@bp.get('/api/session')
def session_info():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return dict(user=public_user(), csrf=session['csrf'], google_enabled=google_enabled(),
                local_teacher_enabled=current_app.config['LOCAL_TEACHER_LOGIN_ENABLED'])


@bp.post('/api/auth/local')
def local_login():
    if not current_app.config['LOCAL_TEACHER_LOGIN_ENABLED']:
        abort(403, 'Тестовий вхід вимкнено.')
    data = payload()
    email, password = data.get('email', ''), data.get('password', '')
    if not isinstance(email, str) or not isinstance(password, str) or len(password) > 256:
        abort(400, 'Перевірте дані входу.')
    ip = request.remote_addr or 'unknown'
    t = now()
    with transaction() as db:
        row = db.execute('SELECT * FROM login_limits WHERE ip=?', (ip,)).fetchone()
        if row and t - row['window_start'] < 900 and row['failures'] >= 5:
            abort(429, 'Забагато спроб. Повторіть вхід через 15 хвилин.')
        if not row or t-row['window_start'] >= 900:
            db.execute('INSERT OR REPLACE INTO login_limits VALUES(?,0,?)', (ip,t))
        # Count before verification, to keep concurrent attempts bounded.
        db.execute('UPDATE login_limits SET failures=failures+1 WHERE ip=?', (ip,))
    user = get_db().execute("SELECT * FROM users WHERE issuer='local' AND subject=?", (email.strip().lower(),)).fetchone()
    valid = check_password_hash(user['password_hash'] if user else DUMMY_HASH, password)
    if not user or not valid:
        abort(401, 'Неправильний логін або пароль.')
    with transaction() as db:
        current = db.execute('SELECT password_hash,auth_version FROM users WHERE id=?', (user['id'],)).fetchone()
        if current['auth_version'] != user['auth_version'] or current['password_hash'] != user['password_hash']:
            abort(401, 'Пароль змінено. Увійдіть з новим паролем.')
        db.execute('DELETE FROM login_limits WHERE ip=?', (ip,))
    establish_session(user['id'], user['auth_version'])
    return {'ok': True}


@bp.post('/api/auth/logout')
def logout():
    session.rotate()
    return {'ok': True}


@bp.post('/api/auth/password')
@require_user('teacher')
def change_password():
    if g.user['issuer'] != 'local':
        abort(400, 'Пароль Google змінюється в обліковому записі Google.')
    data = payload()
    password = data.get('password', '')
    current = data.get('current_password', '')
    if not isinstance(password, str) or not 20 <= len(password) <= 256:
        abort(400, 'Новий пароль має містити від 20 до 256 символів.')
    if not isinstance(current, str) or not check_password_hash(g.user['password_hash'], current):
        abort(400, 'Поточний пароль неправильний.')
    with transaction() as db:
        current = db.execute('SELECT password_hash,auth_version FROM users WHERE id=?', (g.user['id'],)).fetchone()
        if current['auth_version'] != g.user['auth_version'] or current['password_hash'] != g.user['password_hash']:
            abort(409, 'Пароль уже змінено. Увійдіть знову.')
        db.execute('UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=?', (generate_password_hash(password, method='scrypt'),g.user['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (g.user['id'],))
    establish_session(g.user['id'], g.user['auth_version']+1)
    return {'ok': True}
