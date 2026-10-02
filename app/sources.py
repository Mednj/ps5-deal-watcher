"""Bounded public adapters. Anonymous experimental catalogue access; no source logins or browser evasion."""
from dataclasses import dataclass
from decimal import Decimal
import os
import html
import json
import re
import time
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import httpx

from .models import Listing, HOSTS, cents
from scripts.leboncoin_limits import MAX_PAGES, client_budget, CHECK_BUDGET
from .matching import normalize, phrase

AGENT = 'PS5DealWatcher/0.1 (personal public-feed reader)'
URLS = {'dealabs':'https://www.dealabs.com/rss/groupe/jeux-playstation-5',
        'easycash':'https://bons-plans.easycash.fr/jeux-video/sony/ps5',
        'vinted':'https://www.vinted.fr/',
        'leboncoin':'https://www.leboncoin.fr/'}
MIN_INTERVAL = {'dealabs':300, 'easycash':14400, 'leboncoin':300, 'vinted':300}
CHECK_TIMEOUT = {'leboncoin': CHECK_BUDGET}

@dataclass
class Outcome:
    status: str
    message: str
    listings: list[Listing]
    retry_after: int = 0

class FetchError(Exception):
    def __init__(self, status, message, retry_after=0):
        self.status,self.message,self.retry_after=status,message,retry_after

def source_http_event(source, stage, response, byte_count=None):
    parts=urlsplit(str(response.url))
    event={'event':'source_http_response','source':source,'stage':stage,
           'host':parts.hostname,'path':parts.path,'status':response.status_code,
           'content_type':response.headers.get('content-type','').split(';',1)[0],
           'server':response.headers.get('server','')[:80],
           'datadome_header_present':any(k.lower().startswith('x-datadome') for k in response.headers)}
    if byte_count is not None:event['bytes']=byte_count
    print(json.dumps(event,sort_keys=True),flush=True)


def fetch_bytes(source, url, max_bytes=4_000_000, stage='feed'):
    with httpx.Client(timeout=httpx.Timeout(20,connect=8),follow_redirects=False,trust_env=False,headers={'User-Agent':AGENT}) as client:
        for _ in range(4):
            parts=urlsplit(url)
            if parts.scheme!='https' or parts.hostname not in HOSTS[source] or parts.port not in (None,443) or parts.username or parts.password:
                raise FetchError('blocked','Redirect outside the allowed source hosts was refused.')
            with client.stream('GET',url) as response:
                source_http_event(source,stage,response)
                if response.status_code in (301,302,303,307,308):
                    url=urljoin(url,response.headers.get('location',''))
                    continue
                if response.status_code in (401,403):
                    raise FetchError('blocked',f'{source.title()} {stage} request denied access (HTTP {response.status_code}). Use native alerts; no bypass attempted.')
                if response.status_code==429:
                    retry=response.headers.get('retry-after','3600')
                    try: retry=max(60,min(int(retry),86400))
                    except ValueError:
                        from email.utils import parsedate_to_datetime
                        try: retry=max(60,min(int(parsedate_to_datetime(retry).timestamp()-time.time()),86400))
                        except Exception: retry=3600
                    raise FetchError('rate-limited','Source returned 429; waiting before retry.',retry)
                if response.status_code!=200:
                    raise FetchError('error',f'Source returned HTTP {response.status_code}.')
                chunks=[]; size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>max_bytes: raise FetchError('error','Response exceeded the bounded download size.')
                    chunks.append(chunk)
                body=b''.join(chunks)
                source_http_event(source,stage,response,len(body))
                return body
        raise FetchError('error','Too many redirects.')

def plain(value):
    return BeautifulSoup(value,'html.parser').get_text(' ',strip=True)

def euro_near(text, patterns):
    for pattern in patterns:
        found=re.search(pattern,text,re.I)
        if found:
            try:return cents(found.group(1))
            except ValueError:pass
    return None

