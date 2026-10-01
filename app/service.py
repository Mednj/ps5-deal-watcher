import json
import os
import secrets
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from . import db
from .matching import match, eligible, quiet
from .models import Listing, Watch

def money(value):
    return 'Unknown' if value is None else f'€{value/100:.2f}'

def notification(watch,listing,result):
    return (f'PS5 Deal Watcher · {watch.name}\n{listing.title}\nSource: {listing.source}\n'
            f'Item: {money(listing.item_cents)} · Shipping: {money(listing.shipping_cents)}\n'
            f'Delivery fees: {money(listing.fees_cents)} · Pickup fees: {money(listing.pickup_fees_cents)}\n'
            f'{watch.basis} {result.route} price: {money(result.total)}\n'
            f'Condition: {listing.condition} · Location: {listing.location or "Not supplied"}\n'
            f'{result.reason}\n{listing.url}')[:4000]

def evaluate(conn,watch_id,watch,listing_id,listing,now):
    result=match(watch,listing)
    conn.execute('INSERT INTO matches(watch_id,listing_id,state,reason,total_cents,route,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(watch_id,listing_id) DO UPDATE SET state=excluded.state,reason=excluded.reason,total_cents=excluded.total_cents,route=excluded.route,updated_at=excluded.updated_at', (watch_id,listing_id,result.state,result.reason,result.total,result.route,now))
    if result.state!='qualified' or not eligible(watch,now):return result
    # Dedup against events as well as successfully delivered prices; retry is the same event.
    prev=conn.execute('SELECT lowest_cents FROM notified WHERE watch_id=? AND listing_id=?',(watch_id,listing_id)).fetchone()
    pending=conn.execute("SELECT MIN(price_cents) price FROM events WHERE watch_id=? AND listing_id=? AND state != 'cancelled'",(watch_id,listing_id)).fetchone()['price']
    lowest=min([p for p in [prev['lowest_cents'] if prev else None,pending] if p is not None], default=None)
    if lowest is not None and (not watch.notify_drops or result.total>=lowest):return result
    conn.execute("INSERT INTO events(watch_id,listing_id,price_cents,next_at,created_at,message) VALUES(?,?,?,?,?,?) ON CONFLICT(watch_id,listing_id,price_cents) DO UPDATE SET state='pending',next_at=excluded.next_at,message=excluded.message,last_error='' WHERE events.state='cancelled'",(watch_id,listing_id,result.total,now,now,notification(watch,listing,result)))
    return result

def reevaluate_watch(conn,watch_id,now):
    row=conn.execute('SELECT data FROM watches WHERE id=?',(watch_id,)).fetchone()
    if not row:return
    watch=Watch.model_validate_json(row['data'])
    for row in conn.execute('SELECT * FROM listings WHERE last_at>?',(now-86400,)).fetchall():
        evaluate(conn,watch_id,watch,row['id'],Listing.model_validate_json(row['data']),now)

def telegram_credentials(conn):
    config=db.settings(conn)
    return os.environ.get('TELEGRAM_BOT_TOKEN','') or config.get('telegram_token',''),os.environ.get('TELEGRAM_CHAT_ID','') or config.get('telegram_chat','')

def send_telegram(token,chat,message):
    if not token or not chat:return False,'Telegram is not configured.',300
    # Do not log httpx exceptions: their URL includes the token.
    try:
        with httpx.Client(timeout=15,trust_env=False) as client:
            response=client.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat,'text':message,'link_preview_options':{'is_disabled':True}})
            payload=response.json()
            if response.status_code==200 and payload.get('ok'):return True,'Delivered.',0
            wait=int(payload.get('parameters',{}).get('retry_after',60))
            return False,f'Telegram rejected delivery (HTTP {response.status_code}). Check destination and bot access.',max(60,min(wait,86400))
    except Exception:return False,'Telegram connection failed or response was invalid.',60

def deliver(now=None,sender=send_telegram):
    now=time.time() if now is None else now
    owner=secrets.token_hex(8)
    with db.connect() as conn:
        if not db.acquire(conn,'delivery',owner,now,120):return
    try:
        with db.connect() as conn:
            config=db.settings(conn)
            if quiet(config,now):return
            token,chat=telegram_credentials(conn)
            if not token or not chat:return
            # Recover uncertain sends after a worker crash. Telegram has no idempotency key.
            conn.execute("UPDATE events SET state='pending' WHERE state='sending' AND next_at<?",(now,))
            rows=conn.execute("SELECT * FROM events WHERE state='pending' AND next_at<=? ORDER BY id LIMIT 10",(now,)).fetchall()
        for event in rows:
            with db.connect() as conn:
                w=conn.execute('SELECT data FROM watches WHERE id=?',(event['watch_id'],)).fetchone()
                l=conn.execute('SELECT data,last_at FROM listings WHERE id=?',(event['listing_id'],)).fetchone()
                if not w or not l:continue
                watch=Watch.model_validate_json(w['data']); listing=Listing.model_validate_json(l['data'])
                if not watch.active or (watch.end_at is not None and now>=watch.end_at):
                    conn.execute("UPDATE events SET state='cancelled',last_error='Watch paused or expired.' WHERE id=?",(event['id'],));continue
                if not eligible(watch,now):continue
                result=match(watch,listing)
                previous=conn.execute('SELECT lowest_cents FROM notified WHERE watch_id=? AND listing_id=?',(event['watch_id'],event['listing_id'])).fetchone()
                if result.state!='qualified' or result.total!=event['price_cents'] or (previous and event['price_cents']>=previous['lowest_cents']):
                    conn.execute("UPDATE events SET state='cancelled',last_error='Listing no longer qualifies at this event price.' WHERE id=?",(event['id'],));continue
                # Never send an old queued offer with no fresh observation.
                if now-l['last_at']>21600:
                    conn.execute("UPDATE events SET next_at=?,last_error='Waiting for a fresh observation.' WHERE id=?",(now+300,event['id']));continue
                conn.execute("UPDATE events SET state='sending',next_at=? WHERE id=? AND state='pending'",(now+120,event['id']))
            success,detail,retry=sender(token,chat,event['message'])
            with db.connect() as conn:
                conn.execute('INSERT INTO attempts(event_id,at,success,detail) VALUES(?,?,?,?)',(event['id'],now,int(success),detail))
                conn.execute('UPDATE events SET state=?,attempts=attempts+1,next_at=?,last_error=? WHERE id=?',('delivered' if success else 'pending',now+max(retry,min(86400,60*2**min(event['attempts'],10))),'' if success else detail,event['id']))
                if success:
                    conn.execute('INSERT INTO notified VALUES(?,?,?) ON CONFLICT(watch_id,listing_id) DO UPDATE SET lowest_cents=MIN(lowest_cents,excluded.lowest_cents)',(event['watch_id'],event['listing_id'],event['price_cents']))
    finally:
        with db.connect() as conn:conn.execute('DELETE FROM leases WHERE name=? AND owner=?',('delivery',owner))
