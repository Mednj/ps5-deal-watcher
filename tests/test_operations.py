import hashlib
import secrets
import re
import time
from pathlib import Path
from fastapi.testclient import TestClient
from app import db,service,worker,sources
from app.models import Watch,Listing
from app.web import app

def test_single_password_auth(monkeypatch):
    password='only-a-test-password'
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()
    monkeypatch.setenv('APP_PASSWORD_HASH',f'scrypt${salt.hex()}${digest}')
    with TestClient(app) as client:
        assert client.get('/',follow_redirects=False).headers['location']=='/login'
        page=client.get('/login')
        token=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
        assert client.post('/login',data={'csrf':token,'password':password}).status_code==200
        assert 'Your watchlist' in client.get('/').text
        assert client.post('/check-now',data={'csrf':token}).status_code==403 # login rotates CSRF

def test_manual_listing_flow_and_alert_outbox():
    with TestClient(app) as client:
        token=re.search(r'name="csrf" value="([^"]+)"',client.get('/watches/new').text).group(1)
        watch_form=dict(csrf=token,name="Demon's Souls",budget='16',basis='all-in',condition='any',sources=['dealabs'],delivery='on',radius_km='25',interval_minutes='60',timezone='Europe/Paris',checking_start='00:00',checking_end='00:00',active='on',notify_drops='on')
        assert client.post('/watches/save',data=watch_form).status_code==200
        listing_form=dict(csrf=token,source='dealabs',url='https://www.dealabs.com/bons-plans/demons-souls-123',title="Demon's Souls PS5 disc",item_price='12',shipping='3',fees='1',delivery='on',condition='used',platform='ps5',physical='yes',price_kind='exact')
        response=client.post('/import',data=listing_form)
        assert response.status_code==200 and 'Qualified' in response.text
        with db.connect() as conn:
            assert conn.execute('SELECT price_cents FROM events').fetchone()[0]==1600
        assert client.post('/import',data=listing_form).status_code==200
        with db.connect() as conn:assert conn.execute('SELECT count(*) FROM events').fetchone()[0]==1

def test_cancelled_unsent_event_can_be_requeued():
    now=time.time()
    watch=Watch(name="Demon's Souls",max_cents=1600)
    listing=Listing(source='dealabs',external_id='x',url='https://www.dealabs.com/bons-plans/game-123',title="Demon's Souls PS5 disc",item_cents=1200,shipping_cents=300,fees_cents=100,delivery=True,physical=True,platform='ps5')
    with db.connect() as conn:
        conn.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(watch.model_dump_json(),now,now))
        lid=db.put_listing(conn,listing,now)
        service.evaluate(conn,1,watch,lid,listing,now)
        conn.execute("UPDATE events SET state='cancelled'")
        service.evaluate(conn,1,watch,lid,listing,now+10)
        assert conn.execute('SELECT state FROM events').fetchone()[0]=='pending'
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0]==1

def test_telegram_error_does_not_expose_token(monkeypatch):
    import httpx
    real_client=httpx.Client
    transport=httpx.MockTransport(lambda req:httpx.Response(403,json={'ok':False,'description':'Secret token accidentally mentioned token:SENSITIVE'}))
    monkeypatch.setattr(service.httpx,'Client',lambda **kwargs:real_client(transport=transport,**kwargs))
    ok,detail,_=service.send_telegram('token:SENSITIVE','1','test')
    assert not ok and 'SENSITIVE' not in detail
