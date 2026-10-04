import os
from scripts.backup_daemon import backup_healthy

if not backup_healthy(os.environ.get('BACKUP_DIR','/backups'),check_integrity=True):raise SystemExit(1)
