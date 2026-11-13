import time
from app import db, worker, sources, service
from app.models import Watch


def test_vinted_override_reschedules_source_and_watch_without_speeding_dealabs(monkeypatch):
    now=time.time()
    watch=Watch(name='Elden Ring',max_cents=2000,sources=['vinted','dealabs'],checking_start='00:00',checking_end='00:00')
    with db.connect() as c:
        db.setting(c,'vinted_interval_seconds',30)
        c.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(watch.model_dump_json(),now,now))
        c.execute('UPDATE sources SET next_at=0,enabled=1')
    monkeypatch.setattr(service,'deliver',lambda *a:None)
    calls=[]
    def checker(source):
        calls.append(source)
        return sources.Outcome('experimental','test',[])
    worker.tick(now,checker)
    with db.connect() as c:
        assert c.execute("SELECT next_at FROM sources WHERE id='vinted'").fetchone()[0]==now+30
        assert c.execute("SELECT next_at FROM sources WHERE id='dealabs'").fetchone()[0]==now+300
        assert now+30 <= c.execute('SELECT next_at FROM watches').fetchone()[0] < now+35
    worker.tick(now+31,checker)
    assert calls.count('vinted')==2
    assert calls.count('dealabs')==1


def test_override_preserves_defaults_and_minimum():
    watch=Watch(name='Game',max_cents=2000,sources=['vinted'])
    assert worker.watch_interval(watch,{})==300
    assert worker.watch_interval(watch,{'vinted_interval_seconds':'1'})==30
    assert worker.watch_interval(watch.model_copy(update={'sources':['dealabs']}),{'vinted_interval_seconds':'30'})==300
