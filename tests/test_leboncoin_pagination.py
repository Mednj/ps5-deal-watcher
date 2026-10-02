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
    assert client_budget(4)>client_budget(1)>150 and CHECK_BUDGET>client_budget(4)

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

def test_page_limit_validation():
    pytest.importorskip('playwright')
    from scripts.leboncoin_browser import Searches
    for pages in (0,6):
        with pytest.raises(ValueError):Searches(queries=[{'name':'game','budget':5000}],pages=pages)
