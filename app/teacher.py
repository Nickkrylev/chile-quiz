import csv
import io
import json
import secrets
from datetime import datetime, timezone
from flask import Blueprint, request, g, abort, Response, current_app
from .auth import require_user, payload
from .db import get_db, transaction
from .sessions import now
from .attempts import _advance, question_type, normalized_text, MAX_QUESTIONS, MAX_CHOICES

bp = Blueprint('teacher', __name__)
MAX_TITLE = 200
MAX_DESCRIPTION = 3000
MAX_PROMPT = 1200
MAX_QUESTION_TEXT = 4000
MAX_CHOICE_TEXT = 500
MAX_ACCEPTED_TEXTS = 20
MAX_ACCEPTED_TEXT = 1000
MIN_SECONDS = 5
MAX_SECONDS = 3600


def settle(test_id=None):
    with transaction() as db:
        if test_id is None:
            rows = db.execute('SELECT * FROM attempts WHERE finished IS NULL').fetchall()
        else:
            rows = db.execute('SELECT * FROM attempts WHERE test_id=? AND finished IS NULL',(test_id,)).fetchall()
        for attempt in rows:
            _advance(db,attempt,now())


def _test(test_id):
    row = get_db().execute('SELECT * FROM tests WHERE id=?',(test_id,)).fetchone()
    if not row:
        abort(404,'Тест не знайдено.')
    return row


def _test_json(row):
    questions = json.loads(row['questions'])
    return dict(id=row['id'],title=row['title'],description=row['description'],status=row['status'],
                is_open=row['status']=='open',public_code=row['public_code'],
                public_url=current_app.config['PUBLIC_URL']+'/t/'+row['public_code'],
                seconds_per_question=row['seconds_per_question'],show_answers=bool(row['show_answers']),version=row['version'],
                questions=questions,question_count=len(questions),keys_approved=bool(row['keys_approved']))


def _validate_text(value, label, maximum, required=True):
    if not isinstance(value,str) or len(value)>maximum or (required and not value.strip()):
        abort(400,f'Перевірте поле «{label}».')
    if any(ord(char)<32 and char not in '\n\r\t' for char in value):
        abort(400,f'Поле «{label}» містить недопустимі символи.')
    return value.strip()


def _validate_questions(questions):
    if not isinstance(questions,list) or not 1 <= len(questions) <= MAX_QUESTIONS:
        abort(400,f'Тест має містити від 1 до {MAX_QUESTIONS} запитань.')
    for number, question in enumerate(questions,1):
        label = f'Запитання {number}'
        if not isinstance(question,dict):
            abort(400,f'{label}: некоректна структура.')
        kind = question_type(question)
        if kind not in ('single_choice','multiple_choice','short_text'):
            abort(400,f'{label}: невідомий тип.')
        question['type'] = kind
        question['prompt'] = _validate_text(question.get('prompt'),label,MAX_PROMPT)
        question['text'] = _validate_text(question.get('text',''),label,MAX_QUESTION_TEXT,required=False)
        if kind in ('single_choice','multiple_choice'):
            choices = question.get('choices')
            if not isinstance(choices,list) or not 2 <= len(choices) <= MAX_CHOICES:
                abort(400,f'{label}: додайте від 2 до {MAX_CHOICES} варіантів.')
            question['choices'] = [_validate_text(value,f'{label}, варіант {index+1}',MAX_CHOICE_TEXT) for index,value in enumerate(choices)]
            correct = question.get('correct')
            if (not isinstance(correct,list) or not correct or
                    any(type(index) is not int or not 0 <= index < len(choices) for index in correct) or
                    len(set(correct)) != len(correct)):
                abort(400,f'{label}: позначте правильну відповідь.')
            if kind=='single_choice' and len(correct)>len(choices):
                abort(400,f'{label}: некоректний ключ відповіді.')
            question['correct'] = sorted(correct)
            question.pop('correct_texts',None)
        else:
            accepted = question.get('correct_texts')
            if not isinstance(accepted,list) or not 1 <= len(accepted) <= MAX_ACCEPTED_TEXTS:
                abort(400,f'{label}: додайте хоча б одну допустиму текстову відповідь.')
            accepted = [_validate_text(value,f'{label}, ключ',MAX_ACCEPTED_TEXT) for value in accepted]
            if len({normalized_text(value) for value in accepted}) != len(accepted):
                abort(400,f'{label}: допустимі відповіді мають бути унікальними.')
            question['correct_texts'] = accepted
            question.pop('choices',None)
            question.pop('correct',None)
    return questions


