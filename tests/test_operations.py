import re
import time
from pathlib import Path
from fastapi.testclient import TestClient
from app import db,service,worker,sources
from app.models import Watch,Listing
from app.web import app

def test_single_password_auth(monkeypatch):
    monkeypatch.delenv('APP_AUTH_DISABLED_FOR_TESTS',raising=False)
    with TestClient(app,follow_redirects=False) as client:
        assert client.get('/',follow_redirects=False).headers['location']=='/login'
        page=client.get('/login')
        token=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
        assert client.post('/login',data={'csrf':token,'username':'admin','password':'admin@'}).headers['location']=='/account/password'
        page=client.get('/account/password')
        token=re.search(r'name="csrf" value="([^"]+)"',page.text).group(1)
        client.post('/account/password',data={'csrf':token,'password':'this-is-a-secure-test-pass','confirm':'this-is-a-secure-test-pass'})
        assert 'Your watchlist' in client.get('/').text
        assert client.post('/check-now',data={'csrf':token}).status_code==403 # password update requires fresh CSRF

def test_manual_listing_flow_and_alert_outbox():
    with TestClient(app) as client:
        token=re.search(r'name="csrf" value="([^"]+)"',client.get('/watches/new').text).group(1)
        watch_form=dict(csrf=token,name="Demon's Souls",budget='16',qualification='strict',basis='all-in',condition='any',sources=['dealabs'],delivery='on',radius_km='25',interval_minutes='60',timezone='Europe/Paris',checking_start='00:00',checking_end='00:00',active='on',notify_drops='on')
        assert client.post('/watches/save',data=watch_form).status_code==200
        listing_form=dict(csrf=token,source='dealabs',url='https://www.dealabs.com/bons-plans/demons-souls-123',title="Demon's Souls PS5 disc",item_price='12',shipping='3',fees='1',delivery='on',condition='used',platform='ps5',physical='yes',price_kind='exact')
        response=client.post('/import',data=listing_form)
        assert response.status_code==200 and 'Needs review' in response.text
        assert 'Matched watch:' in response.text and 'Calculated match price' in response.text
        assert 'Price history' in response.text and 'Lowest observed' in response.text
        with db.connect() as conn:
            assert conn.execute('SELECT price_cents FROM events').fetchone()[0]==1600
        assert client.post('/import',data=listing_form).status_code==200
        with db.connect() as conn:assert conn.execute('SELECT count(*) FROM events').fetchone()[0]==1

def test_manual_listing_can_mark_availability_as_checked():
    with TestClient(app) as client:
        token=re.search(r'name="csrf" value="([^"]+)"',client.get('/watches/new').text).group(1)
        watch_form=dict(csrf=token,name='Elden Ring',budget='20',qualification='strict',basis='all-in',condition='any',sources=['dealabs'],delivery='on',radius_km='25',interval_minutes='60',timezone='Europe/Paris',checking_start='00:00',checking_end='00:00',active='on',notify_drops='on')
        client.post('/watches/save',data=watch_form)
        listing_form=dict(csrf=token,source='dealabs',url='https://www.dealabs.com/bons-plans/elden-ring-456',title='Elden Ring PS5 disc',item_price='10',shipping='0',fees='0',delivery='on',condition='used',platform='ps5',physical='yes',price_kind='exact',availability='confirmed')
        response=client.post('/import',data=listing_form)
        assert 'User checked available' in response.text
        assert 'Elden Ring PS5 disc' in response.text
        assert 'Elden Ring PS5 disc' not in client.get('/deals?review=yes').text

def test_cancelled_unsent_event_can_be_requeued():
    now=time.time()
    watch=Watch(qualification='strict',name="Demon's Souls",max_cents=1600)
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
