"""Create integrity-checked daily SQLite snapshots in a separate volume."""
from datetime import datetime,timezone
import os
from pathlib import Path
import signal
import sqlite3
import time
import uuid
from app import db

def backup_once(now=None,force=False):
    now=time.time() if now is None else now
    directory=Path(os.environ.get('BACKUP_DIR','/backups'))
    directory.mkdir(parents=True,exist_ok=True)
    # A single Compose backup service owns this directory; remove debris from an interrupted write.
    for stale in directory.glob('.watcher-*'):
        if stale.is_file():stale.unlink(missing_ok=True)
    interval=max(3600,int(os.environ.get('BACKUP_INTERVAL_SECONDS','86400')))
    existing=sorted(directory.glob('watcher-*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)
    if existing and not force and now-existing[0].stat().st_mtime<interval:return existing[0]
    stamp=datetime.fromtimestamp(now,timezone.utc).strftime('%Y%m%d-%H%M%S')
    temporary=directory/f'.watcher-{stamp}-{uuid.uuid4().hex[:8]}.partial'
    target=directory/f'watcher-{stamp}.sqlite3'
    try:
        db.backup(temporary)
        check=sqlite3.connect(temporary)
        try:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity check failed.')
            version=check.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if not version or version[0]!='1':raise RuntimeError('Backup schema version is unsupported.')
            checkpoint=check.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
            if checkpoint and checkpoint[0]!=0:raise RuntimeError('Backup WAL checkpoint was busy.')
            check.execute('PRAGMA journal_mode=DELETE')
        finally:check.close()
        os.replace(temporary,target)
        target.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)
    keep=max(2,min(90,int(os.environ.get('BACKUP_RETAIN_COUNT','14'))))
    for old in sorted(directory.glob('watcher-*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)[keep:]:
        old.unlink(missing_ok=True)
    return target

def main():
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopping:
        try:
            target=backup_once()
            print(f'Backup ready: {target.name}',flush=True)
        except Exception as exc:
            print(f'Backup failed: {type(exc).__name__}; will retry.',flush=True)
        for _ in range(3600):
            if stopping:break
            time.sleep(1)

if __name__=='__main__':main()
