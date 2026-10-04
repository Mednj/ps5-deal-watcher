import argparse
import sqlite3
from pathlib import Path
from app import db
parser=argparse.ArgumentParser(description='Run only while both services are stopped.');parser.add_argument('backup');parser.add_argument('--confirm-replace',action='store_true');args=parser.parse_args()
if not args.confirm_replace:raise SystemExit('Restore replaces the app database. Pass --confirm-replace after stopping both services.')
source=Path(args.backup).resolve();target=db.path().resolve()
if source==target or not source.is_file():raise SystemExit('Choose a separate existing backup file.')
with sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True) as incoming:
    if incoming.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Backup integrity check failed.')
    version=incoming.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
    if not version or version[0] not in ('1','2'):raise SystemExit('Unsupported schema version.')
    if target.exists():db.backup(target.parent/'pre-restore.sqlite3')
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(target) as destination:incoming.backup(destination)
print(f'Restored schema version {version[0]}. Keep the pre-restore backup until verification is complete.')
