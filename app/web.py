from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware

from . import db, service, sources
from .models import Watch, Listing, SOURCES, CENTRES, cents

ROOT=Path(__file__).parent
db.init()
with db.connect() as conn:
    config=db.settings(conn)
    if not config.get('session_key'):
        db.setting(conn,'session_key',secrets.token_hex(32))
    SECRET=db.settings(conn)['session_key']

app=FastAPI(title='PS5 Deal Watcher',docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(SessionMiddleware,secret_key=SECRET,same_site='strict',https_only=os.environ.get('COOKIE_SECURE','false').lower()=='true',max_age=43200)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
templates=Jinja2Templates(directory=ROOT/'templates')
templates.env.filters['money']=service.money
def date(value):
    if value is None:return 'Not yet'
    return datetime.fromtimestamp(float(value),ZoneInfo('Europe/Paris')).strftime('%d %b · %H:%M')
templates.env.filters['date']=date

def password_ok(password):
    encoded=os.environ.get('APP_PASSWORD_HASH','')
    try:
        algorithm,salt,digest=encoded.split('$')
        return algorithm=='scrypt' and hmac.compare_digest(hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex(),digest)
    except Exception:return False

def auth(request):
    if os.environ.get('APP_PASSWORD_HASH') and not request.session.get('authenticated'):
        raise HTTPException(401,'Sign in required.')

async def form(request):
    auth(request)
    data=await request.form()
    expected=request.session.get('csrf','')
    if not expected or not secrets.compare_digest(str(data.get('csrf','')),expected):
        raise HTTPException(403,'Form expired. Reload the page and try again.')
    return data

def redirect(path,message=''):
    return RedirectResponse(path+('?' + urlencode({'message':message}) if message else ''),status_code=303)

@app.middleware('http')
async def security_headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://static-pepper.dealabs.com; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    response.headers['Cache-Control']='no-store'
    return response

def render(request,template,**context):
    if os.environ.get('APP_PASSWORD_HASH') and not request.session.get('authenticated'):
        return redirect('/login')
    if 'csrf' not in request.session:request.session['csrf']=secrets.token_hex(24)
    with db.connect() as conn:
        cfg=db.settings(conn)
        heartbeat=float(cfg.get('worker_heartbeat',0))
    base={'request':request,'csrf':request.session['csrf'],'page':request.url.path,'message':request.query_params.get('message',''),'worker_ok':time.time()-heartbeat<90,'sources_names':SOURCES,'centres':CENTRES,'login_enabled':bool(os.environ.get('APP_PASSWORD_HASH')),'now':time.time()}
    return templates.TemplateResponse(request=request,name=template,context={**base,**context})

@app.get('/health/live')
def live():return {'status':'ok','version':'0.1.0'}

@app.get('/health/ready')
def ready():
    with db.connect() as conn:conn.execute('SELECT 1').fetchone()
    return {'database':'ok'}

@app.get('/health/worker')
def worker_health():
    with db.connect() as conn:heartbeat=float(db.settings(conn).get('worker_heartbeat',0))
    if time.time()-heartbeat>90:raise HTTPException(503,'Worker heartbeat stale.')
    return {'worker':'ok'}

@app.get('/login')
def login_page(request:Request):
    if not os.environ.get('APP_PASSWORD_HASH'):return redirect('/')
    request.session.setdefault('csrf',secrets.token_hex(24))
    return templates.TemplateResponse(request=request,name='login.html',context={'request':request,'csrf':request.session['csrf'],'message':request.query_params.get('message','')})

@app.post('/login')
async def login(request:Request):
    data=await request.form()
    if not hmac.compare_digest(str(data.get('csrf','')),request.session.get('csrf','missing')):raise HTTPException(403)
    with db.connect() as conn:
        cfg=db.settings(conn)
        if float(cfg.get('login_retry_at',0))>time.time():return redirect('/login','Please wait before trying again.')
        if not password_ok(str(data.get('password',''))):
            failures=int(cfg.get('login_failures',0))+1
            db.setting(conn,'login_failures',failures)
            db.setting(conn,'login_retry_at',time.time()+min(300,2**min(failures,8)))
            return redirect('/login','Password incorrect.')
        db.setting(conn,'login_failures',0);db.setting(conn,'login_retry_at',0)
    request.session.clear();request.session['authenticated']=True;request.session['csrf']=secrets.token_hex(24)
    return redirect('/')

@app.post('/logout')
async def logout(request:Request):
    await form(request);request.session.clear();return redirect('/login')

@app.get('/')
def home(request:Request):
    with db.connect() as conn:
        watches=[]
        for row in conn.execute('SELECT * FROM watches ORDER BY id DESC'):
            watches.append({**dict(row),**json.loads(row['data'])})
        source_rows=list(conn.execute('SELECT * FROM sources'))
        counts={r['state']:r['n'] for r in conn.execute('SELECT state,count(*) n FROM matches WHERE hidden=0 GROUP BY state')}
        pending=conn.execute("SELECT count(*) FROM events WHERE state IN ('pending','sending')").fetchone()[0]
        token,chat=service.telegram_credentials(conn)
    return render(request,'home.html',watches=watches,source_rows=source_rows,counts=counts,pending=pending,telegram_ready=bool(token and chat))

def local_input(stamp,zone):
    return datetime.fromtimestamp(stamp,ZoneInfo(zone)).strftime('%Y-%m-%dT%H:%M') if stamp is not None else ''

@app.get('/watches/new')
def new_watch(request:Request):
    with db.connect() as conn:cfg=db.settings(conn)
    watch=Watch(name='New watch',max_cents=1500,interval_minutes=int(cfg['default_interval']),timezone=cfg['timezone']).model_dump()
    watch['name']=''
    return render(request,'watch.html',watch=watch,watch_id=None,start_value='',end_value='')

@app.get('/watches/{watch_id}/edit')
def edit_watch(request:Request,watch_id:int):
    with db.connect() as conn:row=conn.execute('SELECT data FROM watches WHERE id=?',(watch_id,)).fetchone()
    if not row:raise HTTPException(404)
    watch=json.loads(row['data'])
    return render(request,'watch.html',watch=watch,watch_id=watch_id,start_value=local_input(watch['start_at'],watch['timezone']),end_value=local_input(watch['end_at'],watch['timezone']))

def timestamp(value,zone):
    if not value:return None
    local=datetime.fromisoformat(value)
    if local.tzinfo:raise ValueError('Enter a local date and time.')
    zoned=local.replace(tzinfo=ZoneInfo(zone),fold=0)
    # Reject nonexistent DST times rather than silently changing them.
    if datetime.fromtimestamp(zoned.timestamp(),ZoneInfo(zone)).replace(tzinfo=None)!=local:
        raise ValueError('This local time does not exist due to daylight saving. Choose another time.')
    return zoned.timestamp()

def watch_from_form(data):
    zone=str(data.get('timezone','Europe/Paris'))
    return Watch(qualification=str(data.get('qualification','name-price')),name=data['name'],aliases=[s.strip() for s in str(data.get('aliases','')).split(',') if s.strip()],excluded=[s.strip() for s in str(data.get('excluded','')).split(',') if s.strip()],edition=str(data.get('edition','')),language=str(data.get('language','')),max_cents=cents(str(data['budget'])),basis=data['basis'],condition=data['condition'],sources=data.getlist('sources'),delivery='delivery' in data,pickup='pickup' in data,centres=data.getlist('centres'),radius_km=int(data['radius_km']),interval_minutes=int(data['interval_minutes']),timezone=zone,start_at=timestamp(str(data.get('start_at','')),zone),end_at=timestamp(str(data.get('end_at','')),zone),checking_start=data['checking_start'],checking_end=data['checking_end'],ps4_upgrade='ps4_upgrade' in data,bundles='bundles' in data,notify_drops='notify_drops' in data,active='active' in data)

@app.post('/watches/save')
async def save_watch(request:Request):
    data=await form(request)
    watch_id=int(data['watch_id']) if data.get('watch_id') else None
    try:watch=watch_from_form(data)
    except (ValueError,KeyError,ValidationError) as exc:return redirect(f'/watches/{watch_id}/edit' if watch_id else '/watches/new','Please check the form: '+str(exc)[:250])
    now=time.time()
    with db.connect() as conn:
        if watch_id:
            if not conn.execute('SELECT 1 FROM watches WHERE id=?',(watch_id,)).fetchone():raise HTTPException(404)
            conn.execute('UPDATE watches SET data=?,next_at=? WHERE id=?',(watch.model_dump_json(),now,watch_id))
        else:
            conn.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(watch.model_dump_json(),now,now))
            watch_id=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        service.reevaluate_watch(conn,watch_id,now)
    return redirect('/','Watch saved. Checks respect each source’s minimum interval.')

