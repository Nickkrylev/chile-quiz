import csv
import io
import json
from conftest import post


def test_teacher_overview_and_preview(teacher):
    r = teacher.get('/api/teacher/overview')
    assert r.status_code == 200
    assert r.json['total'] == 0
    assert len(teacher.get('/api/teacher/preview').json['questions']) == 20


def test_anonymous_forbidden(client):
    assert client.get('/api/teacher/overview').status_code == 401


def test_open_requires_oauth_and_approved_keys(app, teacher):
    assert post(teacher,'/api/teacher/test/settings',{'is_open':True}).status_code == 409
    app.config.update(GOOGLE_CLIENT_ID='x',GOOGLE_CLIENT_SECRET='y')
    assert post(teacher,'/api/teacher/test/settings',{'is_open':True}).status_code == 409
    assert post(teacher,'/api/teacher/test/settings',{'is_open':True,'approve_suggested_keys':True}).status_code == 200
    with app.app_context():
        from app.db import get_db
        questions = json.loads(get_db().execute('SELECT questions FROM tests').fetchone()[0])
        assert questions[6]['correct'] == [1,2]
        assert questions[9]['correct'] == [3]
        assert questions[15]['correct'] == [1]


def test_csv_detail_expiration_and_student_denied(app, teacher):
    from app.db import get_db
    from app.attempts import start_attempt
    with app.app_context():
        db = get_db()
        uid = db.execute("INSERT INTO users(issuer,subject,email,role,first_name,last_name) VALUES('google','one','x@student.karazin.ua','student','=1+1','Имя,Фамилия')").lastrowid
        db.execute('UPDATE tests SET is_open=1,keys_approved=1')
        aid = start_attempt(uid,1,100)['id']
    r = teacher.get('/api/teacher/overview')
    assert r.json['completed'] == 1
    detail = teacher.get(f'/api/teacher/attempts/{aid}').json
    assert len(detail['answers']) == 20
    assert detail['score'] == 0
    rows = list(csv.reader(io.StringIO(teacher.get('/api/teacher/export.csv').data.decode('utf-8-sig'))))
    assert "'=1+1" in rows[1]
    assert 'Имя,Фамилия' in rows[1]
    student = app.test_client()
    with student.session_transaction() as session:
        session['user_id'] = uid
    assert student.get('/api/teacher/overview').status_code == 403
    assert student.get('/api/teacher/preview').status_code == 403
