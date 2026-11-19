import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from flask import current_app, g
from .config import ROOT


def get_db():
    if 'db' not in g:
        path = Path(current_app.config['DATABASE'])
        path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(path, timeout=15, isolation_level=None)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA busy_timeout=15000')
    return g.db


def close_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


@contextmanager
def transaction():
    db = get_db()
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def init_db():
    db = get_db()
    db.executescript((ROOT / 'app/schema.sql').read_text())
    if 'auth_version' not in {row[1] for row in db.execute('PRAGMA table_info(users)')}:
        db.execute('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')

    # Add columns in place so existing attempts and answer rows are never rebuilt.
    additions = {
        'tests': {
            'public_code': 'TEXT',
            'description': "TEXT NOT NULL DEFAULT ''",
            'status': "TEXT NOT NULL DEFAULT 'closed'",
            'seconds_per_question': 'INTEGER',
            'show_answers': 'INTEGER NOT NULL DEFAULT 0',
        },
        'attempts': {
            'participant_email': 'TEXT',
            'seconds_per_question': 'INTEGER NOT NULL DEFAULT 20',
        },
        'answers': {
            'selection': 'TEXT',
            'text_response': 'TEXT',
        },
    }
    added = {}
    for table, columns in additions.items():
        existing = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        added[table] = set()
        for column, declaration in columns.items():
            if column not in existing:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
                added[table].add(column)

    source = ROOT / 'data/test-uo6.json'
    if source.exists():
        data = json.loads(source.read_text())
        seeded = db.execute('INSERT OR IGNORE INTO tests(id,title,questions) VALUES(1,?,?)',
                            (data['title'], json.dumps(data['questions'], ensure_ascii=False))).rowcount > 0
    else:
        seeded = False

    # The initial public code is generated once and remains stable across restarts.
    legacy = db.execute('SELECT * FROM tests WHERE id=1').fetchone()
    if legacy:
        updates = {}
        if legacy['public_code'] is None:
            code = secrets.token_urlsafe(12)
            while db.execute('SELECT 1 FROM tests WHERE public_code=?', (code,)).fetchone():
                code = secrets.token_urlsafe(12)
            updates['public_code'] = code
        if 'status' in added['tests']:
            updates['status'] = 'open' if legacy['is_open'] and legacy['keys_approved'] else 'closed'
        if 'seconds_per_question' in added['tests'] or seeded:
            updates['seconds_per_question'] = 20
        if updates:
            db.execute('UPDATE tests SET '+','.join(f'{name}=?' for name in updates)+' WHERE id=1', tuple(updates.values()))

    # Snapshot the participant address; casefolding makes later resume checks stable.
    # Historical duplicate addresses remain attached to their original attempt rows;
    # request handling resolves those to the latest matching attempt without merging data.
    for row in db.execute('SELECT a.id,u.email FROM attempts a JOIN users u ON u.id=a.user_id WHERE a.participant_email IS NULL').fetchall():
        db.execute('UPDATE attempts SET participant_email=? WHERE id=?', (row['email'].casefold(),row['id']))
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_tests_public_code ON tests(public_code) WHERE public_code IS NOT NULL')
