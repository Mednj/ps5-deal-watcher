from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit
import pytest
from scripts.leboncoin_pagination import PageTracker,search_url
from scripts.leboncoin_limits import client_budget,CHECK_BUDGET

def row(number, suffix=''):
    return {'url':f'https://www.leboncoin.fr/ad/jeux_video/{number}'+suffix,'text':'Elden Ring PS5\nPrix: 20 €.'}

def test_urls_and_canonical_dedup_early_stop():
    params=parse_qs(urlsplit(search_url('Elden Ring PS5',4999,'price','asc',5)).query)
    assert params=={'text':['Elden Ring PS5'],'price':['min-50'],'sort':['price'],'order':['asc'],'page':['5']}
    tracker=PageTracker();items={}
    assert tracker.collect([row(1,'?tracking=a'),row(2)],items) is None
    assert tracker.collect([row(2),row(3)],items) is None
    assert len(items)==3
    assert tracker.collect([row(3),row(2,'?tracking=b')],items)=='repeated'
    assert tracker.collect([],items)=='empty'

def setup_browser(monkeypatch, rows_for, blocked_page=None):
    pytest.importorskip('playwright')
    from scripts import leboncoin_browser as browser
    seen=[]
    class Page:
        frames=[]
        def wait_for_timeout(self,*a):pass
        def goto(self,url,**kw):
            self.params=parse_qs(urlsplit(url).query)
            seen.append((self.params['sort'][0],int(self.params['page'][0])))
            return SimpleNamespace(status=200,headers={})
        def title(self):return 'Search'
        def locator(self,*a):return self
        @property
        def first(self):return self
        def wait_for(self,**kw):pass
        def inner_text(self,**kw):return ''
        def evaluate_all(self,*a):return rows_for(*seen[-1])
    page=Page()
    @contextmanager
    def context(*a):
        yield SimpleNamespace(pages=[page],cookies=lambda:[],browser=SimpleNamespace(version='test'))
    monkeypatch.setattr(browser,'sync_playwright',lambda:context())
    monkeypatch.setattr(browser,'browser_profile',context)
    monkeypatch.setattr(browser,'emit',lambda *a,**kw:None)
    monkeypatch.setattr(browser,'inspect_challenge',lambda page:{'challenge_kind':'unknown' if seen[-1][1]==blocked_page else 'none','challenge_blocking':seen[-1][1]==blocked_page})
    monkeypatch.setenv('LEBONCOIN_PROFILE_MODE','persistent')
    monkeypatch.setenv('LEBONCOIN_BROWSER_MODE','normal')
    monkeypatch.setenv('LEBONCOIN_INTERACTIVE_SOLVER','false')
    return browser,seen

def test_actual_search_traverses_five_pages_both_sorts(monkeypatch):
    browser,seen=setup_browser(monkeypatch,lambda sort,page:[row(page),row(page+1)])
    result=browser.search(browser.Searches(queries=[{'name':'Elden Ring','budget':5000}]))
    assert seen==[(sort,page) for sort in ('price','time') for page in range(1,6)]
    assert result['status']=='experimental' and result['pages_fetched']==10
    assert len(result['items'])==6
    assert result['searches'][0]['query']=='Elden Ring'
    assert result['searches'][0]['status']=='complete'
    assert client_budget(4)>client_budget(1)>150 and CHECK_BUDGET>client_budget(4)

def test_four_searches_each_report_per_sort_page_counts(monkeypatch):
    browser,seen=setup_browser(monkeypatch,lambda sort,page:[row(page+100*len(seen))])
    queries=[{'name':name,'budget':5000} for name in ('Game Alpha','Game Bravo','Game Charlie','Game Delta')]
    result=browser.search(browser.Searches(queries=queries))
    assert result['status']=='experimental' and len(result['searches'])==4
    assert all(s['status']=='complete' and s['pages']==10 and set(s['sorts'])=={'price','time'} for s in result['searches'])
    assert len(seen)==40

def test_actual_search_stops_repeated_or_empty_pages(monkeypatch):
    browser,seen=setup_browser(monkeypatch,lambda sort,page:[] if sort=='time' else [row(1)])
    result=browser.search(browser.Searches(queries=[{'name':'Elden Ring','budget':5000}]))
    assert seen==[('price',1),('price',2),('time',1)]
    assert [p['stop'] for p in result['coverage']]==[None,'repeated','empty']

