CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
 email TEXT NOT NULL, first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '',
 auth_version INTEGER NOT NULL DEFAULT 0,
 role TEXT NOT NULL CHECK(role IN ('teacher','student')), password_hash TEXT,
 UNIQUE(issuer,subject)
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, data TEXT NOT NULL, user_id INTEGER REFERENCES users(id), expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_limits (ip TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_start REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tests (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, questions TEXT NOT NULL,
 is_open INTEGER NOT NULL DEFAULT 0, keys_approved INTEGER NOT NULL DEFAULT 0, version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS attempts (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), test_id INTEGER NOT NULL REFERENCES tests(id),
 first_name TEXT NOT NULL, last_name TEXT NOT NULL, questions TEXT NOT NULL, version INTEGER NOT NULL,
 started REAL NOT NULL, deadline REAL NOT NULL, question_index INTEGER NOT NULL DEFAULT 0,
 finished REAL, UNIQUE(user_id,test_id)
);
CREATE TABLE IF NOT EXISTS answers (
 attempt_id INTEGER NOT NULL REFERENCES attempts(id), question_index INTEGER NOT NULL,
 choice INTEGER, correct INTEGER NOT NULL, answered REAL NOT NULL,
 PRIMARY KEY(attempt_id,question_index)
);
CREATE TABLE IF NOT EXISTS audit_events (
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, created REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS google_teacher_bindings (
 email TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL
);
