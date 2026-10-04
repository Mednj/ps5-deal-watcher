"""Internal bounded search service using ordinary headed Chromium."""
import uuid
import random
import copy
import tempfile
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import subprocess
import threading
import time
from .leboncoin_pagination import search_url, PageTracker
from .leboncoin_limits import MAX_PAGES, browser_budget

from fastapi import FastAPI
from pydantic import BaseModel, Field
from playwright.sync_api import sync_playwright

from .browser_diagnostics import classify_page, emit, inspect_challenge, choose_handler
from .interactive_challenge import attempt_slide
from .image_puzzle import attempt_image_slider
from .normal_browser import normal_context, chromium_probe

app = FastAPI()
lock = threading.Lock()
status_lock = threading.Lock()
current_status = {'running':False,'stage':'idle'}
chromium_ready = False

def set_status(**fields):
    with status_lock:
        if fields.get('running') and fields.get('stage') == 'starting':
            current_status.clear()
        current_status.update(copy.deepcopy(fields))

@app.get('/status')
def status():
    with status_lock:return copy.deepcopy(current_status)


class Query(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    budget: int = Field(ge=1, le=10000000)


class Searches(BaseModel):
    queries: list[Query] = Field(min_length=1, max_length=4)
    pages: int = Field(default=MAX_PAGES, ge=1, le=MAX_PAGES)


@app.get('/health')
def health():
    display_ready=Path('/tmp/.X11-unix/X99').exists()
    return {'ready':display_ready and chromium_ready,
            'display_ready':display_ready,'chromium_ready':chromium_ready}



@contextmanager
def browser_profile(playwright, mode):
    if mode not in ('fresh', 'persistent'):
        raise ValueError('Invalid Leboncoin profile mode')
    with ExitStack() as resources:
        if mode == 'fresh':
            profile = resources.enter_context(tempfile.TemporaryDirectory(prefix='lbc-query-'))
        else:
            profile = os.environ.get('LEBONCOIN_PROFILE_DIR', '/browser-data/profile')
            Path(profile).mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.environ.get('LEBONCOIN_BROWSER_MODE','normal') == 'normal':
            with normal_context(playwright,profile) as context:
                yield context
        else:
            context = playwright.chromium.launch_persistent_context(str(profile), headless=False,
                executable_path='/usr/bin/chromium', chromium_sandbox=True, timeout=20000,
                locale='fr-FR', timezone_id='Europe/Paris', viewport={'width':1280,'height':900})
            try:
                yield context
            finally:
                context.close()

@app.post('/search')
def search(request: Searches):
    run_id=uuid.uuid4().hex[:12]
    started=time.monotonic()
    phase='lock'
    emit(run_id,'check_started',started,queries=len(request.queries),pages_per_sort=request.pages)
    if not lock.acquire(blocking=False):
        emit(run_id,'busy',started)
        return {'status': 'error', 'message': 'Browser is busy; retry later.', 'items': [], 'retry_after': 300}
    try:
        items = {}
        deadline = time.monotonic() + browser_budget(len(request.queries),request.pages)
        coverage = []
        summaries=[]
        set_status(running=True,run_id=run_id,started_at=time.time(),stage='starting',query=None,
                   query_index=None,sort=None,page=None,pages_limit=request.pages,cards_so_far=0,
                   searches=summaries,error=None)
        def fail(status_code,message,retry_after=300):
            if summaries and summaries[-1]['status']=='running':
                summaries[-1]['status']=status_code
                summaries[-1]['message']=message
                if summaries[-1]['sorts']:
                    current=next((s for s in summaries[-1]['sorts'].values() if s['status']=='running'),None)
                    if current:current['status']=status_code
            emit(run_id,'search_failed',started,status=status_code,message=message,searches=summaries)
            set_status(running=False,stage='failed',ended_at=time.time(),error=message,
                       status=status_code,searches=summaries)
            result={'status':status_code,'message':message,'items':[],'searches':summaries,
                    'coverage':coverage,'pages_fetched':len(coverage)}
            if retry_after is not None:result['retry_after']=retry_after
            return result
        phase='launch'
        with sync_playwright() as p, ExitStack() as sessions:
            mode=os.environ.get('LEBONCOIN_PROFILE_MODE','persistent')
            context=None
            try:
                for query_index,query in enumerate(request.queries):
                    summary={'query':query.name,'budget_cents':query.budget,'status':'running',
                             'pages':0,'cards':0,'sorts':{}}
                    summaries.append(summary)
                    set_status(query=query.name,query_index=query_index,sort=None,page=None,
                               stage='starting_query',cards_so_far=len(items),searches=summaries)
                    for sort, order in [('price', 'asc'), ('time', 'desc')]:
                        sort_summary={'pages':0,'cards':0,'status':'running','stop_reason':None}
                        summary['sorts'][sort]=sort_summary
                        if time.monotonic() >= deadline:
                            emit(run_id,'deadline_exceeded',started)
                            return fail('error',f"{query.name}: total search budget expired before {sort} results.")
                        if context is not None and os.environ.get('LEBONCOIN_BROWSER_MODE','normal')!='normal':
                            delay=random.SystemRandom().randint(6000,10000)
                            emit(run_id,'pacing_pause',started,stage='between_searches',duration_ms=delay)
                            page.wait_for_timeout(delay)
                        if context is None or mode == 'fresh':
                            sessions.close()
                            phase='launch'
                            context=sessions.enter_context(browser_profile(p,mode))
                            emit(run_id,'profile_loaded',started,persistent=mode=='persistent',query_index=query_index,sort=sort,cookie_count=len(context.cookies()))
                            emit(run_id,'browser_ready',started,launch_mode=os.environ.get('LEBONCOIN_BROWSER_MODE','normal'),version=context.browser.version,display_ready=Path('/tmp/.X11-unix/X99').exists())
                            page=context.pages[0] if context.pages else context.new_page()
                        tracker=PageTracker()
                        for page_number in range(1,request.pages+1):
                            if time.monotonic() >= deadline:
                                emit(run_id,'deadline_exceeded',started,pages_fetched=len(coverage))
                                return fail('error',f"{query.name}: time budget expired at {sort} page {page_number} after {len(coverage)} pages; diagnostics {run_id}.")
                            set_status(query=query.name,query_index=query_index,sort=sort,page=page_number,
                                       stage='loading_page',cards_so_far=len(items),searches=summaries)
                            phase='navigation'
                            delay=random.SystemRandom().randint(1200,2500)
                            emit(run_id,'pacing_pause',started,stage='before_navigation',duration_ms=delay)
                            page.wait_for_timeout(delay)
                            response = page.goto(search_url(query.name,query.budget,sort,order,page_number),
                                                 wait_until='domcontentloaded', timeout=15000)
                            status = response.status if response else 0
                            emit(run_id,'navigation_response',started,query_index=query_index,sort=sort,page_number=page_number,http_status=status,datadome_header_present=bool(response and any('datadome' in h for h in response.headers)))
                            # An HTTP access denial is already conclusive. Do not inspect
                            # or interact with a challenge after the source has refused
                            # the request; stop this run and let the normal backoff apply.
                            if status in (401, 403, 429):
                                kind='rate-limited' if status == 429 else 'blocked'
                                return fail(kind,f"{query.name}: Leboncoin returned HTTP {status} on {sort} page {page_number}; request stopped without challenge interaction; diagnostics {run_id}.",86400 if status!=429 else 3600)
                            delay=random.SystemRandom().randint(8500,11500)
                            emit(run_id,'pacing_pause',started,stage='page_settle',duration_ms=delay)
                            page.wait_for_timeout(delay)
                            phase='page_inspection'
                            flags=classify_page(page.locator('body').inner_text(timeout=3000)[:20000],page.title(),[f.url for f in page.frames])
                            emit(run_id,'page_inspected',started,**flags)
                            challenge=inspect_challenge(page)
                            enabled=os.environ.get('LEBONCOIN_INTERACTIVE_SOLVER')=='true'
                            handler=choose_handler(challenge['challenge_kind'],enabled)
                            emit(run_id,'challenge_classified',started,handler=handler,**challenge)
                            if handler=='wait' and status!=429:
                                phase='automatic_check'
                                until=min(deadline,time.monotonic()+12)
                                while time.monotonic()<until and challenge['challenge_blocking']:
                                    page.wait_for_timeout(750)
                                    challenge=inspect_challenge(page)
                                handler=choose_handler(challenge['challenge_kind'],enabled)
                                emit(run_id,'automatic_check_finished',started,handler=handler,**challenge)
                                if not challenge['challenge_blocking'] and page.locator('a[href*="/ad/jeux_video/"]:visible').count():status=200
                            if handler in ('slider','image_slider') and status!=429:
                                phase='interactive_challenge'
                                solver=attempt_slide if handler=='slider' else attempt_image_slider
                                outcome=solver(page,emit,run_id,started)
                                challenge=inspect_challenge(page)
                                emit(run_id,'interactive_outcome',started,outcome=outcome,**challenge)
                                if outcome=='access_confirmed':status=200
                            if status != 200:
                                return fail('error',f"{query.name}: Leboncoin returned HTTP {status} on {sort} page {page_number}; diagnostics {run_id}.")
                            if challenge['challenge_blocking']:
                                return fail('blocked',f"{query.name}: challenge {challenge['challenge_kind']} on {sort} page {page_number}; handler {handler}; diagnostics {run_id}.",86400)
                            phase='extraction'
                            selector = 'a[href*="/ad/jeux_video/"]'
                            try:
                                page.locator(selector).first.wait_for(timeout=8000)
                            except Exception:
                                text = page.locator('body').inner_text().lower()
                                flags=classify_page(text,page.title(),[f.url for f in page.frames])
                                emit(run_id,'cards_missing',started,query=query.name,query_index=query_index,sort=sort,page=page_number,http_status=status,**flags)
                                if not flags['empty_search_detected']:
                                    return fail('error',f"{query.name}: no cards and no confirmed empty-results page on {sort} page {page_number}; diagnostics {run_id}; needs review.")
                            rows = page.locator(selector).evaluate_all("""links => links.slice(0,200).map(a => {
                                const article = a.closest('article');
                                const readText = node => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
                                let text = readText(article);
                                if (!text) {
                                    let fallback = '';
                                    for (let node = a, depth = 0; node && node !== document.body && depth < 10;
                                         node = node.parentElement, depth += 1) {
                                        const candidate = readText(node);
                                        if (!candidate || candidate.length > 5000) continue;
                                        const ids = new Set(Array.from(node.querySelectorAll('a[href*="/ad/jeux_video/"]'))
                                            .map(link => new URL(link.href).pathname));
                                        if (ids.size !== 1) continue;
                                        if (!fallback) fallback = candidate;
                                        if (/prix\\s*:/i.test(candidate)) { text = candidate; break; }
                                    }
                                    if (!text) text = fallback;
                                }
                                return {url:a.href, title:(article?.getAttribute('aria-label') || '').trim(), text:text.slice(0,5000)};
                            })""")
                            emit(run_id,'cards_extracted',started,query_index=query_index,sort=sort,page_number=page_number,
                                 count=len(rows),empty_text_count=sum(not row.get('text','').strip() for row in rows))
                            reason=tracker.collect(rows,items)
                            coverage.append({'query_index':query_index,'sort':sort,'page':page_number,'cards':len(rows),'stop':reason})
                            sort_summary['pages']+=1;sort_summary['cards']+=len(rows)
                            summary['pages']+=1;summary['cards']+=len(rows)
                            sort_summary['stop_reason']=reason
                            set_status(query=query.name,query_index=query_index,sort=sort,page=page_number,
                                       stage='page_complete',cards_so_far=len(items),searches=summaries)
                            emit(run_id,'pagination_page',started,**coverage[-1],unique_cards=len(items))
                            if reason:
                                sort_summary['status']='complete';break
                        else:sort_summary['status']='complete'
                    summary['status']='complete'
                    set_status(query=query.name,query_index=query_index,sort=None,page=None,
                               stage='query_complete',cards_so_far=len(items),searches=summaries)
                emit(run_id,'check_completed',started,unique_cards=len(items),pages_fetched=len(coverage))
                set_status(running=False,stage='complete',ended_at=time.time(),status='experimental',
                           query=None,sort=None,page=None,cards_so_far=len(items),searches=summaries,error=None)
                return {'status': 'experimental', 'message': f'Cheapest + newest: {len(coverage)} pages fetched, up to {request.pages} per search order.',
                        'items': list(items.values()), 'coverage':coverage, 'pages_fetched':len(coverage),
                        'page_limit':request.pages,'searches':summaries}
            finally:
                sessions.close()
                emit(run_id,'profiles_closed',started,mode=mode,temporary_profiles_removed=mode=='fresh')
    except Exception as exc:
        emit(run_id,'check_failed',started,phase=phase,error_type=type(exc).__name__)
        message=f'Browser {phase} failed; diagnostics {run_id}.'
        summaries=locals().get('summaries',[])
        if summaries and summaries[-1]['status']=='running':
            summaries[-1]['status']='error';summaries[-1]['message']=message
        set_status(running=False,stage='failed',ended_at=time.time(),status='error',
                   error=message,searches=summaries)
        return {'status': 'error', 'message': message,'items': [],'searches':summaries}
    finally:
        lock.release()


def main():
    global chromium_ready
    import uvicorn
    display = subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1280x900x24', '-nolisten', 'tcp', '-ac'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ['DISPLAY'] = ':99'
    viewers=[]
    try:
        for _ in range(50):
            if Path('/tmp/.X11-unix/X99').exists():
                break
            if display.poll() is not None:
                raise RuntimeError('Virtual display exited')
            time.sleep(.1)
        if not Path('/tmp/.X11-unix/X99').exists():
            raise RuntimeError('Virtual display startup timeout')
        if not chromium_probe():
            raise RuntimeError('Chromium startup probe failed')
        chromium_ready=True
        viewers.append(subprocess.Popen(['x11vnc','-display',':99','-rfbport','5900','-localhost','-forever','-shared','-viewonly','-nopw','-quiet'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        viewers.append(subprocess.Popen(['websockify','--web=/usr/share/novnc','6080','127.0.0.1:5900'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        uvicorn.run(app, host='0.0.0.0', port=8770, access_log=False)
    finally:
        for viewer in reversed(viewers):
            viewer.terminate()
            try:
                viewer.wait(timeout=3)
            except subprocess.TimeoutExpired:
                viewer.kill()
        display.terminate()
        try:
            display.wait(timeout=3)
        except subprocess.TimeoutExpired:
            display.kill()


if __name__ == '__main__':
    main()
