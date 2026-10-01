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


@pytest.mark.parametrize('fault',[None,'signature','audience','issuer','expiry','nonce','missing_nonce'])
def test_signed_oidc_callback_validation(app,client,monkeypatch,fault):
    import time
    from urllib.parse import urlparse,parse_qs
    from authlib.jose import JsonWebKey, jwt
    app.config.update(GOOGLE_CLIENT_ID='test-client',GOOGLE_CLIENT_SECRET='test-secret')
    google = app.extensions['testing_oauth'].google
    google.client_id = 'test-client'
    google.client_secret = 'test-secret'
    metadata = {'issuer':'https://accounts.google.com',
                'authorization_endpoint':'https://accounts.google.com/o/oauth2/v2/auth',
                'token_endpoint':'https://oauth2.googleapis.com/token',
                'id_token_signing_alg_values_supported':['RS256']}
    monkeypatch.setattr(google,'load_server_metadata',lambda:metadata)
    key=JsonWebKey.generate_key('RSA',2048,options={'kid':'test'},is_private=True)
    monkeypatch.setattr(google,'fetch_jwk_set',lambda **kwargs:{'keys':[key.as_dict()]})
    login=client.get('/auth/google')
    params=parse_qs(urlparse(login.location).query)
    claims={'iss':'https://accounts.google.com','sub':'verified-student','aud':'test-client','exp':int(time.time())+3600,
            'iat':int(time.time()),'nonce':params['nonce'][0],
            'email':'admin@student.karazin.ua','email_verified':True,'hd':'student.karazin.ua'}
    if fault=='audience':claims['aud']='other-client'
    if fault=='issuer':claims['iss']='https://evil.test'
    if fault=='expiry':claims['exp']=int(time.time())-1
    if fault=='nonce':claims['nonce']='wrong'
    if fault=='missing_nonce':claims.pop('nonce')
    signing_key=JsonWebKey.generate_key('RSA',2048,options={'kid':'test'},is_private=True) if fault=='signature' else key
    token=jwt.encode({'alg':'RS256','kid':'test'},claims,signing_key).decode()
    monkeypatch.setattr(google,'fetch_access_token',lambda **kwargs:{'id_token':token,'access_token':'mock-access','token_type':'Bearer'})
    callback=client.get('/auth/google/callback?code=mock-code&state='+params['state'][0])
    user=client.get('/api/session').json['user']
    if fault:
        assert 'login_error' in callback.location
        assert user is None
    else:
        assert user['role']=='student'
        assert user['issuer']=='https://accounts.google.com'
        with app.app_context():
            from app.db import get_db
            assert get_db().execute("SELECT COUNT(*) FROM users WHERE email='admin@student.karazin.ua'").fetchone()[0]==2
