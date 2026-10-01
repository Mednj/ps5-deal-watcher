import argparse
import json
import random
import secrets
import signal
import time

from . import db, sources, service
from .models import Watch, Listing
from .matching import eligible

STOP=False
def stop(*_):
    global STOP
    STOP=True

def tick(now=None,checker=sources.check):
    now=time.time() if now is None else now
    owner=secrets.token_hex(12)
    with db.connect() as conn:
        if not db.acquire(conn,'scheduler',owner,now,600):return
        db.setting(conn,'worker_heartbeat',now)
    try:
        with db.connect() as conn:
            config=db.settings(conn)
            watches=[(r['id'],Watch.model_validate_json(r['data']),r['next_at']) for r in conn.execute('SELECT * FROM watches')]
            due=[(i,w) for i,w,next_at in watches if next_at<=now and eligible(w,now)]
            active_sources=list(conn.execute('SELECT * FROM sources WHERE enabled=1'))
        for source in active_sources:
            interested=[(i,w) for i,w in due if source['id'] in w.sources]
            if not interested or source['next_at']>now:continue
            source_id=source['id']
            with db.connect() as conn:
                if not db.acquire(conn,'source:'+source_id,owner,now,180):continue
                conn.execute("INSERT INTO runs(source,started_at,status) VALUES(?,?,'running')",(source_id,now))
                run_id=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            outcome=checker(source_id)
            finished=time.time() if now is None else now
            success=outcome.status in ('verified working','experimental')
            failures=0 if success else source['failures']+1
            interval=max(sources.MIN_INTERVAL[source_id],min(w.interval_minutes*60 for _,w in interested))
            backoff=max(outcome.retry_after,min(86400,interval*2**min(failures,5))) if failures else interval
            if outcome.status=='blocked' or failures>=3:backoff=max(backoff,86400)
            next_at=now+backoff+random.uniform(1,30)
            with db.connect() as conn:
                if success:
                    listing_ids=[]
                    for listing in outcome.listings:
                        listing_id=db.put_listing(conn,listing,now)
                        listing_ids.append((listing_id,listing.model_copy(update={'observed_at':now})))
                    for watch_id,watch in interested:
                        for listing_id,listing in listing_ids:service.evaluate(conn,watch_id,watch,listing_id,listing,now)
                    conn.execute('UPDATE sources SET last_success=? WHERE id=?',(now,source_id))
                conn.execute('UPDATE sources SET status=?,message=?,failures=?,next_at=? WHERE id=?',(outcome.status,outcome.message,failures,next_at,source_id))
                conn.execute('UPDATE runs SET ended_at=?,status=?,count=?,message=? WHERE id=?',(now,outcome.status,len(outcome.listings),outcome.message,run_id))
                conn.execute('DELETE FROM leases WHERE name=? AND owner=?',('source:'+source_id,owner))
        with db.connect() as conn:
            for watch_id,watch in due:
                # Coalesce missed checks after restart; never replay a backlog.
                conn.execute('UPDATE watches SET next_at=? WHERE id=?',(now+watch.interval_minutes*60,watch_id))
                # Offset watch schedules must reuse a fresh shared source snapshot.
                # Otherwise a watch whose poll follows another watch's fetch can starve forever.
                enabled={r['id'] for r in conn.execute('SELECT id FROM sources WHERE enabled=1')}
                for row in conn.execute('SELECT * FROM listings WHERE last_at>?',(now-21600,)).fetchall():
                    listing=Listing.model_validate_json(row['data'])
                    if listing.provenance=='manual entry' or listing.source in enabled:
                        service.evaluate(conn,watch_id,watch,row['id'],listing,now)
            retention=int(config.get('retention_days','90'))*86400
            conn.execute('DELETE FROM observations WHERE at<?',(now-retention,))
            conn.execute('DELETE FROM runs WHERE started_at<?',(now-retention,))
            # Preserve listings, events and notified price minima for deduplication.
            db.setting(conn,'worker_heartbeat',time.time())
        service.deliver(now)
    finally:
        with db.connect() as conn:conn.execute('DELETE FROM leases WHERE owner=?',(owner,))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    db.init();signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not STOP:
        try:tick()
        except Exception:
            # Error details can contain remote tokens. Keep operational logs bounded and safe.
            print('Worker cycle failed; will retry. Check source health and activity.',flush=True)
        if args.once:break
        for _ in range(10):
            if STOP:break
            time.sleep(1)

if __name__=='__main__':main()