def _validate_test(data):
    title = _validate_text(data.get('title'), 'Назва тесту', MAX_TITLE)
    description = _validate_text(data.get('description',''), 'Опис тесту', MAX_DESCRIPTION, required=False)
    questions = _validate_questions(data.get('questions'))
    seconds = data.get('seconds_per_question',20)
    if seconds is not None and (type(seconds) is not int or not MIN_SECONDS <= seconds <= MAX_SECONDS):
        abort(400,f'Таймер має бути вимкнений або становити від {MIN_SECONDS} до {MAX_SECONDS} секунд на запитання.')
    show_answers = data.get('show_answers',False)
    if type(show_answers) is not bool:
        abort(400,'Перевірте налаштування перегляду відповідей.')
    return title,description,questions,seconds,show_answers


def _audit(action):
    get_db().execute('INSERT INTO audit_events(user_id,action,created) VALUES(?,?,?)',
                     (g.user['id'],json.dumps(action,ensure_ascii=False),now()))


def _new_code(db):
    code = secrets.token_urlsafe(18)
    while db.execute('SELECT 1 FROM tests WHERE public_code=?',(code,)).fetchone():
        code = secrets.token_urlsafe(18)
    return code


@bp.get('/api/teacher/tests')
@require_user('teacher')
def tests_list():
    settle()
    rows = get_db().execute('''SELECT t.*,
        COUNT(a.id) AS attempt_count,
        SUM(CASE WHEN a.finished IS NOT NULL THEN 1 ELSE 0 END) AS completed_count
        FROM tests t LEFT JOIN attempts a ON a.test_id=t.id
        GROUP BY t.id ORDER BY t.id''').fetchall()
    result=[]
    for row in rows:
        data=_test_json(row)
        data['attempt_count']=row['attempt_count']
        data['completed_count']=row['completed_count'] or 0
        result.append(data)
    return {'tests':result}


@bp.post('/api/teacher/tests')
@require_user('teacher')
def create_test():
    data=payload()
    title=data.get('title','Новий тест')
    description=data.get('description','')
    questions=data.get('questions',[{'type':'single_choice','prompt':'Запитання 1','text':'','choices':['Варіант 1','Варіант 2'],'correct':[0]}])
    seconds=data.get('seconds_per_question',20)
    show_answers=data.get('show_answers',False)
    title,description,questions,seconds,show_answers=_validate_test({'title':title,'description':description,'questions':questions,'seconds_per_question':seconds,'show_answers':show_answers})
    with transaction() as db:
        code=_new_code(db)
        test_id=db.execute('INSERT INTO tests(title,questions,description,status,seconds_per_question,show_answers,version,is_open,keys_approved) VALUES(?,?,? ,\'draft\',?,?,1,0,0)',
                           (title,json.dumps(questions,ensure_ascii=False),description,seconds,int(show_answers))).lastrowid
        db.execute('UPDATE tests SET public_code=? WHERE id=?',(code,test_id))
        _audit({'action':'test_created','test_id':test_id})
    return _test_json(_test(test_id)),201


@bp.delete('/api/teacher/tests/<int:test_id>')
@require_user('teacher')
def delete_test(test_id):
    with transaction() as db:
        row=db.execute('SELECT title FROM tests WHERE id=?',(test_id,)).fetchone()
        if not row:
            abort(404,'Тест не знайдено.')
        attempt_ids=[item['id'] for item in db.execute('SELECT id FROM attempts WHERE test_id=?',(test_id,)).fetchall()]
        if attempt_ids:
            db.executemany('DELETE FROM answers WHERE attempt_id=?',((attempt_id,) for attempt_id in attempt_ids))
        db.execute('DELETE FROM attempts WHERE test_id=?',(test_id,))
        db.execute('DELETE FROM tests WHERE id=?',(test_id,))
        _audit({'action':'test_deleted','test_id':test_id,'title':row['title'],'attempt_count':len(attempt_ids)})
    return {'ok':True}


@bp.get('/api/teacher/tests/<int:test_id>')
@require_user('teacher')
def get_test(test_id):
    return _test_json(_test(test_id))


@bp.put('/api/teacher/tests/<int:test_id>')
@require_user('teacher')
def update_test(test_id):
    current=_test(test_id)
    data=payload()
    title,description,questions,seconds,show_answers=_validate_test(data)
    # Once a teacher edits the legacy test, its old suggested key must not
    # overwrite the edited answer key during the next publish action.
    if test_id == 1:
        for question in questions:
            question.pop('suggested_correct', None)
    with transaction() as db:
        row=db.execute('SELECT status FROM tests WHERE id=?',(test_id,)).fetchone()
        if not row:
            abort(404,'Тест не знайдено.')
        next_status='closed' if row['status']=='open' else row['status']
        db.execute('UPDATE tests SET title=?,description=?,questions=?,seconds_per_question=?,show_answers=?,version=version+1,status=?,is_open=0,keys_approved=0 WHERE id=?',
                   (title,description,json.dumps(questions,ensure_ascii=False),seconds,int(show_answers),next_status,test_id))
        _audit({'action':'test_saved','test_id':test_id,'closed_after_edit':row['status']=='open'})
    return _test_json(_test(test_id))


