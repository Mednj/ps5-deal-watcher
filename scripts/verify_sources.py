"""One bounded live check per supported source, recording genuine results only."""
import argparse
import json
import time
from app import db,sources
parser=argparse.ArgumentParser();parser.add_argument('--source',choices=list(sources.URLS));args=parser.parse_args()
db.init()
for source in ([args.source] if args.source else list(sources.URLS)):
    now=time.time();outcome=sources.check(source)
    with db.connect() as conn:
        conn.execute('INSERT INTO runs(source,started_at,ended_at,status,count,message) VALUES(?,?,?,?,?,?)',(source,now,time.time(),outcome.status,len(outcome.listings),'Deployment verification: '+outcome.message))
        conn.execute('UPDATE sources SET status=?,message=?,last_success=CASE WHEN ? THEN ? ELSE last_success END WHERE id=?',(outcome.status,outcome.message,outcome.status in ('verified working','experimental'),now,source))
        for listing in outcome.listings:db.put_listing(conn,listing,now)
    print(json.dumps({'source':source,'status':outcome.status,'count':len(outcome.listings),'message':outcome.message,'examples':[{'title':l.title,'item_cents':l.item_cents,'price_kind':l.price_kind} for l in outcome.listings[:3]]},ensure_ascii=False))
