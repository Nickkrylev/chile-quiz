import pytest
from werkzeug.exceptions import Forbidden


def test_google_not_configured(client):
    assert client.get('/auth/google').status_code == 503


def test_valid_identity_and_local_email_not_teacher(app):
    from app.google_auth import validated_identity
    with app.app_context():
        identity = validated_identity({'iss':'https://accounts.google.com','sub':'google-id','email':'admin@student.karazin.ua','email_verified':True,'hd':'student.karazin.ua'})
        assert identity['role'] == 'student'
        assert identity['issuer'] != 'local'


@pytest.mark.parametrize('field,value', [('email','x@gmail.com'),('hd','evil.ua'),('email_verified',False),('iss','https://evil.test'),('sub','')])
def test_reject_claims(app, field, value):
    from app.google_auth import validated_identity
    claims = {'iss':'https://accounts.google.com','sub':'id1','email':'x@student.karazin.ua','email_verified':True,'hd':'student.karazin.ua'}
    claims[field] = value
    with app.app_context(), pytest.raises(Forbidden):
        validated_identity(claims)


def test_oauth_state_rejected_before_token_request(app, client):
    app.config.update(GOOGLE_CLIENT_ID='test',GOOGLE_CLIENT_SECRET='test')
    r = client.get('/auth/google/callback?code=untrusted&state=unknown')
    assert r.status_code == 302
    assert 'login_error' in r.location
    assert client.get('/api/session').json['user'] is None
