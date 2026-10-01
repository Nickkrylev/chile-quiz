import pytest

@pytest.fixture
def app(tmp_path):
    from app import create_app
    from app.db import init_db
    from app.auth import create_local_teacher
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'test.sqlite'),
        'LOCAL_TEACHER_LOGIN_ENABLED': True, 'SESSION_COOKIE_SECURE': False,
        'SECRET_KEY': 'test-only', 'BASE_PATH': '', 'PUBLIC_URL': 'http://localhost',
        'CLOCK': lambda: 1000.0})
    with app.app_context():
        init_db()
        create_local_teacher('admin@student.karazin.ua', 'test-password-123456789')
    return app

@pytest.fixture
def client(app):
    return app.test_client()

def post(client, path, data):
    csrf = client.get('/api/session').json['csrf']
    return client.post(path, json=data, headers={'X-CSRF-Token': csrf})

@pytest.fixture
def teacher(client):
    assert post(client, '/api/auth/local', {'email':'admin@student.karazin.ua', 'password':'test-password-123456789'}).status_code == 200
    return client
