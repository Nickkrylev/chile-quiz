import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def settings():
    base = os.getenv('BASE_PATH', '').rstrip('/')
    return dict(
        DATABASE=os.getenv('DATABASE', str(ROOT / 'instance' / 'testing.sqlite')),
        SECRET_KEY=os.getenv('SECRET_KEY'),
        BASE_PATH=base,
        STUDENT_DOMAIN=os.getenv('STUDENT_DOMAIN', 'student.karazin.ua').lower(),
        PUBLIC_URL=os.getenv('PUBLIC_URL', 'http://127.0.0.1:5055' + base).rstrip('/'),
        SESSION_COOKIE_NAME='testing_session', SESSION_COOKIE_PATH=base + '/',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '1') == '1',
        LOCAL_TEACHER_LOGIN_ENABLED=os.getenv('LOCAL_TEACHER_LOGIN_ENABLED', '0') == '1',
        TRUST_PROXY=os.getenv('TRUST_PROXY', '0') == '1',
        MAX_CONTENT_LENGTH=16384,
    )
