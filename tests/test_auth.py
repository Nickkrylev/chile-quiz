from conftest import post


def test_teacher_login_and_hash(app, teacher):
    assert teacher.get('/api/session').json['user']['role'] == 'teacher'
    with app.app_context():
        from app.db import get_db
        row = get_db().execute('SELECT password_hash FROM users').fetchone()
        assert row['password_hash'].startswith('scrypt:')
        assert 'test-password' not in row['password_hash']


def test_csrf_required(client):
    assert client.post('/api/auth/local', json={'email':'a','password':'b'}).status_code == 403


def test_rate_limit_and_expiration(app, client):
    for _ in range(5):
        assert post(client, '/api/auth/local', {'email':'bad','password':'bad'}).status_code == 401
    assert post(client, '/api/auth/local', {'email':'bad','password':'bad'}).status_code == 429
    app.config['CLOCK'] = lambda: 1901.0
    assert post(client, '/api/auth/local', {'email':'bad','password':'bad'}).status_code == 401


def test_disable_revokes_local(app, teacher):
    app.config['LOCAL_TEACHER_LOGIN_ENABLED'] = False
    assert teacher.get('/api/session').json['user'] is None
    assert post(teacher,'/api/auth/local', {'email':'admin@student.karazin.ua','password':'test-password-123456789'}).status_code == 403


def test_password_change_revokes_other_sessions(app, teacher):
    other = app.test_client()
    post(other, '/api/auth/local', {'email':'admin@student.karazin.ua','password':'test-password-123456789'})
    response = post(teacher, '/api/auth/password', {'current_password':'test-password-123456789','password':'changed-password-123456789'})
    assert response.status_code == 200
    assert other.get('/api/session').json['user'] is None
    assert post(other, '/api/auth/local', {'email':'admin@student.karazin.ua','password':'test-password-123456789'}).status_code == 401


def test_logout(teacher):
    assert post(teacher, '/api/auth/logout', {}).status_code == 200
    assert teacher.get('/api/session').json['user'] is None


def test_inflight_old_password_cannot_create_session(app,client,monkeypatch):
    import app.auth as auth
    from app.db import get_db
    from werkzeug.security import generate_password_hash
    original=auth.check_password_hash
    done=False
    def concurrent_change(encoded,password):
        nonlocal done
        valid=original(encoded,password)
        if valid and not done:
            done=True
            with app.app_context():
                db=get_db()
                # Interleave a completed password replacement before login persists its session.
                db.execute("UPDATE users SET password_hash=? WHERE issuer='local'",(generate_password_hash('replacement-password-123456'),))
                columns={r[1] for r in db.execute('PRAGMA table_info(users)')}
                if 'auth_version' in columns:db.execute('UPDATE users SET auth_version=auth_version+1')
                db.execute('DELETE FROM sessions WHERE user_id IS NOT NULL')
        return valid
    monkeypatch.setattr(auth,'check_password_hash',concurrent_change)
    post(client,'/api/auth/local',{'email':'admin@student.karazin.ua','password':'test-password-123456789'})
    assert client.get('/api/session').json['user'] is None


def test_existing_responses_do_not_overwrite_rotated_cookie(teacher):
    response=teacher.get('/api/session')
    assert 'Set-Cookie' not in response.headers


def test_student_email_login_accepts_any_valid_domain(app, client):
    response = post(client, '/api/auth/student', {
        'email': ' Student+test@proton.me ',
        'first_name': 'Ім’я',
        'last_name': 'Прізвище',
    })
    assert response.status_code == 200
    user = client.get('/api/session').json['user']
    assert user['email'] == 'student+test@proton.me'
    assert user['role'] == 'student'
    with app.app_context():
        from app.db import get_db
        assert get_db().execute("SELECT COUNT(*) FROM users WHERE email='student+test@proton.me'").fetchone()[0] == 1


def test_student_email_login_normalizes_and_reuses_external_address(app, client):
    from app.db import get_db
    first = post(client, '/api/auth/student', {
        'email': ' Learner+one@Example.org ',
        'first_name': 'Ім’я',
        'last_name': 'Прізвище',
    })
    assert first.status_code == 200
    original_id = client.get('/api/session').json['user']['id']
    second = post(client, '/api/auth/student', {
        'email': 'learner+one@example.org',
        'first_name': 'Нове ім’я',
        'last_name': 'Нове прізвище',
    })
    assert second.status_code == 200
    assert client.get('/api/session').json['user']['id'] == original_id
    with app.app_context():
        users = get_db().execute("SELECT COUNT(*) FROM users WHERE issuer='student_email'").fetchone()[0]
        assert users == 1