def _set_test_state(test_id,data):
    if not isinstance(data.get('status'),str) or data['status'] not in ('open','closed'):
        abort(400,'Укажіть стан тесту.')
    with transaction() as db:
        row=db.execute('SELECT * FROM tests WHERE id=?',(test_id,)).fetchone()
        if not row:
            abort(404,'Тест не знайдено.')
        if data['status']=='open':
            questions=json.loads(row['questions'])
            # Revalidate stored data before making the public link accept attempts.
            _validate_questions(questions)
            if test_id==1 and not row['keys_approved']:
                if data.get('approve_suggested_keys') is True:
                    for question in questions:
                        if 'suggested_correct' in question:
                            question['correct']=question['suggested_correct']
                    questions=_validate_questions(questions)
                    db.execute('UPDATE tests SET questions=?,version=version+1,keys_approved=1 WHERE id=?',
                               (json.dumps(questions,ensure_ascii=False),test_id))
                elif data.get('confirm_keys') is True:
                    db.execute('UPDATE tests SET keys_approved=1 WHERE id=?',(test_id,))
                else:
                    abort(409,'Перед відкриттям перевірте та підтвердьте ключі відповідей.')
            elif data.get('confirm_keys') is True:
                db.execute('UPDATE tests SET keys_approved=1 WHERE id=?',(test_id,))
            elif not row['keys_approved']:
                abort(409,'Підтвердьте ключі відповідей перед відкриттям тесту.')
            state='open'
        else:
            state='closed'
        db.execute('UPDATE tests SET status=?,is_open=? WHERE id=?',(state,int(state=='open'),test_id))
        _audit({'action':'test_state_changed','test_id':test_id,'status':state})
    return _test_json(_test(test_id))


@bp.post('/api/teacher/tests/<int:test_id>/state')
@require_user('teacher')
def change_test_state(test_id):
    return _set_test_state(test_id,payload())


@bp.get('/api/teacher/tests/<int:test_id>/preview')
@require_user('teacher')
def preview_test(test_id):
    row=_test(test_id)
    questions=json.loads(row['questions'])
    if test_id==1 and not row['keys_approved']:
        for question in questions:
            if 'suggested_correct' in question:
                question['correct']=question['suggested_correct']
    return dict(title=row['title'],description=row['description'],questions=questions,
                seconds_per_question=row['seconds_per_question'])


@bp.get('/api/teacher/tests/<int:test_id>/overview')
@require_user('teacher')
def test_overview(test_id):
    test=_test(test_id)
    settle(test_id)
    total,completed=get_db().execute('SELECT COUNT(*),COUNT(finished) FROM attempts WHERE test_id=?',(test_id,)).fetchone()
    rows=get_db().execute('''SELECT a.questions,
        (SELECT COALESCE(SUM(correct),0) FROM answers WHERE attempt_id=a.id) AS score
        FROM attempts a WHERE a.test_id=? AND a.finished IS NOT NULL''',(test_id,)).fetchall()
    percents=[]
    for row in rows:
        maximum=len(json.loads(row['questions']))
        if maximum:
            percents.append((row['score'] or 0)*100/maximum)
    average=round(sum(percents)/len(percents),1) if percents else None
    return dict(test=_test_json(test),total=total,completed=completed,active=total-completed,average=average)


def test_settings():
    row=get_db().execute('SELECT title,status,keys_approved,version FROM tests WHERE id=1').fetchone()
    if not row:
        return None
    result=dict(row)
    result['is_open']=result['status']=='open'
    return result


@bp.get('/api/teacher/overview')
@require_user('teacher')
def overview():
    settle(1)
    total,completed=get_db().execute('SELECT COUNT(*),COUNT(finished) FROM attempts WHERE test_id=1').fetchone()
    rows=get_db().execute('''SELECT a.questions,
        (SELECT COALESCE(SUM(correct),0) FROM answers WHERE attempt_id=a.id) AS score
        FROM attempts a WHERE a.test_id=1 AND a.finished IS NOT NULL''').fetchall()
    percents=[]
    for row in rows:
        count=len(json.loads(row['questions']))
        if count:
            percents.append((row['score'] or 0)*100/count)
    mean=sum(percents)/len(percents) if percents else None
    return dict(total=total,completed=completed,active=total-completed,
                average=round(mean,1) if mean is not None else None,test=test_settings())


