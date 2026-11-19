import json
import re
from flask import Blueprint, g, abort
from .auth import require_user, payload
from .db import get_db, transaction
from .sessions import now

bp = Blueprint('attempts', __name__)
DEFAULT_SECONDS = 20
MAX_QUESTIONS = 100
MAX_CHOICES = 20
MAX_ANSWER_TEXT = 2000


def question_type(question):
    return question.get('type', 'single_choice')


def normalized_text(value):
    return re.sub(r'\s+', ' ', value.strip()).casefold()


def _advance(db, attempt, t):
    a = dict(attempt)
    questions = json.loads(a['questions'])
    seconds = a['seconds_per_question']
    if seconds:
        while a['finished'] is None and a['question_index'] < len(questions) and t >= a['deadline']:
            index = a['question_index']
            db.execute('INSERT OR IGNORE INTO answers(attempt_id,question_index,choice,selection,text_response,correct,answered) VALUES(?,?,NULL,NULL,NULL,0,?)',
                       (a['id'],index,a['deadline']))
            a['question_index'] += 1
            if a['question_index'] == len(questions):
                a['finished'] = a['deadline']
            else:
                a['deadline'] += seconds
        db.execute('UPDATE attempts SET question_index=?,deadline=?,finished=? WHERE id=?',
                   (a['question_index'],a['deadline'],a['finished'],a['id']))
    return a


def _state(db, a, t):
    questions = json.loads(a['questions'])
    result = dict(id=a['id'], status='completed' if a['finished'] is not None else 'active',
                  question_index=a['question_index'], total=len(questions), server_time=t,
                  first_name=a['first_name'], last_name=a['last_name'], started=a['started'], finished=a['finished'],
                  seconds_per_question=a['seconds_per_question'] or None)
    if a['finished'] is not None:
        result['score'] = db.execute('SELECT COALESCE(SUM(correct),0) FROM answers WHERE attempt_id=?',(a['id'],)).fetchone()[0]
        result['answered'] = db.execute('SELECT COUNT(*) FROM answers WHERE attempt_id=? AND (choice IS NOT NULL OR selection IS NOT NULL OR text_response IS NOT NULL)',(a['id'],)).fetchone()[0]
        test=db.execute('SELECT show_answers FROM tests WHERE id=?',(a['test_id'],)).fetchone()
        if test and test['show_answers']:
            review_questions=[]
            for question in questions:
                item={key:question[key] for key in ('type','prompt','text','choices','correct','correct_texts') if key in question}
                if 'correct' not in item and 'suggested_correct' in question:
                    item['correct']=question['suggested_correct']
                review_questions.append(item)
            review_answers=[]
            for answer in db.execute('SELECT question_index,choice,selection,text_response,correct FROM answers WHERE attempt_id=? ORDER BY question_index',(a['id'],)):
                item=dict(answer)
                if item['selection']:
                    item['selection']=json.loads(item['selection'])
                review_answers.append(item)
            result['review']={'questions':review_questions,'answers':review_answers}
    else:
        q = questions[a['question_index']]
        result.update(type=question_type(q), question=q['prompt'], text=q.get('text',''),
                      choices=q.get('choices',[]), deadline=a['deadline'] if a['seconds_per_question'] else None)
    return result


def _owned(db, uid, aid):
    user = db.execute('SELECT email FROM users WHERE id=?',(uid,)).fetchone()
    email = user['email'].casefold() if user else ''
    row = db.execute('SELECT * FROM attempts WHERE id=? AND (user_id=? OR participant_email=?)',(aid,uid,email)).fetchone()
    if not row:
        abort(404,'Спробу не знайдено.')
    return row


