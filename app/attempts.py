import json
from flask import Blueprint, g, abort
from .auth import require_user, payload
from .db import get_db, transaction
from .sessions import now

bp = Blueprint('attempts', __name__)
SECONDS = 20


def _advance(db, attempt, t):
    a = dict(attempt)
    questions = json.loads(a['questions'])
    while a['finished'] is None and t >= a['deadline']:
        index = a['question_index']
        db.execute('INSERT OR IGNORE INTO answers VALUES(?,?,NULL,0,?)', (a['id'],index,a['deadline']))
        a['question_index'] += 1
        if a['question_index'] == len(questions):
            a['finished'] = a['deadline']
        else:
            a['deadline'] += SECONDS
    db.execute('UPDATE attempts SET question_index=?,deadline=?,finished=? WHERE id=?',
               (a['question_index'],a['deadline'],a['finished'],a['id']))
    return a


def _state(db, a, t):
    questions = json.loads(a['questions'])
    result = dict(id=a['id'], status='completed' if a['finished'] is not None else 'active',
                  question_index=a['question_index'], total=len(questions), server_time=t,
                  first_name=a['first_name'], last_name=a['last_name'], started=a['started'], finished=a['finished'])
    if a['finished'] is not None:
        result['score'] = db.execute('SELECT COALESCE(SUM(correct),0) FROM answers WHERE attempt_id=?',(a['id'],)).fetchone()[0]
        result['answered'] = db.execute('SELECT COUNT(*) FROM answers WHERE attempt_id=? AND choice IS NOT NULL',(a['id'],)).fetchone()[0]
    else:
        q = questions[a['question_index']]
        result.update(question=q['prompt'], text=q['text'], choices=q['choices'], deadline=a['deadline'])
    return result


def _owned(db, uid, aid):
    row = db.execute('SELECT * FROM attempts WHERE id=? AND user_id=?',(aid,uid)).fetchone()
    if not row:
        abort(404,'Попытка не найдена.')
    return row


def start_attempt(user_id, test_id, now):
    with transaction() as db:
        existing = db.execute('SELECT * FROM attempts WHERE user_id=? AND test_id=?',(user_id,test_id)).fetchone()
        if existing:
            return _state(db, _advance(db,existing,now), now)
        test = db.execute('SELECT * FROM tests WHERE id=?',(test_id,)).fetchone()
        if not test or not test['is_open'] or not test['keys_approved']:
            abort(409,'Приём ответов пока закрыт. Обратитесь к преподавателю.')
        user = db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not user or not user['first_name'].strip() or not user['last_name'].strip():
            abort(400,'Введите имя и фамилию.')
        aid = db.execute('INSERT INTO attempts(user_id,test_id,first_name,last_name,questions,version,started,deadline) VALUES(?,?,?,?,?,?,?,?)',
                        (user_id,test_id,user['first_name'],user['last_name'],test['questions'],test['version'],now,now+SECONDS)).lastrowid
        return _state(db,dict(_owned(db,user_id,aid)),now)


def attempt_state(user_id, attempt_id, now):
    with transaction() as db:
        return _state(db,_advance(db,_owned(db,user_id,attempt_id),now),now)


def submit_answer(user_id, attempt_id, question_index, choice, now):
    if type(question_index) is not int or type(choice) is not int or not 0 <= choice <= 3:
        abort(400,'Выберите один вариант ответа.')
    with transaction() as db:
        a = _advance(db,_owned(db,user_id,attempt_id),now)
        # Retries and stale tabs only return authoritative state.
        if a['finished'] is not None or question_index < a['question_index']:
            return _state(db,a,now)
        if question_index != a['question_index']:
            abort(409,'Вопрос изменился. Обновите состояние теста.')
        questions = json.loads(a['questions'])
        db.execute('INSERT INTO answers VALUES(?,?,?,?,?)', (attempt_id,question_index,choice,int(choice in questions[question_index]['correct']),now))
        a['question_index'] += 1
        if a['question_index'] == len(questions):
            a['finished'] = now
        else:
            a['deadline'] = now + SECONDS
        db.execute('UPDATE attempts SET question_index=?,deadline=?,finished=? WHERE id=?',
                   (a['question_index'],a['deadline'],a['finished'],attempt_id))
        return _state(db,a,now)


@bp.get('/api/test')
def test_info():
    row = get_db().execute('SELECT title,is_open,keys_approved FROM tests WHERE id=1').fetchone()
    return dict(title=row['title'], is_open=bool(row['is_open'] and row['keys_approved']), total=20, seconds=SECONDS)


@bp.post('/api/attempts')
@require_user('student')
def start():
    data = payload()
    first, last = data.get('first_name',''),data.get('last_name','')
    if any(not isinstance(x,str) or not 1 <= len(x.strip()) <= 80 or any(ord(c)<32 for c in x) for x in (first,last)):
        abort(400,'Укажите имя и фамилию, до 80 символов в каждом поле.')
    get_db().execute('UPDATE users SET first_name=?,last_name=? WHERE id=?',(first.strip(),last.strip(),g.user['id']))
    return start_attempt(g.user['id'],1,now())


@bp.get('/api/attempts/current')
@require_user('student')
def current():
    row = get_db().execute('SELECT id FROM attempts WHERE user_id=? AND test_id=1',(g.user['id'],)).fetchone()
    return {'attempt': attempt_state(g.user['id'],row['id'],now()) if row else None}


@bp.post('/api/attempts/<int:aid>/answers')
@require_user('student')
def answer(aid):
    data = payload()
    return submit_answer(g.user['id'],aid,data.get('question_index'),data.get('choice'),now())
