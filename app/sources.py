"""Bounded public adapters. Never use source logins, private APIs or browser evasion."""
from dataclasses import dataclass
from decimal import Decimal
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
from .matching import normalize, phrase

AGENT = 'PS5DealWatcher/0.1 (personal public-feed reader)'
URLS = {'dealabs':'https://www.dealabs.com/rss/groupe/jeux-playstation-5',
        'easycash':'https://bons-plans.easycash.fr/jeux-video/sony/ps5'}
MIN_INTERVAL = {'dealabs':3600, 'easycash':14400, 'leboncoin':3600, 'vinted':3600}

@dataclass
class Outcome:
    status: str
    message: str
    listings: list[Listing]
    retry_after: int = 0

class FetchError(Exception):
    def __init__(self, status, message, retry_after=0):
        self.status,self.message,self.retry_after=status,message,retry_after

def fetch_bytes(source, url, max_bytes=4_000_000):
    with httpx.Client(timeout=httpx.Timeout(20,connect=8),follow_redirects=False,trust_env=False,headers={'User-Agent':AGENT}) as client:
        for _ in range(4):
            parts=urlsplit(url)
            if parts.scheme!='https' or parts.hostname not in HOSTS[source] or parts.port not in (None,443) or parts.username or parts.password:
                raise FetchError('blocked','Redirect outside the allowed source hosts was refused.')
            with client.stream('GET',url) as response:
                if response.status_code in (301,302,303,307,308):
                    url=urljoin(url,response.headers.get('location',''))
                    continue
                if response.status_code in (401,403):
                    raise FetchError('blocked','Access denied; use native alerts. No bypass attempted.')
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
                return b''.join(chunks)
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
    if source not in URLS:
        return Outcome('blocked','Direct monitoring restricted. Use native saved searches and manual entry.',[])
    try:
        url=URLS[source]; parts=urlsplit(url)
        robots=fetch_bytes(source,f'https://{parts.netloc}/robots.txt',100000).decode('utf-8','replace')
        policy=RobotFileParser();policy.parse(robots.splitlines())
        if not policy.can_fetch(AGENT,url):
            return Outcome('blocked','robots.txt disallows this path. No page fetched.',[])
        body=fetch_bytes(source,url)
        listings=parse_dealabs(body) if source=='dealabs' else parse_easycash(body)
        return Outcome('verified working' if source=='dealabs' else 'experimental',f'{len(listings)} recent feed entries.' if source=='dealabs' else f'{len(listings)} first-page catalogue references; review only.',listings)
    except FetchError as exc:return Outcome(exc.status,exc.message,[],exc.retry_after)
    except httpx.HTTPError:return Outcome('error','Network timeout or connection error. Existing listings preserved.',[])
    except Exception:return Outcome('error','Unexpected adapter/parser failure. Existing listings preserved.',[])
