import argparse
from datetime import datetime, timezone
from app import db
parser=argparse.ArgumentParser();parser.add_argument('destination',nargs='?',default='/data/backups/watcher-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.sqlite3');args=parser.parse_args()
print(db.backup(args.destination))
