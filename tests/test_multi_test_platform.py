from conftest import post
import json
import sqlite3


def create_test(teacher, title, questions, seconds=20, show_answers=False):
    return post(teacher, '/api/teacher/tests', {
        'title': title,
        'description': 'Тестовий опис',
        'questions': questions,
        'seconds_per_question': seconds,
        'show_answers': show_answers,
    })


def publish(teacher, test_id):
    return post(teacher, f'/api/teacher/tests/{test_id}/state', {
        'status': 'open',
        'confirm_keys': True,
    })


def student_start(client, email, code):
    login = post(client, '/api/auth/student', {
        'email': email,
        'first_name': 'Тестове',
        'last_name': 'Ім’я',
        'public_code': code,
    })
    assert login.status_code == 200, login.json
    return post(client, f'/api/tests/{code}/attempts', {
        'first_name': 'Тестове',
        'last_name': 'Ім’я',
    })


def choice_question(prompt='Питання', correct=None):
    return {
        'type': 'single_choice', 'prompt': prompt, 'text': '',
        'choices': ['Ні', 'Так'], 'correct': [1] if correct is None else correct,
    }


def test_teacher_creates_multiple_tests_with_distinct_links_and_times(teacher, client):
    first = create_test(teacher, 'Перший тест', [choice_question()], seconds=12)
    second = create_test(teacher, 'Другий тест', [choice_question()], seconds=None)
    assert first.status_code == second.status_code == 201
    a, b = first.json, second.json
    assert a['public_code'] != b['public_code']
    assert a['public_url'].endswith('/t/' + a['public_code'])
    assert a['status'] == b['status'] == 'draft'
    assert a['seconds_per_question'] == 12
    assert b['seconds_per_question'] is None
    assert client.get('/t/' + a['public_code']).status_code == 404

    assert publish(teacher, a['id']).status_code == 200
    public = client.get('/api/tests/' + a['public_code'])
    assert public.status_code == 200
    assert public.json['seconds_per_question'] == 12
    assert 'correct' not in str(public.json)
    assert client.get('/t/' + a['public_code']).status_code == 200
    assert len(teacher.get('/api/teacher/tests').json['tests']) == 3


def test_any_email_can_start_each_test_and_timer_is_snapshotted(app, teacher):
    timed = create_test(teacher, 'З таймером', [choice_question()], seconds=9).json
    untimed = create_test(teacher, 'Без таймера', [choice_question()], seconds=None).json
    assert publish(teacher, timed['id']).status_code == 200
    assert publish(teacher, untimed['id']).status_code == 200
    app.config['CLOCK'] = lambda: 1000.0

    first_client = app.test_client()
    first = student_start(first_client, 'Participant+one@example.org', timed['public_code'])
    assert first.status_code == 200
    assert first.json['seconds_per_question'] == 9
    assert first.json['deadline'] == 1009

    second_client = app.test_client()
    second = student_start(second_client, 'participant+one@EXAMPLE.org', untimed['public_code'])
    assert second.status_code == 200
    assert second.json['id'] != first.json['id']
    assert second.json['seconds_per_question'] is None
    assert second.json['deadline'] is None

    with app.app_context():
        from app.db import get_db
        rows = get_db().execute('SELECT test_id,participant_email,seconds_per_question FROM attempts ORDER BY test_id').fetchall()
        assert [row['participant_email'] for row in rows] == ['participant+one@example.org'] * 2
        assert [row['seconds_per_question'] for row in rows] == [9, 0]


def test_typed_answers_are_graded_and_result_uses_question_count(teacher, app):
    questions = [
        choice_question('Один вибір'),
        {'type': 'multiple_choice', 'prompt': 'Декілька', 'text': '',
         'choices': ['A', 'B', 'C'], 'correct': [0, 2]},
        {'type': 'short_text', 'prompt': 'Текст', 'text': '', 'correct_texts': ['Buenos días']},
    ]
    created = create_test(teacher, 'Типи відповідей', questions, seconds=None, show_answers=True)
    assert created.status_code == 201, created.json
    assert publish(teacher, created.json['id']).status_code == 200
    client = app.test_client()
    state = student_start(client, 'learner@outlook.com', created.json['public_code']).json
    assert state['total'] == 3
    assert 'correct' not in state

    for index, answer in enumerate(({'choice': 1}, {'choices': [2, 0]}, {'text': '  BUENOS   DÍAS '})):
        csrf = client.get('/api/session').json['csrf']
        response = client.post(f"/api/attempts/{state['id']}/answers",
                               json={'question_index': index, **answer},
                               headers={'X-CSRF-Token': csrf})
        assert response.status_code == 200, response.json
        state = response.json

    assert state['status'] == 'completed'
    assert state['score'] == 3
    assert state['total'] == 3
    assert len(state['review']['questions']) == 3


