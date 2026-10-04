import re
from fastapi.testclient import TestClient
from app import db
from app.web import app,timestamp
import pytest

def csrf(response):return re.search(r'name="csrf" value="([^"]+)"',response.text).group(1)

def test_pages_empty_and_csrf():
    with TestClient(app) as client:
        for url in ['/','/deals','/sources','/activity','/settings','/import','/watches/new','/health/ready']:
            response=client.get(url);assert response.status_code==200
        assert 'Create your first watch' in client.get('/').text
        assert client.post('/check-now',data={'csrf':'bad'}).status_code==403

def test_watch_crud_secret_redaction_and_untrusted_escape():
    with TestClient(app) as client:
        token=csrf(client.get('/watches/new'))
        form=dict(csrf=token,name='<script>alert(1)</script>',budget='15',qualification='strict',basis='all-in',condition='any',sources=['dealabs','vinted'],delivery='on',pickup='on',centres=['Lyon / Villeurbanne'],radius_km='25',interval_minutes='60',timezone='Europe/Paris',checking_start='00:00',checking_end='00:00',active='on',notify_drops='on')
        assert client.post('/watches/save',data=form).status_code==200
        response=client.get('/')
        assert '&lt;script&gt;' in response.text and '<script>alert(1)</script>' not in response.text
        with db.connect() as conn:wid=conn.execute('SELECT id FROM watches').fetchone()[0]
        assert client.post(f'/watches/{wid}/duplicate',data={'csrf':token}).status_code==200
        assert client.post(f'/watches/{wid}/pause',data={'csrf':token}).status_code==200
        assert client.post(f'/watches/{wid}/resume',data={'csrf':token}).status_code==200
        assert client.post('/settings',data={'csrf':token,'timezone':'Europe/Paris','default_interval':'60','retention_days':'90','telegram_token':'123456:SECRETTEST','telegram_chat':'99999'}).status_code==200
        assert 'SECRETTEST' not in client.get('/settings').text
        assert client.post(f'/watches/{wid}/delete',data={'csrf':token}).status_code==200

def test_nonexistent_dst_time_rejected():
    with pytest.raises(ValueError):timestamp('2026-03-29T02:30','Europe/Paris')

def test_initial_admin_forces_password_change_and_user_data_is_private(monkeypatch):
    monkeypatch.delenv('APP_AUTH_DISABLED_FOR_TESTS',raising=False)
    with db.connect() as conn:
        admin=conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()['id']
    with TestClient(app,follow_redirects=False) as admin_client:
        assert admin_client.get('/').status_code==303
        login=admin_client.get('/login')
        assert admin_client.post('/login',data={'csrf':csrf(login),'username':'admin','password':'admin@'}).headers['location']=='/account/password'
        password=admin_client.get('/account/password')
        changed=admin_client.post('/account/password',data={'csrf':csrf(password),'password':'admin-secure-change-1','confirm':'admin-secure-change-1'})
        assert changed.headers['location']=='/?message=Password+updated.'
        token=csrf(admin_client.get('/admin/users'))
        created=admin_client.post('/admin/users/create',data={'csrf':token,'username':'guest1','password':'guest-temp-password-1'})
        assert '/admin/users' in created.headers['location']
        token=csrf(admin_client.get('/watches/new'))
        form=dict(csrf=token,name='Elden Ring',budget='25',qualification='name-price',basis='item',condition='any',sources=['dealabs'],delivery='on',pickup='on',centres=['Lyon / Villeurbanne'],radius_km='25',interval_minutes='60',timezone='Europe/Paris',checking_start='00:00',checking_end='00:00',active='on',notify_drops='on')
        admin_client.post('/watches/save',data=form)
        with db.connect() as conn:watch_id=conn.execute('SELECT id FROM watches WHERE owner_id=?',(admin,)).fetchone()['id']

    with TestClient(app,follow_redirects=False) as user_client:
        login=user_client.get('/login')
        user_client.post('/login',data={'csrf':csrf(login),'username':'guest1','password':'guest-temp-password-1'})
        password=user_client.get('/account/password')
        user_client.post('/account/password',data={'csrf':csrf(password),'password':'user-secure-change-2','confirm':'user-secure-change-2'})
        assert 'Elden Ring' not in user_client.get('/').text
        assert user_client.get(f'/watches/{watch_id}/edit').status_code==404
        assert user_client.get('/admin/users').status_code==403

    with TestClient(app) as anon:
        assert anon.get('/deals').url.path=='/login'

def test_existing_single_user_database_migrates_to_private_admin(tmp_path,monkeypatch):
    import sqlite3
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'legacy'))
    legacy_password_hash=db.hash_password('legacy-server-password')
    monkeypatch.setenv('APP_PASSWORD_HASH',legacy_password_hash)
    old_path=db.path();old_path.parent.mkdir(parents=True)
    with sqlite3.connect(old_path) as legacy:
        legacy.execute('CREATE TABLE watches(id INTEGER PRIMARY KEY,data TEXT NOT NULL,next_at REAL NOT NULL,created_at REAL NOT NULL)')
        legacy.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        legacy.execute("INSERT INTO watches VALUES(1,'{}',0,0)")
        legacy.execute("INSERT INTO settings VALUES('timezone','Europe/Paris')")
        legacy.execute("INSERT INTO settings VALUES('telegram_chat','legacy-chat')")
    db.init()
    with db.connect() as conn:
        admin=conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()['id']
        assert db.check_password('legacy-server-password',conn.execute('SELECT password_hash FROM users WHERE id=?',(admin,)).fetchone()['password_hash'])
        assert conn.execute('SELECT owner_id FROM watches WHERE id=1').fetchone()['owner_id']==admin
        assert db.user_settings(conn,admin)['telegram_chat']=='legacy-chat'
