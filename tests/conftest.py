import os
import tempfile
os.environ['DATA_DIR']=tempfile.mkdtemp(prefix='watcher-tests-')
import pytest
from app import db

@pytest.fixture(autouse=True)
def isolated_database(tmp_path,monkeypatch):
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN',raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID',raising=False)
    monkeypatch.delenv('APP_PASSWORD_HASH',raising=False)
    monkeypatch.setenv('APP_AUTH_DISABLED_FOR_TESTS','1')
    db.init()
