import json
import os
from pathlib import Path
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS watches(id INTEGER PRIMARY KEY, data TEXT NOT NULL, next_at REAL NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL, last_success REAL, next_at REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, data TEXT NOT NULL, first_at REAL NOT NULL, last_at REAL NOT NULL, UNIQUE(source,external_id));
CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE, at REAL NOT NULL, item_cents INTEGER NOT NULL, shipping_cents INTEGER, fees_cents INTEGER);
CREATE TABLE IF NOT EXISTS matches(watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE, listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE, state TEXT NOT NULL, reason TEXT NOT NULL, total_cents INTEGER, route TEXT, hidden INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL, PRIMARY KEY(watch_id,listing_id));
CREATE TABLE IF NOT EXISTS notified(watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE, listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE, lowest_cents INTEGER NOT NULL, PRIMARY KEY(watch_id,listing_id));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE, listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE, price_cents INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL, created_at REAL NOT NULL, last_error TEXT NOT NULL DEFAULT '', message TEXT NOT NULL, UNIQUE(watch_id,listing_id,price_cents));
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE, at REAL NOT NULL, success INTEGER NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, source TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL, status TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS leases(name TEXT PRIMARY KEY, owner TEXT NOT NULL, until_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS monitor_incidents(key TEXT PRIMARY KEY, title TEXT NOT NULL, since REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1, notified INTEGER NOT NULL DEFAULT 0, next_alert REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS monitor_samples(at REAL PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS monitor_pending(event_id INTEGER PRIMARY KEY, since REAL NOT NULL);
CREATE INDEX IF NOT EXISTS events_due ON events(state,next_at);
CREATE INDEX IF NOT EXISTS observations_at ON observations(at);
"""

SOURCE_SEED = [
 ('dealabs', 1, 'verified working', 'Public PS5 RSS feed; recent entries only. Shipping, disc format and availability may need review.'),
 ('leboncoin', 0, 'experimental', 'Headed Docker browser: cheapest and newest game searches. Enable to evaluate; access and coverage remain experimental.'),
 ('vinted', 0, 'experimental', 'Anonymous catalogue searches for configured games. Item-price candidates only; disc, delivery and fees require review. Enable to evaluate.'),
 ('easycash', 0, 'experimental', 'Public first catalogue page only; prices may be from several offers. Review candidates only. Enable to evaluate.'),
]

def path():
    return Path(os.environ.get('DATA_DIR', 'data')) / 'watcher.sqlite3'

def connect():
    conn = sqlite3.connect(path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    return conn

def init():
    os.umask(0o077)
    path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript(SCHEMA)
        if 'manual' not in {r['name'] for r in conn.execute('PRAGMA table_info(events)')}:
            conn.execute('ALTER TABLE events ADD COLUMN manual INTEGER NOT NULL DEFAULT 0')
        conn.execute("INSERT OR IGNORE INTO metadata VALUES('schema_version','1')")
        for source in SOURCE_SEED:
            conn.execute('INSERT OR IGNORE INTO sources(id,enabled,status,message) VALUES(?,?,?,?)', source)
        defaults = {'timezone':'Europe/Paris', 'default_interval':'5', 'quiet_start':'', 'quiet_end':'', 'retention_days':'90'}
        for key,value in defaults.items():
            conn.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', (key,value))
    try:
        path().chmod(0o600)
    except OSError:
        pass

def settings(conn):
    return {r['key']: r['value'] for r in conn.execute('SELECT * FROM settings')}

def setting(conn, key, value):
    conn.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,str(value)))

def acquire(conn, name, owner, now, duration=180):
    cursor = conn.execute('INSERT INTO leases VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,until_at=excluded.until_at WHERE leases.until_at < ? OR leases.owner = ?', (name,owner,now+duration,now,owner))
    return cursor.rowcount == 1

def put_listing(conn, listing, now):
    listing = listing.model_copy(update={'observed_at': now})
    conn.execute('INSERT INTO listings(source,external_id,data,first_at,last_at) VALUES(?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET data=excluded.data,last_at=excluded.last_at', (listing.source,listing.external_id,listing.model_dump_json(),now,now))
    row = conn.execute('SELECT id FROM listings WHERE source=? AND external_id=?',(listing.source,listing.external_id)).fetchone()
    conn.execute('INSERT INTO observations(listing_id,at,item_cents,shipping_cents,fees_cents) VALUES(?,?,?,?,?)', (row['id'],now,listing.item_cents,listing.shipping_cents,listing.fees_cents))
    return row['id']

def backup(destination):
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = connect()
    try:
        dest = sqlite3.connect(target)
        try:source.backup(dest)
        finally:dest.close()
    finally:
        source.close()
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target
