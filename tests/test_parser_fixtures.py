from pathlib import Path
import json

import pytest

from app import sources

FIXTURES=Path(__file__).parent/'fixtures'/'parsers'

def fixture(name):
    return (FIXTURES/name).read_bytes()

@pytest.mark.parametrize(('name','parser','source','price'),[
    ('dealabs.xml',sources.parse_dealabs,'dealabs',2499),
    ('easycash.html',sources.parse_easycash,'easycash',2999),
    ('vinted.json',sources.parse_vinted,'vinted',1950),
])
def test_redacted_parser_contract_fixtures(name,parser,source,price):
    listings=parser(fixture(name))
    assert len(listings)==1
    assert listings[0].source==source
    assert listings[0].item_cents==price

def test_redacted_leboncoin_parser_contract_fixture():
    listings=sources.parse_leboncoin(json.loads(fixture('leboncoin.json')))
    assert len(listings)==1 and listings[0].item_cents==3400

@pytest.mark.parametrize(('name','parser'),[
    ('dealabs-empty.xml',sources.parse_dealabs),
    ('easycash-empty.html',sources.parse_easycash),
    ('vinted-empty.json',sources.parse_vinted),
])
def test_valid_empty_results_remain_successful(name,parser):
    assert parser(fixture(name))==[]

def test_redacted_leboncoin_empty_fixture_is_valid():
    assert sources.parse_leboncoin(json.loads(fixture('leboncoin-empty.json')))==[]

@pytest.mark.parametrize(('parser',),[(sources.parse_dealabs,), (sources.parse_easycash,), (sources.parse_vinted,)])
def test_challenge_html_is_never_reported_as_empty(parser):
    with pytest.raises(sources.FetchError) as error:
        parser(fixture('challenge.html'))
    assert error.value.status=='challenge'
    assert 'no listings were ingested' in error.value.message

def test_leboncoin_browser_challenge_is_kept_distinct_from_empty(monkeypatch):
    import httpx
    real_client=httpx.Client
    monkeypatch.setattr(sources.httpx,'Client',lambda **kwargs:real_client(
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
            'status':'challenge','message':'challenge slide_to_end','items':[]})),**kwargs))
    outcome=sources.check_leboncoin([('Redacted Game PS5',5000)])
    assert outcome.status=='challenge' and not outcome.listings

def test_leboncoin_valid_empty_browser_response_is_success(monkeypatch):
    import httpx
    real_client=httpx.Client
    monkeypatch.setattr(sources.httpx,'Client',lambda **kwargs:real_client(
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
            'status':'experimental','message':'valid empty search','items':[],
            'pages_fetched':1,'searches':[]})),**kwargs))
    outcome=sources.check_leboncoin([('Redacted Game PS5',5000)])
    assert outcome.status=='experimental' and not outcome.listings
    assert 'Valid search pages contained no matching cards.' in outcome.message

@pytest.mark.parametrize(('parser','body'),[
    (sources.parse_dealabs,b'<html><title>Unexpected page</title><p>Page layout changed</p></html>'),
    (sources.parse_easycash,b'<html><title>Unexpected page</title><main>Page layout changed</main></html>'),
    (sources.parse_vinted,b'<html><title>Unexpected page</title></html>'),
    (sources.parse_leboncoin,[{'url':'https://www.leboncoin.fr/ad/jeux_video/1','text':'Redacted card without a price'}]),
])
def test_unrecognized_nonempty_responses_are_format_changes(parser,body):
    with pytest.raises(sources.FetchError) as error:parser(body)
    assert error.value.status=='format-change'

