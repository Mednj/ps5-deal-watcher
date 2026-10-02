from app import db
from app.query_batches import advance,select


def test_batches_rotate_without_omitting_or_repeating_before_wrap():
    queries=[(f'Game {n}',1000+n) for n in range(11)]
    batches=[]
    with db.connect() as conn:
        for _ in range(4):
            batch=select(conn,'leboncoin',queries,4)
            batches.append([name for name,_ in batch.queries])
            advance(conn,'leboncoin',batch)
    assert batches==[
        ['Game 0','Game 1','Game 2','Game 3'],
        ['Game 4','Game 5','Game 6','Game 7'],
        ['Game 8','Game 9','Game 10'],
        ['Game 0','Game 1','Game 2','Game 3'],
    ]


def test_batch_cursor_does_not_advance_on_failed_check():
    queries=[(f'Game {n}',5000) for n in range(9)]
    with db.connect() as conn:
        first=select(conn,'vinted',queries,8)
        same=select(conn,'vinted',queries,8)
        assert first.queries==same.queries
        advance(conn,'vinted',first)
        second=select(conn,'vinted',queries,8)
    assert [q for q,_ in second.queries]==['Game 8']


def test_one_batch_needs_no_rotation_state():
    queries=[('Elden Ring',5000)]
    with db.connect() as conn:
        batch=select(conn,'vinted',queries,8)
        advance(conn,'vinted',batch)
        assert batch.describe()=='all 1 searches this pass'
        assert 'vinted_query_batch' not in db.settings(conn)