@app.post('/watches/{watch_id}/{action}')
async def watch_action(request:Request,watch_id:int,action:str):
    await form(request)
    with db.connect() as conn:
        row=conn.execute('SELECT data FROM watches WHERE id=?',(watch_id,)).fetchone()
        if not row:raise HTTPException(404)
        watch=Watch.model_validate_json(row['data'])
        if action=='delete':conn.execute('DELETE FROM watches WHERE id=?',(watch_id,))
        elif action=='duplicate':
            watch.active=False
            conn.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(watch.model_dump_json(),time.time(),time.time()))
        elif action in ('pause','resume'):
            watch.active=action=='resume'
            conn.execute('UPDATE watches SET data=?,next_at=? WHERE id=?',(watch.model_dump_json(),time.time(),watch_id))
            if action=='pause':conn.execute("UPDATE events SET state='cancelled',last_error='Watch paused.' WHERE watch_id=? AND state='pending'",(watch_id,))
        else:raise HTTPException(404)
    return redirect('/','Watch '+action+' completed.')

@app.post('/check-now')
async def check_now(request:Request):
    await form(request);now=time.time()
    with db.connect() as conn:
        config=db.settings(conn)
        if config.get('manual_check_running')=='1' or config.get('manual_check_requested')=='1':
            return redirect('/activity','An immediate check is already running or queued.')
        db.setting(conn,'last_manual_check',now)
        db.setting(conn,'manual_check_requested',1)
    return redirect('/activity','Immediate check requested across all selected sources. Checking hours and source cooldowns are bypassed for this pass.')

