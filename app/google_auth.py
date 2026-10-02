from authlib.integrations.flask_client import OAuth
from flask import Blueprint, current_app, redirect, abort, g
from .auth import google_enabled, establish_session
from .db import get_db, transaction

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
        abort(403,'Не вдалося підтвердити обліковий запис Google.')
    email = email.lower()
    teacher = email in current_app.config['GOOGLE_TEACHER_EMAILS']
    if not teacher and (email.rsplit('@',1)[-1] != current_app.config['STUDENT_DOMAIN']
                        or claims.get('hd') != current_app.config['GOOGLE_HD']):
        abort(403,'Використовуйте навчальну пошту student.karazin.ua.')
    return dict(issuer='https://accounts.google.com', sub=claims['sub'],email=email,
                first_name=str(claims.get('given_name',''))[:80],last_name=str(claims.get('family_name',''))[:80],
                role='teacher' if teacher else 'student')


def resolve_identity(identity):
    with transaction() as db:
        if identity['role'] == 'teacher':
            bound = db.execute('SELECT issuer,subject FROM google_teacher_bindings WHERE email=?', (identity['email'],)).fetchone()
            if bound and (bound['issuer'],bound['subject']) != (identity['issuer'],identity['sub']):
                abort(403,'Обліковий запис викладача не відповідає прив’язаному запису.')
            db.execute('INSERT OR IGNORE INTO google_teacher_bindings VALUES(?,?,?)', (identity['email'],identity['issuer'],identity['sub']))
        db.execute('INSERT INTO users(issuer,subject,email,first_name,last_name,role) VALUES(?,?,?,?,?,?) ON CONFLICT(issuer,subject) DO UPDATE SET email=excluded.email,role=excluded.role',
                   (identity['issuer'],identity['sub'],identity['email'],identity['first_name'],identity['last_name'],identity['role']))
        return db.execute('SELECT id FROM users WHERE issuer=? AND subject=?',(identity['issuer'],identity['sub'])).fetchone()[0]


@bp.get('/auth/google')
def login():
    if not google_enabled():
        abort(503,'Вхід через Google ще налаштовується.')
    oauth = current_app.extensions['testing_oauth']
    # PUBLIC_URL is administrator configuration; never build callbacks from a Host header.
    return oauth.google.authorize_redirect(current_app.config['PUBLIC_URL']+'/auth/google/callback',prompt='select_account')


@bp.get('/auth/google/callback')
def callback():
    if not google_enabled():
        abort(503,'Вхід через Google ще налаштовується.')
    try:
        token = current_app.extensions['testing_oauth'].google.authorize_access_token(leeway=0)
        # Authlib checks signature, issuer, audience, expiration, nonce and state.
        identity = validated_identity(token.get('userinfo',{}))
        uid = resolve_identity(identity)
        establish_session(uid)
        return redirect(current_app.config['BASE_PATH']+'/')
    except Exception as error:
        # Avoid logging authorization codes, tokens or provider error descriptions.
        current_app.logger.warning('Google sign-in rejected (%s)',type(error).__name__)
        return redirect(current_app.config['BASE_PATH']+'/?login_error=1')
