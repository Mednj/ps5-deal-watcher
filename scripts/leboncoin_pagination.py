"""Bounded pagination and canonical listing deduplication."""
import re
from urllib.parse import urlencode, urlsplit

def search_url(name, budget, sort, order, page):
    return 'https://www.leboncoin.fr/recherche?' + urlencode({
        'text': name, 'price': f'min-{(budget + 99) // 100}',
        'sort': sort, 'order': order, 'page': page})

def canonical_listing(url):
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.hostname not in ('www.leboncoin.fr','leboncoin.fr'):
        return None
    matched=re.fullmatch(r'/ad/jeux_video/(\d+)/?',parts.path)
    return 'https://www.leboncoin.fr/ad/jeux_video/'+matched.group(1) if matched else None

class PageTracker:
    def __init__(self):
        self.fingerprints=set()

    def collect(self, rows, items):
        normalized={}
        for row in rows:
            url=canonical_listing(row['url'])
            if url:normalized[url]={**row,'url':url}
        fingerprint=frozenset(normalized)
        if not fingerprint:return 'empty'
        if fingerprint in self.fingerprints:return 'repeated'
        self.fingerprints.add(fingerprint)
        items.update(normalized)
        return None