def start_attempt(user_id, test_id, participant_email, now=None):
    # Keep the existing in-process call form (user_id, test_id, now) working.
    if now is None:
        now = participant_email
        user_row = get_db().execute('SELECT email FROM users WHERE id=?',(user_id,)).fetchone()
        participant_email = user_row['email'] if user_row else ''
    email = participant_email.strip().casefold() if isinstance(participant_email,str) else ''
    if not email or len(email) > 254:
        abort(400,'Введіть адресу електронної пошти.')
    with transaction() as db:
        existing = db.execute('SELECT * FROM attempts WHERE test_id=? AND participant_email=? ORDER BY started DESC,id DESC LIMIT 1',
                              (test_id,email)).fetchone()
        if existing:
            return _state(db,_advance(db,existing,now),now)
        test = db.execute('SELECT * FROM tests WHERE id=?',(test_id,)).fetchone()
        legacy_open = test_id == 1 and test and test['is_open'] and test['keys_approved']
        if not test or (test['status'] != 'open' and not legacy_open) or (test_id == 1 and not test['keys_approved']):
            abort(409,'Приймання відповідей поки закрито. Зверніться до викладача.')
        user = db.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if not user or not user['first_name'].strip() or not user['last_name'].strip():
            abort(400,'Введіть ім’я та прізвище.')
        questions = json.loads(test['questions'])
        if not questions or len(questions) > MAX_QUESTIONS:
            abort(409,'Тест має некоректну кількість запитань.')
        seconds = test['seconds_per_question']
        deadline = now + seconds if seconds is not None else 0
        stored_seconds = seconds if seconds is not None else 0
        aid = db.execute('INSERT INTO attempts(user_id,test_id,first_name,last_name,questions,version,started,deadline,participant_email,seconds_per_question) VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (user_id,test_id,user['first_name'],user['last_name'],test['questions'],test['version'],now,deadline,email,stored_seconds)).lastrowid
        attempt = db.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone()
        return _state(db,attempt,now)


def attempt_state(user_id, attempt_id, now):
    with transaction() as db:
        return _state(db,_advance(db,_owned(db,user_id,attempt_id),now),now)


def _validate_answer(question, answer):
    kind = question_type(question)
    choices = question.get('choices',[])
    if kind == 'single_choice':
        choice = answer.get('choice') if isinstance(answer,dict) and set(answer)=={'choice'} else None
        if type(choice) is not int or not 0 <= choice < len(choices):
            abort(400,'Оберіть один варіант відповіді.')
        return {'choice':choice,'selection':None,'text_response':None}
    if kind == 'multiple_choice':
        selected = answer.get('choices') if isinstance(answer,dict) and set(answer)=={'choices'} else None
        if (not isinstance(selected,list) or not selected or len(selected)>len(choices) or
                any(type(item) is not int or not 0 <= item < len(choices) for item in selected) or
                len(set(selected)) != len(selected)):
            abort(400,'Оберіть коректні варіанти відповіді.')
        return {'choice':None,'selection':json.dumps(sorted(selected)),'text_response':None}
    if kind == 'short_text':
        value = answer.get('text') if isinstance(answer,dict) and set(answer)=={'text'} else None
        if not isinstance(value,str) or not value.strip() or len(value)>MAX_ANSWER_TEXT:
            abort(400,'Введіть коротку текстову відповідь.')
        return {'choice':None,'selection':None,'text_response':value.strip()}
    abort(400,'Тип запитання не підтримується.')


def _is_correct(question, submitted):
    kind = question_type(question)
    correct = question.get('correct',[])
    if kind == 'single_choice':
        return submitted['choice'] in correct
    if kind == 'multiple_choice':
        return set(json.loads(submitted['selection'])) == set(correct)
    if kind == 'short_text':
        accepted = question.get('correct_texts',[])
        value = normalized_text(submitted['text_response'])
        return any(value == normalized_text(item) for item in accepted)
    return False


def submit_answer(user_id, attempt_id, question_index, answer, now):
    if type(question_index) is not int:
        abort(400,'Запитання змінилося. Оновіть сторінку.')
    with transaction() as db:
        a = _advance(db,_owned(db,user_id,attempt_id),now)
        # Retries and stale tabs only return authoritative state.
        if a['finished'] is not None or question_index < a['question_index']:
            return _state(db,a,now)
        if question_index != a['question_index']:
            abort(409,'Запитання змінилося. Оновіть стан тесту.')
        questions = json.loads(a['questions'])
        question = questions[a['question_index']]
        submitted = _validate_answer(question,answer)
        if a['seconds_per_question'] and now >= a['deadline']:
            a = _advance(db,a,now)
            return _state(db,a,now)
        db.execute('INSERT INTO answers(attempt_id,question_index,choice,selection,text_response,correct,answered) VALUES(?,?,?,?,?,?,?)',
                   (attempt_id,question_index,submitted['choice'],submitted['selection'],submitted['text_response'],int(_is_correct(question,submitted)),now))
        a['question_index'] += 1
        if a['question_index'] == len(questions):
            a['finished'] = now
        elif a['seconds_per_question']:
            a['deadline'] = now + a['seconds_per_question']
        db.execute('UPDATE attempts SET question_index=?,deadline=?,finished=? WHERE id=?',
                   (a['question_index'],a['deadline'],a['finished'],attempt_id))
        return _state(db,a,now)


@bp.get('/api/test')
def test_info():
    row = get_db().execute('SELECT title,description,status,questions,seconds_per_question FROM tests WHERE id=1').fetchone()
    if not row:
        abort(404,'Тест не знайдено.')
    questions = json.loads(row['questions'])
    return dict(title=row['title'],description=row['description'],is_open=row['status']=='open',
                total=len(questions),seconds=row['seconds_per_question'])


def _public_test(public_code):
    row = get_db().execute('SELECT id,title,description,status,questions,seconds_per_question FROM tests WHERE public_code=?',
                           (public_code,)).fetchone()
    if not row or row['status']=='draft':
        abort(404,'Тест не знайдено.')
    return row


@bp.get('/api/tests/<public_code>')
def public_test_info(public_code):
    row = _public_test(public_code)
    return dict(title=row['title'],description=row['description'],status=row['status'],
                is_open=row['status']=='open',total=len(json.loads(row['questions'])),
                seconds_per_question=row['seconds_per_question'])


def _save_student_name(data):
    first, last = data.get('first_name',''),data.get('last_name','')
    if any(not isinstance(value,str) or not 1 <= len(value.strip()) <= 80 or any(ord(c)<32 for c in value) for value in (first,last)):
        abort(400,'Укажіть ім’я та прізвище, до 80 символів у кожному полі.')
    get_db().execute('UPDATE users SET first_name=?,last_name=? WHERE id=?',(first.strip(),last.strip(),g.user['id']))


@bp.post('/api/attempts')
@require_user('student')
def start():
    data = payload()
    _save_student_name(data)
    return start_attempt(g.user['id'],1,g.user['email'],now())


@bp.post('/api/tests/<public_code>/attempts')
@require_user('student')
def start_for_test(public_code):
    test = _public_test(public_code)
    data = payload()
    _save_student_name(data)
    return start_attempt(g.user['id'],test['id'],g.user['email'],now())


@bp.get('/api/attempts/current')
@require_user('student')
def current():
    row = get_db().execute('SELECT id FROM attempts WHERE test_id=1 AND (user_id=? OR participant_email=?) ORDER BY started DESC,id DESC LIMIT 1',
                           (g.user['id'],g.user['email'].casefold())).fetchone()
    return {'attempt': attempt_state(g.user['id'],row['id'],now()) if row else None}


@bp.get('/api/tests/<public_code>/attempts/current')
@require_user('student')
def current_for_test(public_code):
    test = _public_test(public_code)
    row = get_db().execute('SELECT id FROM attempts WHERE test_id=? AND (user_id=? OR participant_email=?) ORDER BY started DESC,id DESC LIMIT 1',
                           (test['id'],g.user['id'],g.user['email'].casefold())).fetchone()
    return {'attempt':attempt_state(g.user['id'],row['id'],now()) if row else None}


@bp.post('/api/attempts/<int:aid>/answers')
@require_user('student')
def answer(aid):
    data = payload()
    content = {key:data[key] for key in ('choice','choices','text') if key in data}
    return submit_answer(g.user['id'],aid,data.get('question_index'),content,now())
