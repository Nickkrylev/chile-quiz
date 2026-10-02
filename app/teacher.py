import csv
import io
import json
from datetime import datetime, timezone
from flask import Blueprint, request, g, abort, Response
from .auth import require_user, payload, google_enabled
from .db import get_db, transaction
from .sessions import now
from .attempts import _advance

bp = Blueprint('teacher', __name__)


def settle():
    with transaction() as db:
        for a in db.execute('SELECT * FROM attempts WHERE finished IS NULL').fetchall():
            _advance(db,a,now())


def test_settings():
    row = get_db().execute('SELECT title,is_open,keys_approved,version FROM tests WHERE id=1').fetchone()
    return dict(row)


@bp.get('/api/teacher/overview')
@require_user('teacher')
def overview():
    settle()
    db = get_db()
    total, completed = db.execute('SELECT COUNT(*),COUNT(finished) FROM attempts').fetchone()
    mean = db.execute('SELECT AVG(score) FROM (SELECT COALESCE(SUM(b.correct),0)*5.0 AS score FROM attempts a LEFT JOIN answers b ON a.id=b.attempt_id WHERE a.finished IS NOT NULL GROUP BY a.id)').fetchone()[0]
    return dict(total=total,completed=completed,active=total-completed,average=round(mean,1) if mean is not None else None,
                test=test_settings(),google_enabled=google_enabled())


def filtered_rows(paginate=True):
    query = request.args.get('search','')[:100]
    status = request.args.get('status','')
    clauses, args = [], []
    if query:
        clauses.append("(a.first_name LIKE ? ESCAPE '\\' OR a.last_name LIKE ? ESCAPE '\\' OR u.email LIKE ? ESCAPE '\\')")
        term = '%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        args.extend([term]*3)
    if status in ('completed','active'):
        clauses.append('a.finished IS '+('NOT NULL' if status=='completed' else 'NULL'))
    where = ' WHERE '+' AND '.join(clauses) if clauses else ''
    sql = 'SELECT a.id,a.first_name,a.last_name,u.email,a.started,a.finished,a.question_index,(SELECT COALESCE(SUM(correct),0) FROM answers WHERE attempt_id=a.id) AS score FROM attempts a JOIN users u ON a.user_id=u.id'+where+' ORDER BY a.started DESC,a.id DESC'
    total = get_db().execute('SELECT COUNT(*) FROM attempts a JOIN users u ON a.user_id=u.id'+where,args).fetchone()[0]
    if paginate:
        try:
            page = max(1,int(request.args.get('page','1')))
        except ValueError:
            page = 1
        sql += ' LIMIT 50 OFFSET ?'
        args.append((page-1)*50)
    return [dict(r) for r in get_db().execute(sql,args)], total


@bp.get('/api/teacher/attempts')
@require_user('teacher')
def attempts():
    settle()
    rows,total = filtered_rows()
    return dict(rows=rows,total=total)


@bp.get('/api/teacher/attempts/<int:aid>')
@require_user('teacher')
def detail(aid):
    settle()
    db = get_db()
    row = db.execute('SELECT a.*,u.email FROM attempts a JOIN users u ON a.user_id=u.id WHERE a.id=?',(aid,)).fetchone()
    if not row:
        abort(404,'Спробу не знайдено.')
    result = dict(row)
    result['questions'] = json.loads(result['questions'])
    result['answers'] = [dict(r) for r in db.execute('SELECT * FROM answers WHERE attempt_id=? ORDER BY question_index',(aid,))]
    result['score'] = sum(a['correct'] for a in result['answers'])
    return result


def csv_safe(value):
    text = str(value or '')
    return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else text


def date(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat() if value is not None else ''


@bp.get('/api/teacher/export.csv')
@require_user('teacher')
def export():
    settle()
    rows,_ = filtered_rows(False)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Прізвище','Ім’я','Email','Статус','Початок (UTC)','Завершення (UTC)','Бали з 20'])
    for row in rows:
        writer.writerow([csv_safe(row['last_name']),csv_safe(row['first_name']),csv_safe(row['email']),
                         'Завершено' if row['finished'] is not None else 'У процесі',date(row['started']),date(row['finished']),row['score']])
    return Response('\ufeff'+output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="uo6-results.csv"'})


@bp.get('/api/teacher/preview')
@require_user('teacher')
def preview():
    row = get_db().execute('SELECT title,questions FROM tests WHERE id=1').fetchone()
    questions = json.loads(row['questions'])
    # Preview follows the proposed corrected key, clearly indicated in the UI.
    for q in questions:
        q['correct'] = q['suggested_correct']
    return dict(title=row['title'],questions=questions,seconds=20)


@bp.post('/api/teacher/test/settings')
@require_user('teacher')
def settings():
    data = payload()
    if type(data.get('is_open')) is not bool:
        abort(400,'Укажіть стан тесту.')
    with transaction() as db:
        row = db.execute('SELECT * FROM tests WHERE id=1').fetchone()
        approved = row['keys_approved'] or data.get('approve_suggested_keys') is True
        if data['is_open'] and (not google_enabled() or not approved):
            abort(409,'Щоб відкрити тест, підключіть Google і підтвердьте ключі відповідей.')
        if data.get('approve_suggested_keys') is True and not row['keys_approved']:
            questions = json.loads(row['questions'])
            for q in questions:
                q['correct'] = q['suggested_correct']
            db.execute('UPDATE tests SET questions=?,keys_approved=1,version=version+1 WHERE id=1', (json.dumps(questions,ensure_ascii=False),))
        db.execute('UPDATE tests SET is_open=? WHERE id=1',(int(data['is_open']),))
        db.execute('INSERT INTO audit_events(user_id,action,created) VALUES(?,?,?)',(g.user['id'],json.dumps({'is_open':data['is_open'],'approved':bool(approved)}),now()))
    return {'ok':True,'test':test_settings()}
