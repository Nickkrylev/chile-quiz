import json
from concurrent.futures import ThreadPoolExecutor
import pytest

@pytest.fixture
def seeded(app):
    with app.app_context():
        from app.db import get_db, init_db
        init_db()
        db = get_db()
        for subject in ['student1','student2']:
            db.execute("INSERT INTO users(issuer,subject,email,role,first_name,last_name) VALUES('https://accounts.google.com',?,?,'student','Имя','Фамилия')", (subject,subject+'@student.karazin.ua'))
        db.execute('UPDATE tests SET is_open=1,keys_approved=1')
        ids = [r[0] for r in db.execute("SELECT id FROM users WHERE role='student'")]
    return app, ids


def test_twenty_questions_and_source_keys(seeded):
    app, _ = seeded
    with app.app_context():
        from app.db import get_db
        questions = json.loads(get_db().execute('SELECT questions FROM tests').fetchone()[0])
        assert len(questions) == 20
        assert all(len(q['choices']) == 4 for q in questions)
        assert questions[9]['source_correct'] == [2]
        assert questions[15]['suggested_correct'] == [1]


def test_deadlines_no_keys_and_resume(seeded):
    app, ids = seeded
    from app.attempts import start_attempt, attempt_state
    with app.app_context():
        state = start_attempt(ids[0], 1, 100)
        assert state['deadline'] == 120
        assert not {'correct', 'source_correct', 'suggested_correct', 'questions'} & state.keys()
        assert attempt_state(ids[0],state['id'],161)['question_index'] == 3
        end = attempt_state(ids[0],state['id'],500)
        assert end['status'] == 'completed' and end['score'] == 0
        assert start_attempt(ids[0],1,600)['id'] == state['id']


def test_answer_before_deadline_idempotent(seeded):
    app, ids = seeded
    from app.attempts import start_attempt, submit_answer
    with app.app_context():
        state = start_attempt(ids[0],1,100)
        result = submit_answer(ids[0],state['id'],0,1,119)
        assert result['question_index'] == 1 and result['deadline'] == 139
        repeat = submit_answer(ids[0],state['id'],0,1,120)
        assert repeat['question_index'] == 1 and repeat['deadline'] == 139


def test_late_answer_is_skip_and_foreign_rejected(seeded):
    from werkzeug.exceptions import NotFound
    app, ids = seeded
    from app.attempts import start_attempt, submit_answer, attempt_state
    from app.db import get_db
    with app.app_context():
        state = start_attempt(ids[0],1,100)
        result = submit_answer(ids[0],state['id'],0,1,120)
        assert result['question_index'] == 1
        assert get_db().execute('SELECT choice FROM answers').fetchone()[0] is None
        with pytest.raises(NotFound):
            attempt_state(ids[1],state['id'],121)


def test_simultaneous_start(seeded):
    app, ids = seeded
    from app.attempts import start_attempt
    def run():
        with app.app_context():
            return start_attempt(ids[0],1,100)['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:run(),range(2)))
    assert results[0] == results[1]


def test_closed_test_keeps_current_attempt(seeded):
    app, ids = seeded
    from app.attempts import start_attempt, submit_answer
    from app.db import get_db
    from werkzeug.exceptions import Conflict
    with app.app_context():
        state = start_attempt(ids[0],1,100)
        get_db().execute('UPDATE tests SET is_open=0')
        with pytest.raises(Conflict):
            start_attempt(ids[1],1,101)
        assert submit_answer(ids[0],state['id'],0,1,101)['question_index'] == 1
