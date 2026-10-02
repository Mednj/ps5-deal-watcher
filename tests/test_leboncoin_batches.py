import json

import httpx

from app import db, sources
from app.models import Watch


def test_active_leboncoin_searches_rotate_in_batches(monkeypatch):
    real_client=httpx.Client
    sent=[]
    def respond(request):
        payload=json.loads(request.content)
        sent.extend(query['name'] for query in payload['queries'])
        return httpx.Response(200,json={'status':'experimental','items':[],'pages_fetched':10,'searches':[]})
    monkeypatch.setattr(sources.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(respond),**kwargs))
    names=[f'Game {n:02}' for n in range(11)]
    with db.connect() as conn:
        for name in names:
            watch=Watch(name=name,max_cents=5000,sources=['leboncoin'])
            conn.execute('INSERT INTO watches(data,next_at,created_at) VALUES(?,?,?)',(watch.model_dump_json(),0,0))
    outcomes=[sources.check_leboncoin() for _ in range(3)]
    assert all(outcome.status=='experimental' for outcome in outcomes)
    assert ['4 of 11 searches' in outcomes[0].message,
            '4 of 11 searches' in outcomes[1].message,
            '3 of 11 searches' in outcomes[2].message]
    assert sent==[f'{name} PS5' for name in names]
