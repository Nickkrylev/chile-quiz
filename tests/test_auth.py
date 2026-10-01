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