def test_challenge_on_later_page_is_not_reported_as_success(monkeypatch):
    browser,seen=setup_browser(monkeypatch,lambda sort,page:[row(page)],blocked_page=3)
    result=browser.search(browser.Searches(queries=[{'name':'Elden Ring','budget':5000}]))
    assert result['status']=='blocked' and result['items']==[]
    assert seen==[('price',1),('price',2),('price',3)]

def test_http_access_denial_stops_before_challenge_inspection_or_solver(monkeypatch):
    browser,seen=setup_browser(monkeypatch,lambda sort,page:[row(page)])
    from types import SimpleNamespace
    def denied_goto(self,url,**kwargs):
        self.params=parse_qs(urlsplit(url).query)
        seen.append((self.params['sort'][0],int(self.params['page'][0])))
        return SimpleNamespace(status=403,headers={})
    # Make either kind of challenge handling fail loudly if reached.
    monkeypatch.setattr(browser,'inspect_challenge',lambda page:pytest.fail('403 must short-circuit challenge inspection'))
    monkeypatch.setattr(browser,'attempt_slide',lambda *a:pytest.fail('403 must not invoke a challenge solver'))
    monkeypatch.setattr(browser,'attempt_image_slider',lambda *a:pytest.fail('403 must not invoke a challenge solver'))
    monkeypatch.setenv('LEBONCOIN_INTERACTIVE_SOLVER','true')
    from contextlib import contextmanager
    original_profile=browser.browser_profile
    @contextmanager
    def profile(*args):
        with original_profile(*args) as context:
            context.pages[0].goto=denied_goto.__get__(context.pages[0],type(context.pages[0]))
            yield context
    monkeypatch.setattr(browser,'browser_profile',profile)
    result=browser.search(browser.Searches(queries=[{'name':'Elden Ring','budget':5000}]))
    assert result['status']=='blocked' and result['retry_after']==86400
    assert 'request stopped without challenge interaction' in result['message']
    assert seen==[('price',1)]

def test_page_limit_validation():
    pytest.importorskip('playwright')
    from scripts.leboncoin_browser import Searches
    for pages in (0,6):
        with pytest.raises(ValueError):Searches(queries=[{'name':'game','budget':5000}],pages=pages)

def test_status_endpoint_reports_current_query_progress(monkeypatch):
    pytest.importorskip('playwright')
    from fastapi.testclient import TestClient
    from scripts import leboncoin_browser as browser
    browser.set_status(running=True,run_id='test',query='Elden Ring',sort='time',page=3,
                       pages_limit=5,cards_so_far=42,stage='loading_page')
    with TestClient(browser.app) as client:
        payload=client.get('/status').json()
    assert payload['query']=='Elden Ring' and payload['page']==3
    assert payload['cards_so_far']==42 and payload['running'] is True

def test_new_status_run_clears_stale_failure_fields():
    pytest.importorskip('playwright')
    from scripts import leboncoin_browser as browser
    browser.set_status(running=False,stage='failed',ended_at=123,error='previous failure',searches=[{'query':'old'}])
    browser.set_status(running=True,stage='starting',run_id='new-run',searches=[])
    payload=browser.status()
    assert payload=={'running':True,'stage':'starting','run_id':'new-run','searches':[]}

def test_failed_search_names_query_sort_page_and_preserves_partial_summary(monkeypatch):
    browser,seen=setup_browser(monkeypatch,lambda sort,page:[row(page)],blocked_page=None)
    page=browser.search
    # Make the second page's missing-card state unreadable rather than a confirmed empty result.
    original=browser.classify_page
    monkeypatch.setattr(browser,'classify_page',lambda text,*a,**kw:{'empty_search_detected':False,'challenge_detected':False,'consent_detected':False} if seen[-1][1]==2 else original(text,*a,**kw))
    # Use a page object that times out waiting on the second results page.
    original_profile=browser.browser_profile
    from contextlib import contextmanager
    from types import SimpleNamespace
    @contextmanager
    def profile(*args):
        with original_profile(*args) as context:
            old_page=context.pages[0]
            old_wait=old_page.wait_for
            def wait(**kwargs):
                if seen[-1][1]==2:raise TimeoutError('No listing cards')
                return old_wait(**kwargs)
            old_page.wait_for=wait
            yield context
    monkeypatch.setattr(browser,'browser_profile',profile)
    result=page(browser.Searches(queries=[{'name':'Elden Ring','budget':5000}]))
    assert result['status']=='error'
    assert 'Elden Ring' in result['message'] and 'price page 2' in result['message']
    assert result['searches'][0]['sorts']['price']['pages']==1
    assert result['searches'][0]['status']=='error'
