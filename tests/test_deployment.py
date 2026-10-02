from app import create_app
from app.db import init_db


def test_prefix_routes_cookies_and_no_neighbor(tmp_path):
    app = create_app({'TESTING':True,'DATABASE':str(tmp_path/'prefix.sqlite'),'BASE_PATH':'/testing',
                      'PUBLIC_URL':'https://gsse.work/testing','SECRET_KEY':'test','SESSION_COOKIE_SECURE':True})
    with app.app_context():
        init_db()
    c = app.test_client()
    first = c.get('/testing/')
    assert first.status_code == 200
    assert c.get('/testing/static/app.js').status_code == 200
    r = c.get('/testing/api/session')
    assert r.status_code == 200
    assert 'Path=/testing/' in first.headers['Set-Cookie']
    assert 'Secure' in first.headers['Set-Cookie'] and 'HttpOnly' in first.headers['Set-Cookie']
    assert c.get('/api/session').status_code == 404


def test_backup_restore_and_credentials_file(app,tmp_path):
    from app.db import get_db
    from pathlib import Path
    target = tmp_path/'backups'
    response = app.test_cli_runner().invoke(args=['backup','--destination',str(target)])
    assert response.exit_code == 0, response.output
    import sqlite3
    copies = list(target.glob('testing-*.sqlite'))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1
    credential = tmp_path/'access.txt'
    response = app.test_cli_runner().invoke(args=['create-teacher','--email','second@example.test','--credentials-file',str(credential)])
    assert response.exit_code == 0, response.output
    assert credential.stat().st_mode & 0o777 == 0o600
    assert 'second@example.test' in credential.read_text()
    assert 'Пароль:' in credential.read_text()
    assert 'Пароль:' not in response.output
    duplicate = app.test_cli_runner().invoke(args=['create-teacher','--email','third@example.test','--credentials-file',str(credential)])
    assert duplicate.exit_code != 0
