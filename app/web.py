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
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
templates=Jinja2Templates(directory=ROOT/'templates')
templates.env.filters['money']=service.money
def date(value):
    if value is None:return 'Not yet'
    return datetime.fromtimestamp(float(value),ZoneInfo('Europe/Paris')).strftime('%d %b · %H:%M')
templates.env.filters['date']=date

def current_user(request):
    user_id=request.session.get('user_id')
    if not user_id and os.environ.get('APP_AUTH_DISABLED_FOR_TESTS'):
        with db.connect() as conn:
            row=conn.execute("SELECT id,username,role,must_change_password,active FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
            return dict(row) if row else None
    if not user_id:return None
    with db.connect() as conn:
        row=conn.execute('SELECT id,username,role,must_change_password,active,session_version FROM users WHERE id=?',(user_id,)).fetchone()
        if not row or not row['active'] or request.session.get('session_version')!=row['session_version']:return None
        return dict(row)

@app.middleware('http')
async def require_account(request,call_next):
    path=request.url.path
    public=path.startswith('/static/') or path.startswith('/health/') or path=='/login'
    if not public and not os.environ.get('APP_AUTH_DISABLED_FOR_TESTS'):
        user=current_user(request)
        if not user:
            response=redirect('/login')
            return response
        if user['must_change_password'] and path not in ('/account/password','/logout'):
            return redirect('/account/password','Change the temporary admin password to continue.')
    return await call_next(request)

async def form(request):
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

# Session middleware must wrap the account gate so it populates request.session first.
app.add_middleware(SessionMiddleware,secret_key=SECRET,same_site='strict',https_only=os.environ.get('COOKIE_SECURE','false').lower()=='true',max_age=43200)

def render(request,template,**context):
    if 'csrf' not in request.session:request.session['csrf']=secrets.token_hex(24)
    with db.connect() as conn:
        cfg=db.settings(conn)
        heartbeat=float(cfg.get('worker_heartbeat',0))
    user=current_user(request)
    base={'request':request,'csrf':request.session['csrf'],'page':request.url.path,'message':request.query_params.get('message',''),'worker_ok':time.time()-heartbeat<90,'sources_names':SOURCES,'centres':CENTRES,'user':user,'now':time.time()}
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
    if current_user(request):return redirect('/account/password' if current_user(request)['must_change_password'] else '/')
    request.session.setdefault('csrf',secrets.token_hex(24))
    return templates.TemplateResponse(request=request,name='login.html',context={'request':request,'csrf':request.session['csrf'],'message':request.query_params.get('message','')})

@app.post('/login')
async def login(request:Request):
    data=await request.form()
    if not hmac.compare_digest(str(data.get('csrf','')),request.session.get('csrf','missing')):raise HTTPException(403)
    username=str(data.get('username','')).strip()
    with db.connect() as conn:
        cfg=db.settings(conn)
        if float(cfg.get('login_retry_at',0))>time.time():return redirect('/login','Please wait before trying again.')
        user=conn.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE',(username,)).fetchone()
        if not user or not user['active'] or not db.check_password(str(data.get('password','')),user['password_hash']):
            failures=int(cfg.get('login_failures',0))+1
            db.setting(conn,'login_failures',failures)
            db.setting(conn,'login_retry_at',time.time()+min(300,2**min(failures,8)))
            return redirect('/login','Password incorrect.')
        db.setting(conn,'login_failures',0);db.setting(conn,'login_retry_at',0)
    request.session.clear();request.session['user_id']=user['id'];request.session['session_version']=user['session_version'];request.session['csrf']=secrets.token_hex(24)
    return redirect('/account/password' if user['must_change_password'] else '/')

@app.post('/logout')
async def logout(request:Request):
    await form(request);request.session.clear();return redirect('/login')

@app.get('/account/password')
def password_page(request:Request):
    user=current_user(request)
    return render(request,'password.html',must_change=bool(user['must_change_password']))

@app.post('/account/password')
async def password_change(request:Request):
    data=await form(request);user=current_user(request)
    password=str(data.get('password',''));confirm=str(data.get('confirm',''))
    if len(password)<12 or password!=confirm:return redirect('/account/password','Use a matching password with at least 12 characters.')
    with db.connect() as conn:
        conn.execute('UPDATE users SET password_hash=?,must_change_password=0,session_version=session_version+1 WHERE id=?',(db.hash_password(password),user['id']))
        version=conn.execute('SELECT session_version FROM users WHERE id=?',(user['id'],)).fetchone()[0]
    request.session.clear();request.session['user_id']=user['id'];request.session['session_version']=version;request.session['csrf']=secrets.token_hex(24)
    return redirect('/','Password updated.')

@app.get('/admin/users')
def users_page(request:Request):
    user=current_user(request)
    if user['role']!='admin':raise HTTPException(403,'Admin account required.')
    with db.connect() as conn:users=list(conn.execute('SELECT id,username,role,active,must_change_password,created_at FROM users ORDER BY id'))
    return render(request,'users.html',users=users)

@app.post('/admin/users/create')
async def user_create(request:Request):
    user=current_user(request)
    if user['role']!='admin':raise HTTPException(403,'Admin account required.')
    data=await form(request);username=str(data.get('username','')).strip();password=str(data.get('password',''))
    if len(username)<3 or len(username)>64 or not username.replace('_','').replace('-','').isalnum() or len(password)<12:
        return redirect('/admin/users','Use a 3–64 character username and temporary password of at least 12 characters.')
    try:
        with db.connect() as conn:conn.execute('INSERT INTO users(username,password_hash,role,active,must_change_password,created_at) VALUES(?,?,\'user\',1,1,?)',(username,db.hash_password(password),time.time()))
    except Exception:return redirect('/admin/users','That username already exists or could not be created.')
    return redirect('/admin/users','Account created. Share the temporary password securely.')

@app.post('/admin/users/{target_id}/toggle')
async def user_toggle(request:Request,target_id:int):
    user=current_user(request)
    if user['role']!='admin':raise HTTPException(403,'Admin account required.')
    await form(request)
    with db.connect() as conn:
        target=conn.execute('SELECT role,active FROM users WHERE id=?',(target_id,)).fetchone()
        if not target:raise HTTPException(404)
        if target_id==user['id'] or target['role']=='admin':return redirect('/admin/users','Admin access cannot be disabled here.')
        conn.execute('UPDATE users SET active=?,session_version=session_version+1 WHERE id=?',(0 if target['active'] else 1,target_id))
    return redirect('/admin/users','Account status updated.')

@app.post('/admin/users/{target_id}/reset-password')
async def user_reset_password(request:Request,target_id:int):
    user=current_user(request)
    if user['role']!='admin':raise HTTPException(403,'Admin account required.')
    data=await form(request);password=str(data.get('password',''))
    if len(password)<12:return redirect('/admin/users','Temporary password must have at least 12 characters.')
    with db.connect() as conn:
        target=conn.execute('SELECT role FROM users WHERE id=?',(target_id,)).fetchone()
        if not target:raise HTTPException(404)
        if target['role']=='admin':return redirect('/admin/users','Use the account page to change an admin password.')
        conn.execute('UPDATE users SET password_hash=?,must_change_password=1,session_version=session_version+1 WHERE id=?',(db.hash_password(password),target_id))
    return redirect('/admin/users','Password reset. The user must change it at next login.')

@app.get('/')
def home(request:Request):
    user=current_user(request)
    with db.connect() as conn:
        watches=[]
        for row in conn.execute('SELECT * FROM watches WHERE owner_id=? ORDER BY id DESC',(user['id'],)):
            watches.append({**dict(row),**json.loads(row['data'])})
        source_rows=[]
        for row in conn.execute('SELECT * FROM sources'):
            latest=conn.execute('SELECT status,count FROM runs WHERE source=? AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
            status=row['status']
            label=('Challenged' if status in ('challenge','blocked') else 'Format changed' if status=='format-change' else ('Healthy · no results' if latest['count']==0 else 'Healthy · results') if latest and status in ('verified working','experimental') else 'Experimental · not checked' if status=='experimental' else 'Not checked' if not latest else status.replace('-',' ').title())
            source_rows.append({**dict(row),'health_label':label,'health_kind':'bad' if status in ('challenge','blocked','format-change') else 'good' if status in ('verified working','experimental') else 'warning'})
        counts={r['state']:r['n'] for r in conn.execute('SELECT state,count(*) n FROM matches m JOIN watches w ON w.id=m.watch_id WHERE w.owner_id=? AND m.hidden=0 GROUP BY state',(user['id'],))}
        pending=conn.execute("SELECT count(*) FROM events e JOIN watches w ON w.id=e.watch_id WHERE w.owner_id=? AND e.state IN ('pending','sending')",(user['id'],)).fetchone()[0]
        token,chat=service.telegram_credentials(conn,user['id'])
    return render(request,'home.html',watches=watches,source_rows=source_rows,counts=counts,pending=pending,telegram_ready=bool(token and chat))

def local_input(stamp,zone):
    return datetime.fromtimestamp(stamp,ZoneInfo(zone)).strftime('%Y-%m-%dT%H:%M') if stamp is not None else ''

@app.get('/watches/new')
def new_watch(request:Request):
    user=current_user(request)
    with db.connect() as conn:
        cfg=db.user_settings(conn,user['id']);token,chat=service.telegram_credentials(conn,user['id'])
    watch=Watch(name='New watch',max_cents=1500,interval_minutes=int(cfg['default_interval']),timezone=cfg['timezone']).model_dump()
    watch['name']=''
    return render(request,'watch.html',watch=watch,watch_id=None,start_value='',end_value='',telegram_ready=bool(token and chat))

@app.get('/watches/{watch_id}/edit')
def edit_watch(request:Request,watch_id:int):
    user=current_user(request)
    with db.connect() as conn:
        row=conn.execute('SELECT data FROM watches WHERE id=? AND owner_id=?',(watch_id,user['id'])).fetchone()
        token,chat=service.telegram_credentials(conn,user['id'])
    if not row:raise HTTPException(404)
    watch=json.loads(row['data'])
    return render(request,'watch.html',watch=watch,watch_id=watch_id,start_value=local_input(watch['start_at'],watch['timezone']),end_value=local_input(watch['end_at'],watch['timezone']),telegram_ready=bool(token and chat))

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
    data=await form(request);user=current_user(request)
    watch_id=int(data['watch_id']) if data.get('watch_id') else None
    try:watch=watch_from_form(data)
    except (ValueError,KeyError,ValidationError) as exc:return redirect(f'/watches/{watch_id}/edit' if watch_id else '/watches/new','Please check the form: '+str(exc)[:250])
    now=time.time()
    with db.connect() as conn:
        if watch_id:
            if not conn.execute('SELECT 1 FROM watches WHERE id=? AND owner_id=?',(watch_id,user['id'])).fetchone():raise HTTPException(404)
            conn.execute('UPDATE watches SET data=?,next_at=? WHERE id=? AND owner_id=?',(watch.model_dump_json(),now,watch_id,user['id']))
        else:
            conn.execute('INSERT INTO watches(owner_id,data,next_at,created_at) VALUES(?,?,?,?)',(user['id'],watch.model_dump_json(),now,now))
            watch_id=conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        service.reevaluate_watch(conn,watch_id,now)
    return redirect('/','Watch saved. Checks respect each source’s minimum interval.')

@app.post('/watches/{watch_id}/{action}')
async def watch_action(request:Request,watch_id:int,action:str):
    await form(request);user=current_user(request)
    with db.connect() as conn:
        row=conn.execute('SELECT data FROM watches WHERE id=? AND owner_id=?',(watch_id,user['id'])).fetchone()
        if not row:raise HTTPException(404)
        watch=Watch.model_validate_json(row['data'])
        if action=='delete':conn.execute('DELETE FROM watches WHERE id=?',(watch_id,))
        elif action=='duplicate':
            watch.active=False
            conn.execute('INSERT INTO watches(owner_id,data,next_at,created_at) VALUES(?,?,?,?)',(user['id'],watch.model_dump_json(),time.time(),time.time()))
        elif action in ('pause','resume'):
            watch.active=action=='resume'
            conn.execute('UPDATE watches SET data=?,next_at=? WHERE id=? AND owner_id=?',(watch.model_dump_json(),time.time(),watch_id,user['id']))
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
    user=current_user(request)
    state=request.query_params.get('state','all');source=request.query_params.get('source','all')
    game=request.query_params.get('game','all');review=request.query_params.get('review','all')
    sort=request.query_params.get('sort','newest')
    history=request.query_params.get('history','6m')
    if history not in ('6m','1y','2y','all'):history='6m'
    history_seconds={'6m':180*86400,'1y':365*86400,'2y':730*86400,'all':None}[history]
    now=time.time()
    with db.connect() as conn:user_retention=int(db.user_settings(conn,user['id']).get('retention_days','730'))
    retention_after=now-user_retention*86400
    history_after=max(retention_after,now-history_seconds) if history_seconds is not None else retention_after
    with db.connect() as conn:
        watches=[{'id':r['id'],'data':r['data'],'name':json.loads(r['data'])['name']} for r in conn.execute('SELECT id,data FROM watches WHERE owner_id=? ORDER BY id',(user['id'],))]
        allowed_states=('qualified','candidate') if state=='all' else (state,) if state in ('qualified','candidate','excluded','over-budget') else ('qualified','candidate')
        placeholders=','.join('?' for _ in allowed_states)
        rows=conn.execute(f'SELECT m.*,l.data,l.last_at,l.first_at,w.data watch,w.id watch_id FROM matches m JOIN listings l ON l.id=m.listing_id JOIN watches w ON w.id=m.watch_id WHERE w.owner_id=? AND (l.owner_id IS NULL OR l.owner_id=?) AND m.hidden=0 AND m.state IN ({placeholders})',(user['id'],user['id'],*allowed_states)).fetchall()
    items=[]
    history_by_listing={}
    all_history_by_listing={}
    listing_ids=sorted({row['listing_id'] for row in rows})
    if listing_ids:
        with db.connect() as conn:
            marks=','.join('?' for _ in listing_ids)
            history_rows=conn.execute(f'SELECT listing_id,at,item_cents FROM observations WHERE listing_id IN ({marks}) ORDER BY listing_id,at',listing_ids).fetchall()
        for observation in history_rows:
            all_history_by_listing.setdefault(observation['listing_id'],[]).append(observation)
            if history_after is not None and observation['at']<history_after:continue
            points=history_by_listing.setdefault(observation['listing_id'],[])
            if points and points[-1]['price_cents']==observation['item_cents']:
                points[-1]['at']=observation['at']
            else:
                points.append({'at':observation['at'],'price_cents':observation['item_cents']})
    for row in rows:
        if state!='all' and row['state']!=state:continue
        listing=json.loads(row['data'])
        if source!='all' and listing['source']!=source:continue
        watch_data=json.loads(row['watch'])
        if game!='all' and str(row['watch_id'])!=game:continue
        uncertain=[]
        if listing.get('platform')=='unknown':uncertain.append('platform')
        elif listing.get('platform') in ('ps5','ps4-upgrade') and listing.get('provenance')!='manual entry':uncertain.append('platform reported by listing')
        if listing.get('physical') is not True:uncertain.append('physical disc')
        if listing.get('delivery') is None:uncertain.append('delivery availability')
        if listing.get('delivery') is True and listing.get('shipping_cents') is None:uncertain.append('delivery cost')
        if listing.get('fees_cents') is None:uncertain.append('buyer fees')
        if listing.get('provenance')!='manual entry':uncertain.append('delivery, pickup and prices are source-reported')
        if listing.get('availability')!='confirmed':uncertain.append('availability is source-reported, not independently confirmed')
        image=urlsplit(listing.get('image',''))
        safe_image=listing.get('image','') if image.scheme=='https' and image.hostname=='static-pepper.dealabs.com' and not image.username and not image.password else ''
        points=history_by_listing.get(row['listing_id'],[])
        all_points=all_history_by_listing.get(row['listing_id'],[])
        low=min((p['price_cents'] for p in points),default=None)
        if len(points)>100:
            stride=max(1,len(points)//100)
            reduced=points[::stride]+[points[-1],min(points,key=lambda p:p['price_cents']),max(points,key=lambda p:p['price_cents'])]
            points=sorted({p['at']:p for p in reduced}.values(),key=lambda p:p['at'])
        prices=[p['price_cents'] for p in points]
        chart=[]
        if points:
            x0=50;x1=610;y0=18;y1=150
            lo=min(prices);hi=max(prices);span=max(1,hi-lo)
            start=history_after if history_after is not None else points[0]['at']
            end=max(start+1,now)
            for point in points:
                x=x0+(point['at']-start)/(end-start)*(x1-x0)
                y=y1-(point['price_cents']-lo)/span*(y1-y0) if hi>lo else (y0+y1)/2
                chart.append({'x':round(x,1),'y':round(y,1),'at':point['at'],'price':point['price_cents']})
        needs_review=bool(uncertain) or row['state']=='candidate'
        if review=='yes' and not needs_review:continue
        items.append({**dict(row),**listing,'watch_name':watch_data['name'],'watch_budget':watch_data['max_cents'],'watch_basis':watch_data['basis'],'watch_effective_basis':'item price only' if watch_data['qualification']=='name-price' else watch_data['basis'],'watch_qualification':watch_data['qualification'],'safe_image':safe_image,'uncertainties':list(dict.fromkeys(uncertain)),'needs_review':needs_review,'history_points':chart,'history_polyline':' '.join(f"{p['x']},{p['y']}" for p in chart),'history_low':low,'history_from':points[0]['at'] if points else None,'history_to':points[-1]['at'] if points else None})
    items.sort(key=lambda x:(x['total_cents'] is None,x['total_cents'] if x['total_cents'] is not None else x['item_cents']) if sort=='price' else -x['first_at'])
    return render(request,'deals.html',items=items,state=state,source=source,sort=sort,game=game,review=review,history=history,watches=watches)

@app.post('/deals/{watch_id}/{listing_id}/hide')
async def hide(request:Request,watch_id:int,listing_id:int):
    await form(request);user=current_user(request)
    with db.connect() as conn:conn.execute('UPDATE matches SET hidden=1 WHERE watch_id=? AND listing_id=? AND EXISTS (SELECT 1 FROM watches WHERE id=? AND owner_id=?)',(watch_id,listing_id,watch_id,user['id']))
    return redirect('/deals','Deal hidden.')

@app.get('/sources')
def source_page(request:Request):
    with db.connect() as conn:
        rows=[]
        for row in conn.execute('SELECT * FROM sources'):
            latest=conn.execute('SELECT status,count FROM runs WHERE source=? AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone()
            status=row['status']
            label=('Challenged' if status in ('challenge','blocked') else 'Format changed' if status=='format-change' else ('Healthy · no results' if latest['count']==0 else 'Healthy · results') if latest and status in ('verified working','experimental') else 'Experimental · not checked' if status=='experimental' else 'Not checked' if not latest else status.replace('-',' ').title())
            rows.append({**dict(row),'health_label':label,'health_kind':'bad' if status in ('challenge','blocked','format-change') else 'good' if status in ('verified working','experimental') else 'warning'})
    return render(request,'sources.html',rows=rows,minimums=sources.MIN_INTERVAL,urls={'dealabs':'https://www.dealabs.com/groupe/jeux-playstation-5','leboncoin':'https://www.leboncoin.fr/c/jeux_video/console_brand%3Asony%2Bconsole_model%3Aps5','vinted':'https://www.vinted.fr/catalog/3026','easycash':sources.URLS['easycash']})

@app.post('/sources/{source}/toggle')
async def source_toggle(request:Request,source:str):
    if current_user(request)['role']!='admin':raise HTTPException(403,'Admin account required.')
    await form(request)
    if source not in sources.URLS:return redirect('/sources','This source only supports native alerts/manual entry.')
    with db.connect() as conn:conn.execute('UPDATE sources SET enabled=1-enabled WHERE id=?',(source,))
    return redirect('/sources','Source setting updated.')

@app.get('/activity')
def activity(request:Request):
    user=current_user(request)
    day_ago=time.time()-86400
    with db.connect() as conn:
        runs=list(conn.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 50'))
        events=list(conn.execute('SELECT e.*,json_extract(w.data,\'$.name\') name FROM events e JOIN watches w ON w.id=e.watch_id WHERE w.owner_id=? ORDER BY e.id DESC LIMIT 50',(user['id'],)))
        raw_stats=list(conn.execute("""SELECT source,count(*) checks,
            sum(CASE WHEN status IN ('verified working','experimental') THEN 1 ELSE 0 END) successful,
            sum(CASE WHEN status IN ('verified working','experimental') AND count=0 THEN 1 ELSE 0 END) empty
            FROM runs WHERE ended_at IS NOT NULL AND started_at>=? GROUP BY source ORDER BY source""",(day_ago,)))
        delivery_stats={r['state']:r['n'] for r in conn.execute("""SELECT state,count(*) n FROM events e JOIN watches w ON w.id=e.watch_id
            WHERE w.owner_id=? AND e.created_at>=? GROUP BY state""",(user['id'],day_ago))}
    check_stats=[]
    for row in raw_stats:
        checks=int(row['checks']);successful=int(row['successful'] or 0)
        check_stats.append({**dict(row),'checks':checks,'successful':successful,'empty':int(row['empty'] or 0),
            'issues':checks-successful,'rate':round(successful*100/checks) if checks else 0})
    return render(request,'activity.html',runs=runs,events=events,check_stats=check_stats,delivery_stats=delivery_stats)

@app.get('/settings')
def settings_page(request:Request):
    user=current_user(request)
    with db.connect() as conn:
        cfg=db.user_settings(conn,user['id']);token,chat=service.telegram_credentials(conn,user['id'])
        configured=db.user_settings(conn,user['id'])
    safe={k:v for k,v in cfg.items() if k in ('timezone','default_interval','quiet_start','quiet_end','retention_days')}
    env_fallback=user['role']=='admin' and not configured.get('telegram_token') and not configured.get('telegram_chat') and bool(os.environ.get('TELEGRAM_BOT_TOKEN') and os.environ.get('TELEGRAM_CHAT_ID'))
    return render(request,'settings.html',config=safe,telegram_ready=bool(token and chat),env_telegram=env_fallback)

@app.post('/settings')
async def settings_save(request:Request):
    data=await form(request);user=current_user(request)
    try:
        zone=str(data['timezone']);ZoneInfo(zone)
        interval=int(data['default_interval']);retention=int(data['retention_days'])
        if not 5<=interval<=10080 or not 7<=retention<=730:raise ValueError()
        start=str(data.get('quiet_start',''));end=str(data.get('quiet_end',''))
        if bool(start)!=bool(end):raise ValueError()
        for value in (start,end):
            if value:datetime.strptime(value,'%H:%M')
        token=str(data.get('telegram_token','')).strip();chat=str(data.get('telegram_chat','')).strip()
        if token and (':' not in token or any(c.isspace() for c in token)):raise ValueError()
    except Exception:return redirect('/settings','Check timezone, intervals, quiet hours and Telegram details.')
    with db.connect() as conn:
        for key,value in [('timezone',zone),('default_interval',interval),('retention_days',retention),('quiet_start',start),('quiet_end',end)]:db.user_setting(conn,user['id'],key,value)
        if token:db.user_setting(conn,user['id'],'telegram_token',token)
        if chat:db.user_setting(conn,user['id'],'telegram_chat',chat)
        if 'clear_telegram' in data:
            conn.execute("DELETE FROM user_settings WHERE user_id=? AND key IN ('telegram_token','telegram_chat')",(user['id'],))
    return redirect('/settings','Settings saved. Secrets are never shown in the dashboard.')

@app.post('/settings/test')
async def telegram_test(request:Request):
    await form(request);user=current_user(request)
    with db.connect() as conn:
        config=db.user_settings(conn,user['id'])
        if time.time()-float(config.get('telegram_test_at',0))<60:return redirect('/settings','Wait one minute between test messages.')
        db.user_setting(conn,user['id'],'telegram_test_at',time.time());token,chat=service.telegram_credentials(conn,user['id'])
    success,detail,_=service.send_telegram(token,chat,'PS5 Deal Watcher · TEST notification\nYour Telegram destination is connected. This is not a deal alert.')
    return redirect('/settings',detail)

@app.get('/import')
def import_page(request:Request):return render(request,'import.html')

@app.post('/import')
async def import_listing(request:Request):
    data=await form(request);user=current_user(request)
    try:
        optional=lambda key:cents(str(data[key])) if str(data.get(key,'')).strip() else None
        place=str(data.get('location','')).strip()
        lat=float(data['lat']) if str(data.get('lat','')).strip() else None
        lon=float(data['lon']) if str(data.get('lon','')).strip() else None
        source=str(data['source']);url=str(data['url']).strip()
        private_id=str(data.get('external_id','')).strip() or hashlib.sha256(url.encode()).hexdigest()
        listing=Listing(source=source,external_id=f"manual-{user['id']}-{private_id}",url=url,title=data['title'],description=str(data.get('description','')),item_cents=cents(str(data['item_price'])),shipping_cents=optional('shipping'),fees_cents=optional('fees'),pickup_fees_cents=optional('pickup_fees'),delivery='delivery' in data,pickup='pickup' in data,location=place,lat=lat,lon=lon,condition=data['condition'],platform=data['platform'],physical={'yes':True,'no':False,'unknown':None}[data['physical']],bundle='bundle' in data,price_kind=data['price_kind'],availability='confirmed' if data.get('availability')=='confirmed' else 'unverified')
    except Exception:return redirect('/import','Check the listing URL, prices, coordinates and required fields.')
    now=time.time()
    with db.connect() as conn:
        listing_id=db.put_listing(conn,listing,now,user['id'])
        for row in conn.execute('SELECT * FROM watches WHERE owner_id=?',(user['id'],)).fetchall():service.evaluate(conn,row['id'],Watch.model_validate_json(row['data']),listing_id,listing,now)
    return redirect('/deals','Listing saved and matched. Manual entries are not automatic source monitoring.')

@app.get('/monitoring')
def monitoring_page(request:Request):
    if current_user(request)['role']!='admin':raise HTTPException(403,'Admin account required.')
    from .monitoring import dashboard
    return render(request,'monitoring.html',**dashboard())
