"""Initialize only the backup mount, then drop to the unprivileged app UID."""
import os
import sys

if os.geteuid()==0:
    target='/backups'
    if os.stat(target).st_uid!=10001:
        os.chmod(target,0o700)
        os.chown(target,10001,10001)
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
    os.chmod(target,0o700)
if len(sys.argv)<2:raise SystemExit('Backup command is required.')
os.execvp(sys.argv[1],sys.argv[1:])
