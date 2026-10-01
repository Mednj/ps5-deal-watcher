import getpass
import hashlib
import secrets
password=getpass.getpass('New app password (minimum 12 characters): ')
if len(password)<12:raise SystemExit('Use at least 12 characters.')
if password!=getpass.getpass('Repeat password: '):raise SystemExit('Passwords differ.')
salt=secrets.token_bytes(16)
digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()
print("APP_PASSWORD_HASH='scrypt$"+salt.hex()+'$'+digest+"'")
