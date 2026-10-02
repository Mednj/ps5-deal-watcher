import os
import sqlite3
import subprocess
import sys
from scripts.backup_daemon import backup_once
from app import db

def test_atomic_backup_rotation_and_restore(tmp_path,monkeypatch):
    backup_dir=tmp_path/'snapshots'
    monkeypatch.setenv('BACKUP_DIR',str(backup_dir))
    monkeypatch.setenv('BACKUP_RETAIN_COUNT','2')
    monkeypatch.setenv('BACKUP_INTERVAL_SECONDS','3600')
    with db.connect() as conn:db.setting(conn,'backup_test','state-before-backup')
    first=backup_once(force=True)
    snapshot=sqlite3.connect(first)
    try:
        assert snapshot.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert snapshot.execute("SELECT value FROM settings WHERE key='backup_test'").fetchone()[0]=='state-before-backup'
    finally:snapshot.close()
    assert backup_once()==first
    for offset in (1,2):backup_once(force=True,now=1700000000+offset)
    backups=list(backup_dir.glob('watcher-*.sqlite3'))
    assert len(backups)==2
    restorable=max(backups,key=lambda p:p.stat().st_mtime)
    restore_dir=tmp_path/'restore-data';env=os.environ.copy();env['DATA_DIR']=str(restore_dir)
    result=subprocess.run([sys.executable,'-m','scripts.restore',str(restorable),'--confirm-replace'],
                          env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    restored=sqlite3.connect(restore_dir/'watcher.sqlite3')
    try:
        assert restored.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert restored.execute("SELECT value FROM settings WHERE key='backup_test'").fetchone()[0]=='state-before-backup'
    finally:restored.close()
    assert not list(backup_dir.glob('*.partial'))