def parse_dealabs(body):
    try: root=ET.fromstring(body)
    except ET.ParseError as exc: raise FetchError('error','Expected RSS XML; parser failed or a challenge page was returned.') from exc
    if root.tag!='rss' or root.find('channel') is None:
        raise FetchError('error','Expected RSS channel; received another document.')
    results=[]
    for item in root.findall('./channel/item')[:100]:
        title=plain(item.findtext('title',''))
        description=plain(item.findtext('description',''))
        url=item.findtext('link','')
        merchant=item.find('{http://www.pepper.com/rss}merchant')
        price=merchant.get('price','') if merchant is not None else ''
        if not price:continue
        try: price_cents=cents(price)
        except ValueError:continue
        text=normalize(f'{title} {description}')
        platform='ps5' if re.search(r'\bps5\b|\bplaystation 5\b',text) else 'unknown'
        if re.search(r'\bps4\b',text) and platform!='ps5': platform='other'
        physical=True if any(phrase(x,description) for x in ['version physique','physical disc','disque','blu ray']) else None
        shipping=0 if phrase('livraison gratuite',description) else euro_near(description,[r'(?:livraison|frais de port|shipping)\s*(?:de|:|à|a)?\s*(\d+(?:[,.]\d{1,2})?)\s*€'])
        fees=0 if any(phrase(x,description) for x in ['sans frais de service','aucuns frais de service']) else None
        price_kind='exact'
        if any(phrase(x,title) for x in ['code promo','coupon']):price_kind='coupon'
        if any(phrase(x,title) for x in ['adherent','membre','membership']):price_kind='membership'
        image=item.find('{http://search.yahoo.com/mrss/}thumbnail')
        try:
            results.append(Listing(source='dealabs',external_id=url.rsplit('-',1)[-1],url=url,title=title,description=description[:15000],item_cents=price_cents,shipping_cents=shipping,fees_cents=fees,delivery=True if shipping is not None else None,platform=platform,physical=physical,price_kind=price_kind,condition='unknown',provenance='public PS5 RSS feed',availability='unverified',image=image.get('url','') if image is not None else ''))
        except ValueError:continue
    if root.findall('./channel/item') and not results:
        raise FetchError('error','RSS contained entries but no prices could be parsed; adapter needs review.')
    return results

def parse_easycash(body):
    soup=BeautifulSoup(body,'html.parser')
    if 'captcha' in soup.title.get_text().lower() if soup.title else False:
        raise FetchError('blocked','Challenge page returned.')
    results=[]; seen=set()
    for anchor in soup.select('a.link-buy[href]'):
        url=anchor['href']
        if url in seen or '/jeux-video/' not in url:continue
        seen.add(url)
        card=anchor.find_parent('li',class_='block-link')
        if card is None:continue
        price_node=card.select_one('.infos-price-number')
        if price_node is None:continue
        text=price_node.get_text(' ',strip=True)
        price=euro_near(text,[r'(\d+(?:[,.]\d{1,2})?)\s*€'])
        if price is None:continue
        title=anchor.get_text(' ',strip=True)
        if not title:continue
        try:
            results.append(Listing(source='easycash',external_id=url.rsplit('-',1)[-1],url=url,title=title,item_cents=price,condition='used',platform='ps5',physical=None,description='Catalogue reference across multiple offers. Open the source to choose an actual offer, confirm disc, stock and total.',price_kind='from',delivery=None,provenance='public first catalogue page; aggregate reference price',availability='unverified'))
        except ValueError:continue
    if not results:raise FetchError('error','Catalogue parser found no priced product cards. This is not an empty successful check.')
    return results

def check(source):
    if source=='leboncoin':return check_leboncoin()
    if source=='vinted':return check_vinted()
    if source not in URLS:
        return Outcome('blocked','Direct monitoring restricted. Use native saved searches and manual entry.',[])
    try:
        url=URLS[source]; parts=urlsplit(url)
        robots=fetch_bytes(source,f'https://{parts.netloc}/robots.txt',100000,stage='robots').decode('utf-8','replace')
        policy=RobotFileParser();policy.parse(robots.splitlines())
        if not policy.can_fetch(AGENT,url):
            return Outcome('blocked','robots.txt disallows this path. No page fetched.',[])
        body=fetch_bytes(source,url,stage='feed' if source=='dealabs' else 'catalogue')
        listings=parse_dealabs(body) if source=='dealabs' else parse_easycash(body)
        return Outcome('verified working' if source=='dealabs' else 'experimental',f'{len(listings)} recent feed entries.' if source=='dealabs' else f'{len(listings)} first-page catalogue references; review only.',listings)
    except FetchError as exc:return Outcome(exc.status,exc.message,[],exc.retry_after)
    except httpx.HTTPError:return Outcome('error','Network timeout or connection error. Existing listings preserved.',[])
    except Exception:return Outcome('error','Unexpected adapter/parser failure. Existing listings preserved.',[])