def test_legacy_database_migration_preserves_attempts_and_is_repeatable(tmp_path):
    from app import create_app
    from app.db import get_db, init_db

    path = tmp_path / 'legacy.sqlite'
    questions = json.dumps([{
        'prompt': 'Збережене питання', 'text': '', 'choices': ['Ні', 'Так'], 'correct': [1],
    }], ensure_ascii=False)
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL,
                email TEXT NOT NULL, first_name TEXT NOT NULL DEFAULT '', last_name TEXT NOT NULL DEFAULT '',
                auth_version INTEGER NOT NULL DEFAULT 0, role TEXT NOT NULL, password_hash TEXT,
                UNIQUE(issuer,subject)
            );
            CREATE TABLE tests (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, questions TEXT NOT NULL,
                is_open INTEGER NOT NULL DEFAULT 0, keys_approved INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                test_id INTEGER NOT NULL REFERENCES tests(id), first_name TEXT NOT NULL,
                last_name TEXT NOT NULL, questions TEXT NOT NULL, version INTEGER NOT NULL,
                started REAL NOT NULL, deadline REAL NOT NULL, question_index INTEGER NOT NULL DEFAULT 0,
                finished REAL, UNIQUE(user_id,test_id)
            );
            CREATE TABLE answers (
                attempt_id INTEGER NOT NULL REFERENCES attempts(id), question_index INTEGER NOT NULL,
                choice INTEGER, correct INTEGER NOT NULL, answered REAL NOT NULL,
                PRIMARY KEY(attempt_id,question_index)
            );
        ''')
        db.execute("INSERT INTO users(id,issuer,subject,email,role,first_name,last_name) VALUES(1,'local','teacher@example.test','teacher@example.test','teacher','Викладач','')")
        db.execute("INSERT INTO users(id,issuer,subject,email,role,first_name,last_name) VALUES(2,'old-idp','old-sub','PARTICIPANT@example.org','student','Марія','Тест')")
        db.execute('INSERT INTO tests(id,title,questions,is_open,keys_approved,version) VALUES(1,?,?,?,?,7)',
                   ('Старий тест', questions, 1, 1))
        db.execute('INSERT INTO attempts(id,user_id,test_id,first_name,last_name,questions,version,started,deadline,question_index) VALUES(1,2,1,?,?,?,?,?,?,1)',
                   ('Марія','Тест',questions,7,100,120))
        db.execute('INSERT INTO answers(attempt_id,question_index,choice,correct,answered) VALUES(1,0,1,1,110)')

    app = create_app({'TESTING': True, 'DATABASE': str(path), 'SECRET_KEY': 'test-only'})
    with app.app_context():
        init_db()
        first = dict(get_db().execute('SELECT * FROM tests WHERE id=1').fetchone())
        attempt = dict(get_db().execute('SELECT * FROM attempts WHERE id=1').fetchone())
        answer = dict(get_db().execute('SELECT * FROM answers WHERE attempt_id=1').fetchone())
        init_db()
        second = dict(get_db().execute('SELECT * FROM tests WHERE id=1').fetchone())
        assert first['public_code'] and first['status'] == 'open' and first['seconds_per_question'] == 20
        assert first['public_code'] == second['public_code']
        assert first['questions'] == second['questions'] == questions
        assert attempt['participant_email'] == 'participant@example.org'
        assert attempt['seconds_per_question'] == 20
        assert (answer['choice'], answer['correct'], answer['selection'], answer['text_response']) == (1, 1, None, None)
        assert get_db().execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1
