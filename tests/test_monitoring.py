from fastapi.testclient import TestClient
from app import db,monitoring
from app.models import Watch,Listing
from app.web import app

def heartbeat(now):
    with db.connect() as c:
        db.setting(c,'worker_heartbeat',now)
        db.setting(c,'telegram_token','test-token')
        db.setting(c,'telegram_chat','test-chat')

def test_failure_debounce_dedup_recovery():
    now=10000; sent=[]
    sender=lambda *args:(sent.append(args[2]) or (True,'ok',0))
    heartbeat(now)
    monitoring.tick(now,{'web':False,'browser':True},sender)
    heartbeat(now+179);monitoring.tick(now+179,{'web':False,'browser':True},sender)
    assert not sent
    heartbeat(now+180);monitoring.tick(now+180,{'web':False,'browser':True},sender)
    heartbeat(now+200);monitoring.tick(now+200,{'web':False,'browser':True},sender)
    assert len(sent)==1 and 'ALERT' in sent[0]
    heartbeat(now+210);monitoring.tick(now+210,{'web':True,'browser':True},sender)
    heartbeat(now+220);monitoring.tick(now+220,{'web':True,'browser':True},sender)
    assert len(sent)==2 and 'RECOVERED' in sent[1]

def test_retry_and_zero_results_success():
    now=10000;heartbeat(now)
    with db.connect() as c:
        c.execute("UPDATE sources SET failures=3 WHERE id='dealabs'")
        c.execute("INSERT INTO runs(source,started_at,ended_at,status,count) VALUES('vinted',?,?, 'experimental',0)",(now-10,now))
    calls=[]
    def sender(*args):
        calls.append(args)
        return len(calls)>1,'test',60
    data=monitoring.tick(now,{'web':True,'browser':True},sender)
    assert next(s for s in data['sources'] if s['name']=='vinted')['success_rate']==100
    monitoring.tick(now+10,{'web':True,'browser':True},sender)
    assert len(calls)==1
    heartbeat(now+60);monitoring.tick(now+60,{'web':True,'browser':True},sender)
    assert len(calls)==2

def test_notification_delay_excludes_quiet_hours():
    now=1790935200;heartbeat(now)
    watch=Watch(name='Elden Ring',max_cents=5000)
    listing=Listing(source='dealabs',external_id='monitor',url='https://www.dealabs.com/test',title='Elden Ring PS5',item_cents=1000)
    with db.connect() as c:
        admin=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()['id']
        c.execute('INSERT INTO watches(owner_id,data,next_at,created_at) VALUES(?,?,?,?)',(admin,watch.model_dump_json(),now,now))
        lid=db.put_listing(c,listing,now)
        c.execute('INSERT INTO events(watch_id,listing_id,price_cents,next_at,created_at,message) VALUES(1,?,1000,?,?,?)',(lid,now,now,'test'))
    ok={'web':True,'browser':True}
    assert monitoring.tick(now,ok)['overdue']==0
    heartbeat(now+600);assert monitoring.tick(now+600,ok)['overdue']==1
    with db.connect() as c:
        db.user_setting(c,admin,'quiet_start','00:00');db.user_setting(c,admin,'quiet_end','23:59')
    assert monitoring.tick(now+601,ok)['overdue']==0
    with db.connect() as c:db.user_setting(c,admin,'quiet_start','')
    assert monitoring.tick(now+602,ok)['overdue']==0

def test_stuck_check_dashboard_auth_and_retention(monkeypatch):
    now=1000000;heartbeat(now)
    with db.connect() as c:
        c.execute("INSERT INTO runs(source,started_at,status) VALUES('vinted',?,'running')",(now-181,))
        c.execute("INSERT INTO monitor_samples VALUES(0,'{}')")
    monitoring.tick(now,{'web':True,'browser':True},sender=lambda *a:(True,'ok',0))
    with db.connect() as c:
        assert c.execute('SELECT count(*) FROM monitor_samples').fetchone()[0]==1
        assert c.execute("SELECT active FROM monitor_incidents WHERE key='stuck:vinted'").fetchone()[0]==1
    with TestClient(app) as client:
        assert 'Source performance' in client.get('/monitoring').text
        monkeypatch.delenv('APP_AUTH_DISABLED_FOR_TESTS',raising=False)
        assert client.get('/monitoring',follow_redirects=False).status_code==303

def test_worker_recovers_interrupted_run_without_losing_delivery_lease():
    from app.worker import recover_restart
    with db.connect() as c:
        c.execute("INSERT INTO runs(source,started_at,status) VALUES('leboncoin',1,'running')")
        for name in ('scheduler','source:leboncoin','delivery'):db.acquire(c,name,'old',1,1000)
        db.setting(c,'manual_check_running',1)
    recover_restart()
    with db.connect() as c:
        assert c.execute('SELECT status FROM runs').fetchone()[0]=='interrupted'
        assert [r['name'] for r in c.execute('SELECT name FROM leases')]==['delivery']
        assert db.settings(c)['manual_check_requested']=='1'

def test_paginated_check_uses_longer_monitor_budget():
    from app.sources import CHECK_TIMEOUT
    now=1000000;heartbeat(now)
    with db.connect() as c:
        c.execute("INSERT INTO runs(source,started_at,status) VALUES('leboncoin',?,'running')",(now-200,))
        _,problems=monitoring.snapshot(c,now,{'web':True,'browser':True})
        assert 'stuck:leboncoin' not in problems
        c.execute('UPDATE runs SET started_at=?',(now-CHECK_TIMEOUT['leboncoin']-1,))
        _,problems=monitoring.snapshot(c,now,{'web':True,'browser':True})
        assert 'stuck:leboncoin' in problems

def test_backup_health_requires_recent_snapshot(tmp_path):
    import json
    import os
    import sqlite3
    from app.monitoring import backup_healthy
    assert not backup_healthy(tmp_path,now=10000)
    backup=tmp_path/'watcher-test.sqlite3'
    with sqlite3.connect(backup) as conn:
        conn.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        conn.execute("INSERT INTO metadata VALUES('schema_version','1')")
    os.utime(backup,(10000,10000))
    (tmp_path/'.restore-verified').write_text(json.dumps({'backup':backup.name,'verified_at':10000}))
    assert backup_healthy(tmp_path,now=10000)
    assert backup_healthy(tmp_path,now=10000,check_integrity=True)
    assert not backup_healthy(tmp_path,now=10000+48*3600+1)
    (tmp_path/'.restore-verified').write_text(json.dumps({'backup':backup.name,'verified_at':0}))
    assert not backup_healthy(tmp_path,now=10000)