def filtered_rows(test_id,paginate=True):
    query=request.args.get('search','')[:100]
    status=request.args.get('status','')
    clauses=['a.test_id=?']; args=[test_id]
    if query:
        clauses.append("(a.first_name LIKE ? ESCAPE '\\' OR a.last_name LIKE ? ESCAPE '\\' OR a.participant_email LIKE ? ESCAPE '\\')")
        term='%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        args.extend([term]*3)
    if status in ('completed','active'):
        clauses.append('a.finished IS '+('NOT NULL' if status=='completed' else 'NULL'))
    where=' WHERE '+' AND '.join(clauses)
    sql='''SELECT a.id,a.first_name,a.last_name,a.participant_email AS email,a.started,a.finished,a.question_index,
           a.questions,a.version,t.title AS test_title,
           (SELECT COALESCE(SUM(correct),0) FROM answers WHERE attempt_id=a.id) AS score
           FROM attempts a JOIN tests t ON t.id=a.test_id'''+where+' ORDER BY a.started DESC,a.id DESC'
    total=get_db().execute('SELECT COUNT(*) FROM attempts a'+where,args).fetchone()[0]
    if paginate:
        try:
            page=max(1,int(request.args.get('page','1')))
        except ValueError:
            page=1
        sql+=' LIMIT 50 OFFSET ?'
        args.append((page-1)*50)
    rows=[]
    for row in get_db().execute(sql,args):
        item=dict(row)
        item['max_score']=len(json.loads(item['questions']))
        item['percent']=round(item['score']*100/item['max_score']) if item['max_score'] else 0
        item.pop('questions')
        rows.append(item)
    return rows,total


def _attempt_detail(aid,test_id=None):
    settle(test_id)
    sql='SELECT a.*,a.participant_email AS email,t.title AS test_title FROM attempts a JOIN tests t ON t.id=a.test_id WHERE a.id=?'
    args=[aid]
    if test_id is not None:
        sql+=' AND a.test_id=?'
        args.append(test_id)
    row=get_db().execute(sql,args).fetchone()
    if not row:
        abort(404,'Спробу не знайдено.')
    result=dict(row)
    result['questions']=json.loads(result['questions'])
    result['answers']=[dict(answer) for answer in get_db().execute('SELECT * FROM answers WHERE attempt_id=? ORDER BY question_index',(aid,))]
    for answer in result['answers']:
        if answer['selection']:
            answer['selection']=json.loads(answer['selection'])
    result['score']=sum(answer['correct'] for answer in result['answers'])
    result['max_score']=len(result['questions'])
    result['percent']=round(result['score']*100/result['max_score']) if result['max_score'] else 0
    return result


@bp.get('/api/teacher/tests/<int:test_id>/attempts')
@require_user('teacher')
def test_attempts(test_id):
    _test(test_id)
    settle(test_id)
    rows,total=filtered_rows(test_id)
    return dict(rows=rows,total=total)


@bp.get('/api/teacher/tests/<int:test_id>/attempts/<int:aid>')
@require_user('teacher')
def test_attempt_detail(test_id,aid):
    _test(test_id)
    return _attempt_detail(aid,test_id)


def csv_safe(value):
    text=str(value or '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else text


def date(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat() if value is not None else ''


def _export(test_id):
    settle(test_id)
    rows,_=filtered_rows(test_id,False)
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['Тест','Прізвище','Ім’я','Email','Статус','Початок (UTC)','Завершення (UTC)','Бали','Максимум','Результат (%)'])
    for row in rows:
        writer.writerow([csv_safe(row['test_title']),csv_safe(row['last_name']),csv_safe(row['first_name']),csv_safe(row['email']),
                         'Завершено' if row['finished'] is not None else 'У процесі',date(row['started']),date(row['finished']),
                         row['score'],row['max_score'],row['percent'] if row['finished'] is not None else ''])
    filename=f'test-{test_id}-results.csv'
    return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="{filename}"'})


@bp.get('/api/teacher/tests/<int:test_id>/export.csv')
@require_user('teacher')
def test_export(test_id):
    _test(test_id)
    return _export(test_id)


# Compatibility routes for existing clients of the original test dashboard.
@bp.get('/api/teacher/attempts')
@require_user('teacher')
def attempts():
    settle(1)
    rows,total=filtered_rows(1)
    return dict(rows=rows,total=total)


@bp.get('/api/teacher/attempts/<int:aid>')
@require_user('teacher')
def detail(aid):
    return _attempt_detail(aid,1)


@bp.get('/api/teacher/export.csv')
@require_user('teacher')
def export():
    return _export(1)


@bp.get('/api/teacher/preview')
@require_user('teacher')
def preview():
    return preview_test(1)


@bp.post('/api/teacher/test/settings')
@require_user('teacher')
def settings():
    data=payload()
    if type(data.get('is_open')) is not bool:
        abort(400,'Укажіть стан тесту.')
    state='open' if data['is_open'] else 'closed'
    body={'status':state,'approve_suggested_keys':data.get('approve_suggested_keys') is True,
          'confirm_keys':data.get('approve_suggested_keys') is True}
    result=_set_test_state(1,body)
    return {'ok':True,'test':test_settings(),'result':result}
