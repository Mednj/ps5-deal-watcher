import json,re,threading
from datetime import datetime,timezone
from fastapi.testclient import TestClient
from app import db,worker,sources,service
from app.models import Watch,Listing
from app.matching import eligible,manual_check
from app.web import app


def test_manual_pass_runs_all_selected_sources_concurrently_outside_schedule(monkeypatch):
    now=datetime(2026,10,2,12,tzinfo=timezone.utc).timestamp()
    watch=Watch(name='Elden Ring',max_cents=2000,checking_start='19:00',checking_end='00:00')
    assert not eligible(watch,now)
    with db.connect() as c:
        c.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(watch.model_dump_json(),now+86400,now))
        c.execute('UPDATE sources SET enabled=0,next_at=?',(now+86400,))
        db.setting(c,'manual_check_requested',1)
        db.setting(c,'telegram_token','test-token')
        db.setting(c,'telegram_chat','test-chat')
    barrier=threading.Barrier(4);calls=[]
    def checker(source):
        calls.append(source)
        assert eligible(watch,now) and manual_check.get()
        barrier.wait(timeout=4)
        listing=Listing(source=source,external_id='manual-test',url=sources.URLS[source],title='Elden Ring PS5',item_cents=1000)
        return sources.Outcome('experimental','test', [listing])
    actual_deliver=service.deliver
    monkeypatch.setattr(service,'deliver',lambda *a,**kw:None)
    worker.tick(now,checker)
    assert set(calls)==set(sources.MIN_INTERVAL)
    assert not manual_check.get()
    with db.connect() as c:
        assert c.execute("SELECT count(*) FROM runs WHERE status='experimental'").fetchone()[0]==4
        assert c.execute('SELECT count(*) FROM events WHERE manual=1').fetchone()[0]==4
        assert db.settings(c)['manual_check_running']=='0'
        assert json.loads(c.execute('SELECT data FROM watches').fetchone()[0])['checking_start']=='19:00'
    delivered=[]
    actual_deliver(now+1,sender=lambda *args:(delivered.append(1) or (True,'test delivered',0)))
    assert len(delivered)==4
    worker.tick(now+2,checker=lambda source:(_ for _ in ()).throw(AssertionError('regular pass should respect schedules')))
    with db.connect() as c:
        assert c.execute('SELECT count(*) FROM runs').fetchone()[0]==4
        db.setting(c,'manual_check_requested',1)
    worker.tick(now+3,checker)
    with db.connect() as c:assert c.execute('SELECT count(*) FROM events').fetchone()[0]==4


def test_check_now_queues_immediate_pass_and_coalesces_clicks():
    with TestClient(app) as client:
        csrf=re.search(r'name="csrf" value="([^"]+)"',client.get('/').text).group(1)
        response=client.post('/check-now',data={'csrf':csrf})
        assert response.status_code==200
        with db.connect() as c:assert db.settings(c)['manual_check_requested']=='1'
        response=client.post('/check-now',data={'csrf':csrf})
        assert 'already running or queued' in response.text
