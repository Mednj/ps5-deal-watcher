import os
import sqlite3
import time
from pathlib import Path

files=sorted(Path(os.environ.get('BACKUP_DIR','/backups')).glob('watcher-*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)
if not files or time.time()-files[0].stat().st_mtime>48*3600:raise SystemExit(1)
with sqlite3.connect(f'file:{files[0].as_posix()}?mode=ro',uri=True) as conn:
    if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit(1)
