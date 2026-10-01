from authlib.integrations.flask_client import OAuth
from flask import Blueprint, current_app, redirect, abort, g
from .auth import google_enabled, establish_session
from .db import get_db

bp = Blueprint('google', __name__)


def setup_oauth(app):
    oauth = OAuth(app)
    oauth.register(name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'], client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope':'openid email profile','code_challenge_method':'S256','timeout':10})
    app.extensions['testing_oauth'] = oauth


def validated_identity(claims):
    email = claims.get('email', '')
    if (claims.get('iss') not in ('https://accounts.google.com','accounts.google.com')
        or not isinstance(claims.get('sub'),str) or not claims['sub']
        or claims.get('email_verified') is not True or not isinstance(email,str)):
        abort(403,'Не удалось подтвердить аккаунт Google.')
    email = email.lower()
    teacher = email in current_app.config['GOOGLE_TEACHER_EMAILS']
    if not teacher and (email.rsplit('@',1)[-1] != current_app.config['STUDENT_DOMAIN']
                        or claims.get('hd') != current_app.config['GOOGLE_HD']):
        abort(403,'Используйте учебную почту student.karazin.ua.')
    return dict(issuer='https://accounts.google.com', sub=claims['sub'],email=email,
                first_name=str(claims.get('given_name',''))[:80],last_name=str(claims.get('family_name',''))[:80],
                role='teacher' if teacher else 'student')


@bp.get('/auth/google')
def login():
    if not google_enabled():
        abort(503,'Вход через Google ещё настраивается.')
    oauth = current_app.extensions['testing_oauth']
    # PUBLIC_URL is administrator configuration; never build callbacks from a Host header.
    return oauth.google.authorize_redirect(current_app.config['PUBLIC_URL']+'/auth/google/callback',prompt='select_account')


@bp.get('/auth/google/callback')
def callback():
    if not google_enabled():
        abort(503,'Вход через Google ещё настраивается.')
    try:
        token = current_app.extensions['testing_oauth'].google.authorize_access_token(leeway=0)
        # Authlib checks signature, issuer, audience, expiration, nonce and state.
        identity = validated_identity(token.get('userinfo',{}))
        db = get_db()
        db.execute('INSERT INTO users(issuer,subject,email,first_name,last_name,role) VALUES(?,?,?,?,?,?) ON CONFLICT(issuer,subject) DO UPDATE SET email=excluded.email,role=excluded.role',
                   (identity['issuer'],identity['sub'],identity['email'],identity['first_name'],identity['last_name'],identity['role']))
        uid = db.execute('SELECT id FROM users WHERE issuer=? AND subject=?',(identity['issuer'],identity['sub'])).fetchone()[0]
        establish_session(uid)
        return redirect(current_app.config['BASE_PATH']+'/')
    except Exception as error:
        # Avoid logging authorization codes, tokens or provider error descriptions.
        current_app.logger.warning('Google sign-in rejected (%s)',type(error).__name__)
        return redirect(current_app.config['BASE_PATH']+'/?login_error=1')