def vinted_response(client, url, stage='catalogue', **kwargs):
    # Fixed endpoints, bounded bodies and no redirects. Never retry access denials.
    with client.stream('GET', url, **kwargs) as response:
        source_http_event('vinted',stage,response)
        if response.status_code in (401,403):
            raise FetchError('blocked',f'Vinted {stage} request denied anonymous access (HTTP {response.status_code}). No bypass attempted.',86400)
        if response.status_code==429:
            from email.utils import parsedate_to_datetime
            value=response.headers.get('retry-after','300')
            try: retry=int(value)
            except ValueError:
                try: retry=int(parsedate_to_datetime(value).timestamp()-time.time())
                except Exception: retry=300
            raise FetchError('rate-limited',f'Vinted {stage} request was rate limited (HTTP 429); waiting before retry.',max(60,min(retry,86400)))
        if response.status_code!=200:
            raise FetchError('error',f'Vinted returned HTTP {response.status_code}.')
        body=bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body)>4_000_000:raise FetchError('error','Vinted response exceeded download limit.')
        source_http_event('vinted',stage,response,len(body))
        return bytes(body)


def parse_vinted(body):
    try: payload=json.loads(body)
    except (ValueError,TypeError):raise FetchError('error','Vinted returned invalid JSON or a challenge page.')
    if not isinstance(payload,dict) or not isinstance(payload.get('items'),list):
        raise FetchError('error','Vinted catalogue schema changed; expected items list.')
    results=[]
    for item in payload['items'][:24]:
        if not isinstance(item,dict):continue
        try:
            price=item.get('price') or {}
            if price.get('currency_code')!='EUR':continue
            title=str(item['title']);text=normalize(title)
            platform='ps5' if re.search(r'\bps5\b|\bplaystation 5\b',text) else 'unknown'
            if platform=='unknown' and re.search(r'\bps4\b|\bxbox\b|\bpc\b|\bswitch\b',text):platform='other'
            # Catalogue titles alone do not establish a physical disc or delivery eligibility.
            unavailable=bool(item.get('is_closed') or item.get('is_reserved') or item.get('is_sold'))
            results.append(Listing(source='vinted',external_id=str(item['id']),url=urljoin('https://www.vinted.fr/',str(item['url'])),title=title,item_cents=cents(str(price['amount'])),platform=platform,physical=None,delivery=None,availability='unavailable' if unavailable else 'unverified',provenance='experimental anonymous Vinted catalogue',description='Item price only. Disc, edition, delivery, buyer protection and shipping must be confirmed on Vinted. Pickup location unknown.'))
        except (ValueError,TypeError,KeyError,AttributeError):continue
    if payload['items'] and not results:raise FetchError('error','Vinted entries could not be parsed; adapter needs review.')
    return results


def check_vinted(queries=None):
    try:
        if queries is None:
            from . import db
            from .models import Watch
            from .matching import eligible
            grouped={}
            with db.connect() as conn:
                for row in conn.execute('SELECT data FROM watches ORDER BY id'):
                    watch=Watch.model_validate_json(row['data'])
                    if 'vinted' not in watch.sources or not eligible(watch,time.time()):continue
                    for name in [watch.name,*watch.aliases]:
                        query=name+' PS5'
                        grouped[query]=max(grouped.get(query,0),watch.max_cents)
            queries=list(grouped.items())
        if not queries:return Outcome('experimental','No active Vinted watches to search.',[])
        grouped={}
        for name,budget in queries:grouped[name]=max(grouped.get(name,0),budget)
        queries=list(grouped.items())
        if len(queries)>8:return Outcome('error',f'Vinted has {len(queries)} distinct active game/alias searches; the per-check limit is 8. Reduce active searches to avoid partial coverage.',[])
        results={}
        with httpx.Client(timeout=httpx.Timeout(20,connect=8),follow_redirects=False,trust_env=False,headers={'User-Agent':AGENT,'Accept-Language':'fr-FR'}) as client:
            vinted_response(client,'https://www.vinted.fr/',stage='homepage')
            headers={'Accept':'application/json','Platform':'web','x-next-app':'marketplace-web','Origin':'https://www.vinted.fr','Referer':'https://www.vinted.fr/','Locale':'fr-FR'}
            anon=client.cookies.get('anon_id')
            if anon:headers['X-Anon-Id']=anon
            for name,budget in queries:
                for order in ('price_low_to_high','newest_first'):
                    params={'page':1,'per_page':24,'search_text':name,'order':order,'price_to':format(Decimal(budget)/100,'.2f'),'currency':'EUR'}
                    body=vinted_response(client,'https://api.vinted.fr/svc-catalogue/items',stage='catalogue',params=params,headers=headers)
                    for listing in parse_vinted(body):
                        if listing.item_cents<=budget:results[listing.external_id]=listing
        return Outcome('experimental',f'{len(results)} catalogue listings from {len(queries)} searches (cheapest + newest, deduplicated). Item prices only; disc, delivery and fees need review.',list(results.values()))
    except FetchError as exc:return Outcome(exc.status,exc.message,[],exc.retry_after)
    except httpx.HTTPError:return Outcome('error','Vinted network timeout or connection error. Existing listings preserved.',[])
    except Exception:return Outcome('error','Vinted adapter/parser failed. Existing listings preserved.',[])


