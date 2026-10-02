import hashlib
import json
import secrets
from flask import current_app
from flask.sessions import SessionInterface, SessionMixin
from .db import get_db
import time


def now():
    clock = current_app.config.get('CLOCK')
    return clock() if clock else time.time()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class ServerSession(dict, SessionMixin):
    def __init__(self, data=None, token=None, expires=None, fresh=True):
        super().__init__(data or {})
        self.token = token or secrets.token_urlsafe(32)
        self.expires = expires or now() + 8 * 3600
        self.fresh = fresh

    def rotate(self):
        get_db().execute('DELETE FROM sessions WHERE token_hash=?', (digest(self.token),))
        self.token = secrets.token_urlsafe(32)
        self.expires = now() + 8 * 3600
        self.fresh = True
        self.clear()


class SQLiteSessions(SessionInterface):
    def open_session(self, app, request):
        token = request.cookies.get(app.config['SESSION_COOKIE_NAME'], '')
        if token and len(token) < 200:
            row = get_db().execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?', (digest(token), now())).fetchone()
            if row:
                return ServerSession(json.loads(row['data']), token, row['expires'], False)
        return ServerSession()

    def save_session(self, app, session, response):
        # Existing sessions only update: a concurrent logout/password change cannot resurrect them.
        values = (json.dumps(dict(session)), session.get('user_id'), session.expires, digest(session.token))
        db = get_db()
        if session.fresh and session.get('user_id'):
            user = db.execute('SELECT issuer,auth_version FROM users WHERE id=?', (session['user_id'],)).fetchone()
            if not user or (user['issuer'] == 'local' and session.get('auth_version') != user['auth_version']):
                return
        if session.fresh:
            db.execute('INSERT INTO sessions(data,user_id,expires,token_hash) VALUES(?,?,?,?)', values)
        else:
            db.execute('UPDATE sessions SET data=?,user_id=?,expires=? WHERE token_hash=?', values)
        db.execute('DELETE FROM sessions WHERE expires<?', (now(),))
        if session.fresh:
            response.set_cookie(app.config['SESSION_COOKIE_NAME'], session.token,
                            max_age=max(0, int(session.expires-now())), httponly=True,
                            secure=app.config['SESSION_COOKIE_SECURE'], samesite='Lax',
                            path=app.config['BASE_PATH'] + '/')
        response.vary.add('Cookie')
