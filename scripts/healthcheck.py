import time
from app import db
with db.connect() as conn:
    heartbeat=float(db.settings(conn).get('worker_heartbeat',0))
if time.time()-heartbeat>90:
    raise SystemExit(1)
