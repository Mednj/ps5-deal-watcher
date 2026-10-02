"""Independent operational monitoring; never makes marketplace requests."""
import json
import os
import signal
import time
import httpx
from pathlib import Path
from . import db, service, sources
from .matching import eligible, quiet, match
from .models import Watch, Listing

SUCCESS = ('verified working', 'experimental')

def probe(url):
    try:
        with httpx.Client(timeout=5, trust_env=False) as client:
            response=client.get(url)
            return response.status_code==200 and response.json().get('ready', True)
    except Exception:return False

def read_json(url):
    try:
        with httpx.Client(timeout=3,trust_env=False) as client:
            response=client.get(url)
            response.raise_for_status()
            return response.json()
    except Exception:return None

def backup_healthy(directory='/backups',now=None):
    now=time.time() if now is None else now
    files=list(Path(directory).glob('watcher-*.sqlite3'))
    return bool(files and now-max(p.stat().st_mtime for p in files)<48*3600)

def snapshot(conn, now, health, browser_progress=None):
    cfg=db.settings(conn)
    problems={}
    for key,ok in health.items():
        if not ok:problems[key]=f'{key.title()} service unavailable'
    age=max(0,now-float(cfg.get('worker_heartbeat',0)))
    if age>90:problems['worker']='Worker heartbeat stale'
    source_stats=[]
    watches=[Watch.model_validate_json(r['data']) for r in conn.execute('SELECT data FROM watches')]
    for source in conn.execute('SELECT * FROM sources'):
        runs=[dict(r) for r in conn.execute('SELECT * FROM runs WHERE source=? AND started_at>=? ORDER BY id DESC',(source['id'],now-86400))]
        finished=[r for r in runs if r['ended_at'] is not None]
        durations=sorted(max(0,r['ended_at']-r['started_at']) for r in finished)
        successes=sum(r['status'] in SUCCESS for r in finished)
        source_stats.append({'name':source['id'], 'checks':len(finished), 'success_rate':round(100*successes/len(finished),1) if finished else None,
            'average_seconds':round(sum(durations)/len(durations),1) if durations else None,
            'p95_seconds':round(durations[min(len(durations)-1,int(len(durations)*.95))],1) if durations else None,
            'last_success':source['last_success'], 'listings':sum(r['count'] for r in finished), 'failures':source['failures'], 'status':source['status']})
        if source['failures']>=3 and (source['enabled'] or runs):problems['source:'+source['id']]=f"{source['id'].title()}: three or more consecutive failed checks"
        if (source['enabled'] and now-source['next_at']>600
                and any(source['id'] in w.sources and eligible(w,now,allow_manual=False) for w in watches)
                and not any(r['ended_at'] is None for r in runs)):
            problems['schedule:'+source['id']]=f"{source['id'].title()}: scheduled check overdue by over 10 minutes"
    for run in conn.execute("SELECT * FROM runs WHERE ended_at IS NULL"):
        budget=sources.CHECK_TIMEOUT.get(run['source'],180)
        if now-run['started_at']>budget:
            problems['stuck:'+run['source']]=f"{run['source'].title()} check exceeds {budget}-second budget"
    overdue=0
    eligible_ids=set()
    rows=conn.execute("SELECT e.*, w.data watch, l.data listing, l.last_at FROM events e JOIN watches w ON w.id=e.watch_id JOIN listings l ON l.id=e.listing_id WHERE e.state IN ('pending','sending')").fetchall()
    for event in rows:
        watch=Watch.model_validate_json(event['watch']); listing=Listing.model_validate_json(event['listing'])
        result=match(watch,listing)
        previous=conn.execute('SELECT lowest_cents FROM notified WHERE watch_id=? AND listing_id=?',(event['watch_id'],event['listing_id'])).fetchone()
        ready=(not quiet(cfg,now) and watch.active and (watch.end_at is None or now<watch.end_at)
            and (event['manual'] or eligible(watch,now,allow_manual=False)) and now-event['last_at']<=21600
            and result.state=='qualified' and result.total==event['price_cents']
            and (previous is None or event['price_cents']<previous['lowest_cents']))
        if not ready:continue
        eligible_ids.add(event['id'])
        # Retry backoff is still delivery delay; intentional schedule holds reset this timer.
        conn.execute('INSERT OR IGNORE INTO monitor_pending VALUES(?,?)',(event['id'],now))
        since=conn.execute('SELECT since FROM monitor_pending WHERE event_id=?',(event['id'],)).fetchone()[0]
        if now-since>=600:overdue+=1
    for row in conn.execute('SELECT event_id FROM monitor_pending').fetchall():
        if row[0] not in eligible_ids:conn.execute('DELETE FROM monitor_pending WHERE event_id=?',(row[0],))
    if overdue:problems['telegram']=f'{overdue} eligible notification(s) delayed over 10 minutes'
    attempts=conn.execute('SELECT count(*) total, COALESCE(sum(success),0) success FROM attempts WHERE at>=?',(now-86400,)).fetchone()
    delay=conn.execute('SELECT avg(a.at-e.created_at) FROM events e JOIN attempts a ON a.event_id=e.id WHERE a.success=1 AND a.at>=?',(now-86400,)).fetchone()[0]
    manual_delay=None
    requested=float(cfg.get('last_manual_check',0))
    if requested:
        started=conn.execute('SELECT min(started_at) FROM runs WHERE started_at>=?',(requested,)).fetchone()[0]
        if started is not None:manual_delay=round(started-requested,1)
        elif cfg.get('manual_check_requested')=='1' and now-requested>180:problems['manual']='Manual check has been queued over three minutes'
    data={'at':now,'health':health,'worker_age':round(age,1),'sources':source_stats,'pending':len(rows),'overdue':overdue,
        'telegram_attempts':attempts['total'],'telegram_failures':attempts['total']-attempts['success'],
        'delivery_delay':round(delay,1) if delay is not None else None,'manual_delay':manual_delay,
        'browser_progress':browser_progress}
    return data,problems

