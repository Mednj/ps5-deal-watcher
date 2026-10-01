import httpx
import pytest
from app import sources

def test_easycash_each_product_uses_its_own_price():
    body=b'''<html><ul><li class="block-link"><h3><a class="link-buy" href="https://bons-plans.easycash.fr/jeux-video/f1-25-100">F1 25 PS5</a></h3><p class="infos-price-number">24,99 &#8364;</p></li><li class="block-link"><h3><a class="link-buy" href="https://bons-plans.easycash.fr/jeux-video/god-of-war-200">God of War PS5</a></h3><p class="infos-price-number">21,99 &#8364;</p></li></ul></html>'''
    listings=sources.parse_easycash(body)
    assert [item.item_cents for item in listings]==[2499,2199]
    assert all(item.price_kind=='from' and item.physical is None for item in listings)

@pytest.mark.parametrize('status,expected',[(403,'blocked'),(429,'rate-limited'),(500,'error')])
def test_http_failures_are_explicit(monkeypatch,status,expected):
    real_client=httpx.Client
    transport=httpx.MockTransport(lambda req:httpx.Response(status,headers={'retry-after':'300'},text='Challenge or error'))
    monkeypatch.setattr(sources.httpx,'Client',lambda **kwargs:real_client(transport=transport,**kwargs))
    with pytest.raises(sources.FetchError) as exc:sources.fetch_bytes('dealabs',sources.URLS['dealabs'])
    assert exc.value.status==expected
    if status==429:assert exc.value.retry_after==300

def test_redirect_to_private_host_refused(monkeypatch):
    real_client=httpx.Client
    transport=httpx.MockTransport(lambda req:httpx.Response(302,headers={'location':'http://127.0.0.1/private'}))
    monkeypatch.setattr(sources.httpx,'Client',lambda **kwargs:real_client(transport=transport,**kwargs))
    with pytest.raises(sources.FetchError) as exc:sources.fetch_bytes('dealabs',sources.URLS['dealabs'])
    assert exc.value.status=='blocked'