@app.get('/deals')
def deals(request:Request):
    state=request.query_params.get('state','all');source=request.query_params.get('source','all')
    sort=request.query_params.get('sort','newest')
    with db.connect() as conn:
        rows=conn.execute('SELECT m.*,l.data,l.last_at,l.first_at,w.data watch FROM matches m JOIN listings l ON l.id=m.listing_id JOIN watches w ON w.id=m.watch_id WHERE m.hidden=0 AND m.state IN (\'qualified\',\'candidate\')').fetchall()
    items=[]
    for row in rows:
        if state!='all' and row['state']!=state:continue
        listing=json.loads(row['data'])
        if source!='all' and listing['source']!=source:continue
        image=urlsplit(listing.get('image',''))
        safe_image=listing.get('image','') if image.scheme=='https' and image.hostname=='static-pepper.dealabs.com' and not image.username and not image.password else ''
        items.append({**dict(row),**listing,'watch_name':json.loads(row['watch'])['name'],'safe_image':safe_image})
    items.sort(key=lambda x:(x['total_cents'] is None,x['total_cents'] if x['total_cents'] is not None else x['item_cents']) if sort=='price' else -x['first_at'])
    return render(request,'deals.html',items=items,state=state,source=source,sort=sort)

@app.post('/deals/{watch_id}/{listing_id}/hide')
async def hide(request:Request,watch_id:int,listing_id:int):
    await form(request)
    with db.connect() as conn:conn.execute('UPDATE matches SET hidden=1 WHERE watch_id=? AND listing_id=?',(watch_id,listing_id))
    return redirect('/deals','Deal hidden.')

@app.get('/sources')
def source_page(request:Request):
    with db.connect() as conn:rows=list(conn.execute('SELECT * FROM sources'))
    return render(request,'sources.html',rows=rows,minimums=sources.MIN_INTERVAL,urls={'dealabs':'https://www.dealabs.com/groupe/jeux-playstation-5','leboncoin':'https://www.leboncoin.fr/c/jeux_video/console_brand%3Asony%2Bconsole_model%3Aps5','vinted':'https://www.vinted.fr/catalog/3026','easycash':sources.URLS['easycash']})

@app.post('/sources/{source}/toggle')
async def source_toggle(request:Request,source:str):
    await form(request)
    if source not in sources.URLS:return redirect('/sources','This source only supports native alerts/manual entry.')
    with db.connect() as conn:conn.execute('UPDATE sources SET enabled=1-enabled WHERE id=?',(source,))
    return redirect('/sources','Source setting updated.')