def tick(now=None, health=None, sender=service.send_telegram):
    now=time.time() if now is None else now
    if health is None:
        health={'web':probe(os.environ.get('MONITOR_WEB_URL','http://web:8765/health/ready')),
            'browser':probe(os.environ.get('MONITOR_BROWSER_URL','http://browser:8770/health')),
            'backups':backup_healthy(os.environ.get('MONITOR_BACKUP_DIR','/backups'),now)}
        browser_url=os.environ.get('MONITOR_BROWSER_URL','http://browser:8770/health').removesuffix('/health')
        browser_progress=read_json(browser_url+'/status')
    else:browser_progress=None
    with db.connect() as conn:
        data,problems=snapshot(conn,now,health,browser_progress)
        for key,title in problems.items():
            conn.execute('INSERT INTO monitor_incidents(key,title,since,updated_at) VALUES(?,?,?,?) ON CONFLICT(key) DO UPDATE SET title=excluded.title, since=CASE WHEN monitor_incidents.active=0 THEN excluded.since ELSE monitor_incidents.since END, notified=CASE WHEN monitor_incidents.active=0 THEN 0 ELSE monitor_incidents.notified END, next_alert=CASE WHEN monitor_incidents.active=0 THEN 0 ELSE monitor_incidents.next_alert END, active=1,updated_at=excluded.updated_at',(key,title,now,now))
        for row in conn.execute('SELECT key FROM monitor_incidents WHERE active=1').fetchall():
            if row['key'] not in problems:conn.execute('UPDATE monitor_incidents SET active=0,updated_at=? WHERE key=?',(now,row['key']))
        conn.execute('INSERT OR REPLACE INTO monitor_samples VALUES(?,?)',(now,json.dumps(data)))
        conn.execute('DELETE FROM monitor_samples WHERE at<?',(now-7*86400,))
        db.setting(conn,'monitor_heartbeat',now)
        token,chat=service.telegram_credentials(conn)
        alerts=[dict(r) for r in conn.execute('SELECT * FROM monitor_incidents WHERE next_alert<=?',(now,))]
    for incident in alerts:
        failure=incident['active'] and not incident['notified'] and (incident['key'] not in ('web','browser','worker') or now-incident['since']>=180)
        recovery=not incident['active'] and incident['notified']==1
        if not token or not chat or not (failure or recovery):continue
        ok,_,retry=sender(token,chat,f"PS5 Deal Watcher monitoring\n{'ALERT' if failure else 'RECOVERED'}: {incident['title']}")
        with db.connect() as conn:
            conn.execute('UPDATE monitor_incidents SET notified=?,next_alert=? WHERE key=?',(int(failure) if ok else incident['notified'],now+max(60,retry) if not ok else 0,incident['key']))
    return data

def dashboard():
    with db.connect() as conn:
        row=conn.execute('SELECT data FROM monitor_samples ORDER BY at DESC LIMIT 1').fetchone()
        data=json.loads(row[0]) if row else None
        incidents=[dict(r) for r in conn.execute('SELECT * FROM monitor_incidents ORDER BY active DESC,updated_at DESC LIMIT 30')]
    return {'metrics':data,'incidents':incidents}

def main():
    db.init()
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopping:
        try:tick()
        except Exception:print('Monitoring cycle failed; retrying. No credentials logged.',flush=True)
        for _ in range(30):
            if stopping:break
            time.sleep(1)

if __name__=='__main__':main()
