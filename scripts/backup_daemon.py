"""Create integrity-checked daily SQLite snapshots in a separate volume."""
from datetime import datetime,timezone
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from app import db

def restore_verification_valid(directory,backup):
    try:
        marker=json.loads((Path(directory)/'.restore-verified').read_text())
        return marker.get('backup')==backup.name and float(marker.get('verified_at',0))>=backup.stat().st_mtime
    except (OSError,TypeError,ValueError,json.JSONDecodeError):return False

def backup_healthy(directory='/backups',now=None,check_integrity=False):
    now=time.time() if now is None else now
    files=sorted(Path(directory).glob('watcher-*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not files or now-files[0].stat().st_mtime>=48*3600 or not restore_verification_valid(directory,files[0]):return False
    if not check_integrity:return True
    try:
        with closing(sqlite3.connect(f'file:{files[0].resolve().as_posix()}?mode=ro',uri=True)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':return False
            version=conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            return bool(version and version[0]=='1')
    except (OSError,sqlite3.Error):return False

def _record_restore_verification(directory,backup):
    directory=Path(directory)
    temporary=directory/'.restore-verified.partial'
    marker=directory/'.restore-verified'
    try:
        temporary.write_text(json.dumps({'backup':backup.name,'verified_at':time.time()}))
        temporary.chmod(0o600)
        os.replace(temporary,marker)
    finally:temporary.unlink(missing_ok=True)

def _restore_drill(backup,directory):
    with tempfile.TemporaryDirectory(prefix='.restore-test-',dir=directory) as scratch:
        environment=os.environ.copy();environment['DATA_DIR']=scratch
        result=subprocess.run([sys.executable,'-m','scripts.restore',str(backup),'--confirm-replace'],
            env=environment,capture_output=True,text=True,timeout=180)
        restored=Path(scratch)/'watcher.sqlite3'
        if result.returncode or not restored.is_file():raise RuntimeError('Backup restore drill failed.')
        source_uri=f'file:{backup.resolve().as_posix()}?mode=ro'
        restored_uri=f'file:{restored.resolve().as_posix()}?mode=ro'
        with closing(sqlite3.connect(source_uri,uri=True)) as source,closing(sqlite3.connect(restored_uri,uri=True)) as clone:
            if clone.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Restored backup integrity check failed.')
            version=clone.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if not version or version[0]!='1':raise RuntimeError('Restored backup schema version is unsupported.')
            tables=[row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                escaped=table.replace('"','""')
                source_count=source.execute(f'SELECT count(*) FROM "{escaped}"').fetchone()[0]
                clone_count=clone.execute(f'SELECT count(*) FROM "{escaped}"').fetchone()[0]
                if source_count!=clone_count:raise RuntimeError('Restored backup row counts do not match.')

def backup_once(now=None,force=False):
    now=time.time() if now is None else now
    directory=Path(os.environ.get('BACKUP_DIR','/backups'))
    directory.mkdir(parents=True,exist_ok=True)
    # A single Compose backup service owns this directory; remove debris from an interrupted write.
    for stale in [*directory.glob('.watcher-*'),*directory.glob('.restore-test-*')]:
        if stale.is_file():stale.unlink(missing_ok=True)
        elif stale.is_dir():
            import shutil
            shutil.rmtree(stale,ignore_errors=True)
    (directory/'.restore-verified.partial').unlink(missing_ok=True)
    interval=max(3600,int(os.environ.get('BACKUP_INTERVAL_SECONDS','86400')))
    existing=sorted(directory.glob('watcher-*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)
    if existing and not force and now-existing[0].stat().st_mtime<interval:
        if not restore_verification_valid(directory,existing[0]):
            _restore_drill(existing[0],directory)
            _record_restore_verification(directory,existing[0])
        return existing[0]
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
        _restore_drill(temporary,directory)
        os.replace(temporary,target)
        target.chmod(0o600)
        _record_restore_verification(directory,target)
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