@app.get('/activity')
def activity(request:Request):
    with db.connect() as conn:
        runs=list(conn.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 50'))
        events=list(conn.execute('SELECT e.*,json_extract(w.data,\'$.name\') name FROM events e JOIN watches w ON w.id=e.watch_id ORDER BY e.id DESC LIMIT 50'))
    return render(request,'activity.html',runs=runs,events=events)

@app.get('/settings')
def settings_page(request:Request):
    with db.connect() as conn:
        cfg=db.settings(conn);token,chat=service.telegram_credentials(conn)
    safe={k:v for k,v in cfg.items() if k in ('timezone','default_interval','quiet_start','quiet_end','retention_days')}
    return render(request,'settings.html',config=safe,telegram_ready=bool(token and chat),env_telegram=bool(os.environ.get('TELEGRAM_BOT_TOKEN')))

@app.post('/settings')
async def settings_save(request:Request):
    data=await form(request)
    try:
        zone=str(data['timezone']);ZoneInfo(zone)
        interval=int(data['default_interval']);retention=int(data['retention_days'])
        if not 5<=interval<=10080 or not 7<=retention<=3650:raise ValueError()
        start=str(data.get('quiet_start',''));end=str(data.get('quiet_end',''))
        if bool(start)!=bool(end):raise ValueError()
        for value in (start,end):
            if value:datetime.strptime(value,'%H:%M')
        token=str(data.get('telegram_token','')).strip();chat=str(data.get('telegram_chat','')).strip()
        if token and (':' not in token or any(c.isspace() for c in token)):raise ValueError()
    except Exception:return redirect('/settings','Check timezone, intervals, quiet hours and Telegram details.')
    with db.connect() as conn:
        for key,value in [('timezone',zone),('default_interval',interval),('retention_days',retention),('quiet_start',start),('quiet_end',end)]:db.setting(conn,key,value)
        if token:db.setting(conn,'telegram_token',token)
        if chat:db.setting(conn,'telegram_chat',chat)
        if 'clear_telegram' in data:
            conn.execute("DELETE FROM settings WHERE key IN ('telegram_token','telegram_chat')")
    return redirect('/settings','Settings saved. Secrets are never shown in the dashboard.')

@app.post('/settings/test')
async def telegram_test(request:Request):
    await form(request)
    with db.connect() as conn:
        config=db.settings(conn)
        if time.time()-float(config.get('telegram_test_at',0))<60:return redirect('/settings','Wait one minute between test messages.')
        db.setting(conn,'telegram_test_at',time.time());token,chat=service.telegram_credentials(conn)
    success,detail,_=service.send_telegram(token,chat,'PS5 Deal Watcher · TEST notification\nYour Telegram destination is connected. This is not a deal alert.')
    return redirect('/settings',detail)

@app.get('/import')
def import_page(request:Request):return render(request,'import.html')

@app.post('/import')
async def import_listing(request:Request):
    data=await form(request)
    try:
        optional=lambda key:cents(str(data[key])) if str(data.get(key,'')).strip() else None
        place=str(data.get('location','')).strip()
        lat=float(data['lat']) if str(data.get('lat','')).strip() else None
        lon=float(data['lon']) if str(data.get('lon','')).strip() else None
        source=str(data['source']);url=str(data['url']).strip()
        listing=Listing(source=source,external_id=str(data.get('external_id','')).strip() or hashlib.sha256(url.encode()).hexdigest(),url=url,title=data['title'],description=str(data.get('description','')),item_cents=cents(str(data['item_price'])),shipping_cents=optional('shipping'),fees_cents=optional('fees'),pickup_fees_cents=optional('pickup_fees'),delivery='delivery' in data,pickup='pickup' in data,location=place,lat=lat,lon=lon,condition=data['condition'],platform=data['platform'],physical={'yes':True,'no':False,'unknown':None}[data['physical']],bundle='bundle' in data,price_kind=data['price_kind'],availability='unverified')
    except Exception:return redirect('/import','Check the listing URL, prices, coordinates and required fields.')
    now=time.time()
    with db.connect() as conn:
        listing_id=db.put_listing(conn,listing,now)
        for row in conn.execute('SELECT * FROM watches').fetchall():service.evaluate(conn,row['id'],Watch.model_validate_json(row['data']),listing_id,listing,now)
    return redirect('/deals','Listing saved and matched. Manual entries are not automatic source monitoring.')

@app.get('/monitoring')
def monitoring_page(request:Request):
    auth(request)
    from .monitoring import dashboard
    return render(request,'monitoring.html',**dashboard())