def parse_leboncoin(items):
    if not isinstance(items,list):raise FetchError('error','Browser returned invalid listing schema.')
    results=[]
    for item in items:
        try:
            text=item['text'];title=text.split('\n',1)[0].strip()
            found=re.search(r'Prix:\s*([0-9]+(?:[,.][0-9]{1,2})?)\s*€',text)
            if not found:continue
            url=item['url'];platform='ps5' if re.search(r'\bps5\b|\bplaystation 5\b',normalize(title)) else 'unknown'
            unavailable=any(phrase(term,text) for term in ['achat en cours','vendu','annonce expirée'])
            results.append(Listing(source='leboncoin',external_id=urlsplit(url).path.rsplit('/',1)[-1],url=url,title=title,description=text[:5000],item_cents=cents(found.group(1)),platform=platform,physical=None,delivery=True if phrase('livraison',text) else None,availability='unavailable' if unavailable else 'unverified',provenance='experimental headed browser search cards'))
        except (KeyError,TypeError,ValueError,AttributeError):continue
    if items and not results:raise FetchError('error','No advertised item prices parsed; browser cards need review.')
    return results


def check_leboncoin(queries=None):
    try:
        if queries is None:
            from . import db
            from .models import Watch
            from .matching import eligible
            grouped={}
            with db.connect() as conn:
                for row in conn.execute('SELECT data FROM watches ORDER BY id'):
                    watch=Watch.model_validate_json(row['data'])
                    if 'leboncoin' not in watch.sources or not eligible(watch,time.time()):continue
                    for name in [watch.name,*watch.aliases]:
                        query=name+' PS5';grouped[query]=max(grouped.get(query,0),watch.max_cents)
            queries=list(grouped.items())
        if not queries:return Outcome('experimental','No active Leboncoin watches to search.',[])
        if len(queries)>4:return Outcome('error','Leboncoin supports at most 4 distinct active game/alias searches.',[])
        with httpx.Client(timeout=client_budget(len(queries)),trust_env=False) as client:
            response=client.post(os.environ.get('LEBONCOIN_BROWSER_URL','http://browser:8770')+'/search',json={'queries':[{'name':name,'budget':budget} for name,budget in queries],'pages':MAX_PAGES})
            if response.status_code!=200:return Outcome('error','Internal browser service unavailable or rejected input.',[])
            payload=response.json()
        status=payload.get('status')
        if status not in ('experimental','blocked','rate-limited','error'):raise FetchError('error','Browser returned invalid status.')
        if status!='experimental':
            detail=payload.get('message','Browser check failed.')
            searches=payload.get('searches',[])
            if searches:
                summary='; '.join(f"{s.get('query','search')}: {s.get('status','unknown')} ({s.get('pages',0)} pages, {s.get('cards',0)} cards)" for s in searches)
                detail=f'{detail} Searches: {summary}.'
            return Outcome(status,detail,[],int(payload.get('retry_after',300)))
        budget=max(b for _,b in queries)
        listings={l.external_id:l for l in parse_leboncoin(payload.get('items')) if l.item_cents<=budget}
        summary='; '.join(f"{s.get('query','search')}: {s.get('pages',0)} pages, {s.get('cards',0)} cards" for s in payload.get('searches',[]))
        detail=f"{len(listings)} browser listings; {payload.get('pages_fetched','unknown')} pages fetched. Up to {MAX_PAGES} per cheapest/newest search."
        if summary:detail+=f' Searches: {summary}.'
        return Outcome('experimental',detail+' Item prices; game-name matching applies.',list(listings.values()))
    except FetchError as exc:return Outcome(exc.status,exc.message,[],exc.retry_after)
    except Exception:return Outcome('error','Leboncoin browser connection or parser failed. Existing listings preserved.',[])
