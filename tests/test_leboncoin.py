import httpx
from app import sources
from app.matching import match
from app.models import Watch


def card(text='Elden Ring PS5\nPrix: 27 €.', url='https://www.leboncoin.fr/ad/jeux_video/123'):
    return {'text': text, 'url': url}


def test_browser_card_price_and_name_match():
    listing = sources.parse_leboncoin([card()])[0]
    assert listing.item_cents == 2700 and listing.external_id == '123'
    assert listing.shipping_cents is None and listing.physical is None
    assert match(Watch(name='Elden Ring', max_cents=5000), listing).state == 'qualified'


def test_pending_purchase_excluded_and_external_url_refused():
    items = sources.parse_leboncoin([card('Elden Ring PS5\nPrix: 15 €.\nAchat en cours'),
                                    card(url='https://evil.example/ad/123')])
    assert len(items) == 1
    assert match(Watch(name='Elden Ring', max_cents=5000), items[0]).state == 'excluded'


def test_no_price_is_not_shipping_price():
    listing = sources.parse_leboncoin([card(), card('Recherche Elden Ring\nLivraison dès 2,49 €')])
    assert len(listing) == 1


def test_browser_connection_payload_dedup_budget_and_block(monkeypatch):
    real_client = httpx.Client

    def respond(request):
        assert request.url.path == '/search'
        return httpx.Response(200, json={'status': 'experimental', 'items': [card(), card(),
            card('Elden Ring PS5\nPrix: 60 €.', 'https://www.leboncoin.fr/ad/jeux_video/456')]})

    monkeypatch.setattr(sources.httpx, 'Client', lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), **kwargs))
    outcome = sources.check_leboncoin([('Elden Ring PS5', 5000)])
    assert outcome.status == 'experimental' and len(outcome.listings) == 1
    assert sources.check_leboncoin([('game', 5000)] * 5).status == 'error'

    monkeypatch.setattr(sources.httpx, 'Client', lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'status': 'blocked', 'message': '403', 'retry_after': 86400})), **kwargs))
    outcome = sources.check_leboncoin([('Elden Ring PS5', 5000)])
    assert outcome.status == 'blocked' and outcome.retry_after == 86400 and not outcome.listings
