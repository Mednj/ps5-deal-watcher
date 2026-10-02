import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import random
import secrets
import signal
import time

from . import db, sources, service
from .models import Watch, Listing
from .matching import eligible, manual_check

STOP=False
def stop(*_):
    global STOP
    STOP=True

def tick(now=None,checker=sources.check):
    realtime=now is None
    now=time.time() if now is None else now
    owner=secrets.token_hex(12)
    with db.connect() as conn:
        if not db.acquire(conn,'scheduler',owner,now,600):return
        db.setting(conn,'worker_heartbeat',now)
    token=None
    try:
        with db.connect() as conn:
            config=db.settings(conn)
            watches=[(r['id'],Watch.model_validate_json(r['data']),r['next_at']) for r in conn.execute('SELECT * FROM watches')]
            manual=config.get('manual_check_requested')=='1'
            token=manual_check.set(manual)
            if manual:
                db.setting(conn,'manual_check_requested',0)
                db.setting(conn,'manual_check_running',1)
            due=[(i,w) for i,w,next_at in watches if (manual or next_at<=now) and eligible(w,now)]
            active_sources=list(conn.execute('SELECT * FROM sources' if manual else 'SELECT * FROM sources WHERE enabled=1'))
        def fetch(source_id):
            thread_token=manual_check.set(manual)
            try:
                return checker(source_id)
            except Exception:
                return sources.Outcome('error','Source check failed; retry later.',[])
            finally:manual_check.reset(thread_token)
        executor=ThreadPoolExecutor(max_workers=4)
        tasks={}
        try:
            for source in active_sources:
                interested=[(i,w) for i,w in due if source['id'] in w.sources]
                if not interested or (not manual and source['next_at']>now):continue
                source_id=source['id']
                with db.connect() as conn:
                    if not db.acquire(conn,'source:'+source_id,owner,now,180):continue
                    conn.execute("INSERT INTO runs(source,started_at,status) VALUES(?,?,'running')",(source_id,now))
                    run_id=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                tasks[executor.submit(fetch,source_id)]=(source,interested,run_id)
            def completed():
                pending=set(tasks)
                while pending:
                    done,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
                    with db.connect() as conn:db.setting(conn,'worker_heartbeat',time.time() if realtime else now)
                    yield from done
            for future in completed():
                source,interested,run_id=tasks[future]
                source_id=source['id']
                outcome=future.result()
                finished=time.time() if realtime else now
                success=outcome.status in ('verified working','experimental')
                failures=0 if success else source['failures']+1
                interval=max(sources.MIN_INTERVAL[source_id],min(w.interval_minutes*60 for _,w in interested))
                backoff=max(outcome.retry_after,min(86400,interval*2**min(failures,5))) if failures else interval
                if outcome.status=='blocked' or failures>=3:backoff=max(backoff,86400)
                next_at=finished+backoff+(0 if success and source_id in ('dealabs','vinted','leboncoin') else random.uniform(1,30))
                with db.connect() as conn:
                    if success:
                        listing_ids=[]
                        for listing in outcome.listings:
                            listing_id=db.put_listing(conn,listing,finished)
                            listing_ids.append((listing_id,listing.model_copy(update={'observed_at':finished})))
                        for watch_id,watch in interested:
                            for listing_id,listing in listing_ids:service.evaluate(conn,watch_id,watch,listing_id,listing,finished)
                        conn.execute('UPDATE sources SET last_success=? WHERE id=?',(finished,source_id))
                    conn.execute('UPDATE sources SET status=?,message=?,failures=?,next_at=? WHERE id=?',(outcome.status,outcome.message,failures,next_at,source_id))
                    conn.execute('UPDATE runs SET ended_at=?,status=?,count=?,message=? WHERE id=?',(finished,outcome.status,len(outcome.listings),outcome.message,run_id))
                    conn.execute('DELETE FROM leases WHERE name=? AND owner=?',('source:'+source_id,owner))
                service.deliver(finished)
        finally:executor.shutdown(wait=True)
        with db.connect() as conn:
            for watch_id,watch in due:
                # Coalesce missed checks after restart; never replay a backlog.
                conn.execute('UPDATE watches SET next_at=? WHERE id=?',(now+watch.interval_minutes*60,watch_id))
                # Offset watch schedules must reuse a fresh shared source snapshot.
                # Otherwise a watch whose poll follows another watch's fetch can starve forever.
                enabled={r['id'] for r in conn.execute('SELECT id FROM sources WHERE enabled=1')}
                for row in ([] if manual else conn.execute('SELECT * FROM listings WHERE last_at>?',(now-21600,)).fetchall()):
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
        if token is not None:manual_check.reset(token)
        with db.connect() as conn:
            conn.execute('DELETE FROM leases WHERE owner=?',(owner,))
            db.setting(conn,'manual_check_running',0)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    db.init()
    recover_restart()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not STOP:
        try:tick()
        except Exception:
            # Error details can contain remote tokens. Keep operational logs bounded and safe.
            print('Worker cycle failed; will retry. Check source health and activity.',flush=True)
        if args.once:break
        for _ in range(10):
            if STOP:break
            time.sleep(1)
            with db.connect() as conn:
                if db.settings(conn).get('manual_check_requested')=='1':break

def recover_restart():
    # Compose runs exactly one worker. Never scale it without revisiting startup ownership.
    now=time.time()
    with db.connect() as conn:
        if db.settings(conn).get('manual_check_running')=='1':
            db.setting(conn,'manual_check_requested',1)
        db.setting(conn,'manual_check_running',0)
        conn.execute("UPDATE runs SET ended_at=?,status='interrupted',message='Worker restarted during check; queued for retry.' WHERE ended_at IS NULL",(now,))
        conn.execute("DELETE FROM leases WHERE name='scheduler' OR name LIKE 'source:%'")
        conn.execute('UPDATE sources SET next_at=MIN(next_at,?) WHERE id IN (SELECT source FROM runs WHERE ended_at=? AND status=?)',(now,now,'interrupted'))
        db.setting(conn,'worker_heartbeat',now)

if __name__=='__main__':main()
