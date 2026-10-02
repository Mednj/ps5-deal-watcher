from datetime import datetime
import json
import sqlite3
from zoneinfo import ZoneInfo
import pytest

from app import db,service,sources,worker
from app.models import Listing,Watch,cents
from app.matching import match,eligible,quiet

NOW=datetime(2026,10,1,12,tzinfo=ZoneInfo('Europe/Paris')).timestamp()

def listing(**changes):
    return Listing(**dict(source='dealabs',external_id='123',url='https://www.dealabs.com/bons-plans/demons-souls-123',title="Demon's Souls PS5 disc",item_cents=1200,shipping_cents=300,fees_cents=100,delivery=True,physical=True,platform='ps5',condition='used',**changes))

def offer(**changes):
    data=listing().model_dump();data.update(changes);return Listing(**data)

def watch(**changes):
    data=dict(name="Demon's Souls",max_cents=1500);data.update(changes);return Watch(qualification='strict',**data)

def persist(w=None,l=None,now=NOW):
    w=w or watch(max_cents=1600);l=l or listing()
    with db.connect() as conn:
        conn.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(w.model_dump_json(),now,now))
        wid=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        lid=db.put_listing(conn,l,now);service.evaluate(conn,wid,w,lid,l,now)
    return wid,lid

def telegram_config():
    with db.connect() as conn:
        db.setting(conn,'telegram_token','fake:not-real');db.setting(conn,'telegram_chat','1')

def test_all_in_arithmetic():
    assert match(watch(),listing()).state=='over-budget'
    assert match(watch(max_cents=1600),listing()).state=='qualified'
    assert match(watch(max_cents=1600),listing()).total==1600

@pytest.mark.parametrize('field',['shipping_cents','fees_cents'])
def test_unknown_is_not_zero(field):
    assert match(watch(max_cents=1600),offer(**{field:None})).state=='candidate'

def test_pickup_is_separate():
    l=offer(shipping_cents=None,fees_cents=None,pickup=True,pickup_fees_cents=0,lat=45.764,lon=4.8357,location='Lyon')
    result=match(watch(),l)
    assert result.state=='qualified' and result.total==1200 and result.route=='pickup'
    assert match(watch(),l.model_copy(update={'pickup_fees_cents':None})).state=='candidate'
    assert match(watch(delivery=False),l.model_copy(update={'lat':43.3,'lon':5.3})).state=='excluded'

@pytest.mark.parametrize('title',["Demon's Souls PS5 digital","Demon's Souls PS5 compte","Demon's Souls PS5 empty case","Demon's Souls PS5 manette","Demon's Souls 2 PS5 disc"])
def test_excluded_titles(title):assert match(watch(),offer(title=title)).state=='excluded'

def test_uncertain_format_and_wrong_platform():
    assert match(watch(max_cents=1600),offer(physical=None)).state=='candidate'
    assert match(watch(max_cents=1600),offer(platform='other')).state=='excluded'
    assert match(watch(max_cents=1600),offer(platform='ps4-upgrade')).state=='excluded'
    assert match(watch(max_cents=1600,ps4_upgrade=True),offer(platform='ps4-upgrade')).state=='qualified'

def test_alias_accent_punctuation_and_edition():
    assert match(watch(name='Démons Souls',max_cents=1600),listing()).state=='qualified'
    assert match(watch(name='DS',aliases=["Demon's Souls"],max_cents=1600),listing()).state=='qualified'
    assert match(watch(edition='deluxe',max_cents=1600),listing()).state=='candidate'

def test_bundle_full_price():
    assert match(watch(max_cents=1600),offer(bundle=True)).state=='excluded'
    assert match(watch(bundles=True,max_cents=1500),offer(bundle=True)).state=='over-budget'

def test_price_types_are_not_exact():
    assert match(watch(max_cents=1600),offer(price_kind='from')).state=='candidate'
    assert match(watch(max_cents=1600),offer(price_kind='trade-in')).state=='excluded'

def test_dedup_restart_and_lower_price():
    wid,lid=persist();telegram_config();calls=[]
    sender=lambda *args:(calls.append(args) or True,'Delivered.',0)
    service.deliver(NOW,sender)
    db.init()
    with db.connect() as conn:
        for _ in range(3):service.evaluate(conn,wid,watch(max_cents=1600),lid,listing(),NOW)
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0]==1
        lower=offer(item_cents=1100)
        db.put_listing(conn,lower,NOW+10)
        service.evaluate(conn,wid,watch(max_cents=1600),lid,lower,NOW+10)
    service.deliver(NOW+10,sender)
    with db.connect() as conn:
        db.put_listing(conn,listing(),NOW+20);service.evaluate(conn,wid,watch(max_cents=1600),lid,listing(),NOW+20)
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0]==2
        assert conn.execute('SELECT lowest_cents FROM notified').fetchone()[0]==1500
    assert len(calls)==2

