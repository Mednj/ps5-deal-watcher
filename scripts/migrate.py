from app import db
db.init()
with db.connect() as conn:
    version=conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
print('Schema version '+version+' ready. Version 0.1.0 has one idempotent initial migration.')
