import json

import httpx
import pytest

from app import sources
from app.matching import match
from app.models import Watch


def item(**changes):
    value = dict(id=123, title='Elden Ring PS5', url='/items/123-elden-ring',
                 price={'amount': '25.00', 'currency_code': 'EUR'},
                 total_item_price={'amount': '26.95', 'currency_code': 'EUR'})
    value.update(changes)
    return value


def test_catalogue_does_not_invent_disc_delivery_or_checkout_total():
    listing = sources.parse_vinted(json.dumps({'items': [item()]}))[0]
    assert listing.item_cents == 2500
    assert listing.platform == 'ps5'
    assert listing.physical is None and listing.delivery is None
    assert listing.shipping_cents is None and listing.fees_cents is None
    assert listing.url == 'https://www.vinted.fr/items/123-elden-ring'
    result = match(Watch(qualification='strict',name='Elden Ring', max_cents=5000), listing)
    assert result.state == 'candidate' and result.total is None


def test_invalid_hosts_currency_and_wrong_platform():
    entries = [item(url='https://evil.example/item'),
               item(price={'amount': '10', 'currency_code': 'USD'}),
               item(title='Elden Ring Xbox')]
    listings = sources.parse_vinted(json.dumps({'items': entries}))
    assert len(listings) == 1
    assert match(Watch(qualification='strict',name='Elden Ring', max_cents=5000), listings[0]).state == 'excluded'


@pytest.mark.parametrize('body', ['<html>challenge</html>', '{}', '{"items":{}}'])
def test_schema_failure_is_not_empty_success(body):
    with pytest.raises(sources.FetchError):
        sources.parse_vinted(body)


@pytest.mark.parametrize('status,expected', [(403, 'blocked'), (429, 'rate-limited')])
def test_denial_stops_without_retry(monkeypatch, status, expected):
    real_client = httpx.Client
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={'retry-after': '600'})

    monkeypatch.setattr(sources.httpx, 'Client', lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs))
    outcome = sources.check_vinted([('Elden Ring PS5', 4999)])
    assert outcome.status == expected and not outcome.listings
    assert len(requests) == 1
    if status==403:assert 'homepage' in outcome.message and '403' in outcome.message
    if status == 429:
        assert outcome.retry_after == 600


def test_search_is_bounded_deduplicated_and_locally_price_filtered(monkeypatch):
    real_client = httpx.Client
    requests = []

    def respond(request):
        requests.append(request)
        if request.url.host == 'www.vinted.fr':
            return httpx.Response(200, text='Anonymous home')
        assert request.url.params['price_to'] == '49.99'
        assert request.url.params['per_page'] == '24'
        unique = item(id=789 if request.url.params['order']=='price_low_to_high' else 987)
        return httpx.Response(200, json={'items': [item(), item(), unique,
            item(id=456, price={'amount': '60', 'currency_code': 'EUR'})]})

    monkeypatch.setattr(sources.httpx, 'Client', lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs))
    outcome = sources.check_vinted([('Elden Ring PS5', 4999)])
    assert outcome.status == 'experimental'
    assert len(outcome.listings) == 3 and len(requests) == 3
    assert {r.url.params['order'] for r in requests[1:]} == {'price_low_to_high', 'newest_first'}
    capped=sources.check_vinted([(f'game {n}',5000) for n in range(9)])
    assert capped.status == 'error' and '9 distinct' in capped.message and not capped.listings


def test_explicit_duplicate_vinted_searches_are_merged(monkeypatch):
    real_client=httpx.Client
    requests=[]
    def respond(request):
        requests.append(request)
        if request.url.host=='www.vinted.fr':return httpx.Response(200,text='Anonymous home')
        return httpx.Response(200,json={'items':[]})
    monkeypatch.setattr(sources.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(respond),**kwargs))
    outcome=sources.check_vinted([('Elden Ring PS5',4000),('Elden Ring PS5',5000)])
    assert outcome.status=='experimental' and '1 searches' in outcome.message
    assert len(requests)==3


def test_name_price_qualifies_without_disc_platform_or_fees():
    listing = sources.parse_vinted(json.dumps({'items': [item(title='Elden Ring')]}))[0]
    watch = Watch(name='Elden Ring', max_cents=5000)
    result = match(watch, listing)
    assert result.state == 'qualified' and result.total == 2500
    assert match(watch.model_copy(update={'max_cents': 2499}), listing).state == 'over-budget'
    assert match(watch.model_copy(update={'name': 'Dead Space'}), listing).state == 'excluded'
    assert match(watch, listing.model_copy(update={'availability': 'unavailable'})).state == 'excluded'
