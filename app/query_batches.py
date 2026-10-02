"""Persistent round-robin batches for bounded marketplace search workloads."""
from dataclasses import dataclass
from math import ceil

from . import db


@dataclass(frozen=True)
class QueryBatch:
    queries: list[tuple[str, int]]
    total: int
    index: int
    count: int
    next_cursor: int

    @property
    def partial(self):
        return self.count > 1

    def describe(self):
        if self.partial:
            return f"batch {self.index}/{self.count}; {len(self.queries)} of {self.total} searches this pass"
        return f"all {self.total} searches this pass"


def select(conn, source, queries, limit):
    queries=list(queries)
    total=len(queries)
    if not total:
        return QueryBatch([],0,0,0,0)
    count=ceil(total/limit)
    key=f'{source}_query_batch'
    settings=db.settings(conn)
    try:cursor=int(settings.get(key,'0'))%count
    except (TypeError,ValueError):cursor=0
    start=cursor*limit
    return QueryBatch(queries[start:start+limit],total,cursor+1,count,(cursor+1)%count)


def advance(conn, source, batch):
    if batch.count>1:
        db.setting(conn,f'{source}_query_batch',batch.next_cursor)
