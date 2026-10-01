import json
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
    source = ROOT / 'data/test-uo6.json'
    if source.exists():
        data = json.loads(source.read_text())
        db.execute('INSERT OR IGNORE INTO tests(id,title,questions) VALUES(1,?,?)',
                   (data['title'], json.dumps(data['questions'], ensure_ascii=False)))