def test_persistent_retry_same_event():
    persist();telegram_config()
    service.deliver(NOW,lambda *_:(False,'Failed safely.',60))
    db.init()
    service.deliver(NOW+61,lambda *_:(True,'Delivered.',0))
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM events').fetchone()
        assert row['state']=='delivered' and row['attempts']==2
        assert conn.execute('SELECT count(*) FROM events').fetchone()[0]==1

def test_quiet_hours_recheck_changed_offer():
    wid,lid=persist();telegram_config()
    with db.connect() as conn:
        db.setting(conn,'quiet_start','11:00');db.setting(conn,'quiet_end','13:00')
    service.deliver(NOW,lambda *_:pytest.fail('Quiet hours sent a notification'))
    with db.connect() as conn:db.put_listing(conn,offer(item_cents=9999),NOW+7200)
    service.deliver(NOW+7200,lambda *_:pytest.fail('Changed price sent a notification'))
    with db.connect() as conn:assert conn.execute('SELECT state FROM events').fetchone()[0]=='cancelled'

def test_schedule_dst_pause_expiry():
    assert not eligible(watch(active=False),NOW)
    assert not eligible(watch(end_at=NOW),NOW)
    assert not eligible(watch(start_at=NOW+1),NOW)
    assert eligible(watch(checking_start='11:00',checking_end='13:00'),NOW)
    assert not eligible(watch(checking_start='22:00',checking_end='08:00'),NOW)
    for stamp in [datetime(2026,10,25,2,30,tzinfo=ZoneInfo('Europe/Paris'),fold=f).timestamp() for f in (0,1)]:
        assert eligible(watch(checking_start='02:00',checking_end='03:00'),stamp)

def test_scheduler_shared_fetch_cooldown_and_failures_preserve():
    persist(watch(max_cents=1600));persist(watch(max_cents=1700))
    calls=[]
    def checker(source):
        calls.append(source);return sources.Outcome('verified working','Fixture only',[listing()])
    worker.tick(NOW,checker)
    worker.tick(NOW+1,checker)
    assert calls==['dealabs']
    with db.connect() as conn:conn.execute('UPDATE sources SET next_at=0');conn.execute('UPDATE watches SET next_at=0')
    worker.tick(NOW+3601,lambda _:sources.Outcome('blocked','403 challenge',[]))
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM listings').fetchone()[0]==1
        assert conn.execute("SELECT status FROM sources WHERE id='dealabs'").fetchone()[0]=='blocked'

def test_lease_prevents_overlap():
    with db.connect() as conn:assert db.acquire(conn,'scheduler','first',NOW,600)
    worker.tick(NOW,lambda _:pytest.fail('Concurrent fetch occurred'))
    with db.connect() as conn:assert not db.acquire(conn,'scheduler','second',NOW)

def test_offset_watch_reuses_shared_source_snapshot():
    persist(watch(max_cents=1600),now=NOW)
    real_listing=listing().model_copy(update={'provenance':'public PS5 RSS feed'})
    worker.tick(NOW,lambda _:sources.Outcome('verified working','Fixture only',[real_listing]))
    later_watch=watch(max_cents=1700)
    with db.connect() as conn:
        conn.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(later_watch.model_dump_json(),NOW+150,NOW+150))
    worker.tick(NOW+150,lambda _:pytest.fail('Source should still be cooling down'))
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM matches WHERE watch_id=2').fetchone()[0]==1

def test_unknown_pickup_can_still_be_candidate_when_delivery_over_budget():
    l=offer(shipping_cents=1000,pickup=True,pickup_fees_cents=None,lat=45.764,lon=4.8357)
    result=match(watch(),l)
    assert result.state=='candidate' and result.route=='pickup' and result.total is None

def test_backup_restore_preserves_data(tmp_path):
    persist()
    target=db.backup(tmp_path/'backup.sqlite3')
    with sqlite3.connect(target) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT count(*) FROM watches').fetchone()[0]==1
        with db.connect() as dest:
            dest.execute('DELETE FROM watches');dest.commit();conn.backup(dest)
    with db.connect() as conn:assert conn.execute('SELECT count(*) FROM watches').fetchone()[0]==1

def test_parser_challenge_and_price():
    with pytest.raises(sources.FetchError):sources.parse_dealabs(b'<html>captcha</html>')
    body=b'''<rss xmlns:p="http://www.pepper.com/rss"><channel><item><title>Demon's Souls PS5</title><p:merchant price="12,00&#8364;"/><description>Physical disc</description><link>https://www.dealabs.com/bons-plans/game-123</link></item></channel></rss>'''
    listings=sources.parse_dealabs(body)
    assert listings[0].item_cents==1200 and listings[0].shipping_cents is None

def test_money_validation_and_ssrf():
    assert cents('12,34')==1234
    for value in ['NaN','-1','1.234']:
        with pytest.raises(ValueError):cents(value)
    with pytest.raises(ValueError):offer(url='http://127.0.0.1/')
