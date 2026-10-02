import re
from fastapi.testclient import TestClient
from app import db
from app.web import app,timestamp
import pytest

def csrf(response):return re.search(r'name="csrf" value="([^"]+)"',response.text).group(1)

def test_pages_empty_and_csrf():
    with TestClient(app) as client:
        for url in ['/','/deals','/sources','/activity','/settings','/import','/watches/new','/health/ready']:
            response=client.get(url);assert response.status_code==200
        assert 'Create your first watch' in client.get('/').text
        assert client.post('/check-now',data={'csrf':'bad'}).status_code==403

def test_watch_crud_secret_redaction_and_untrusted_escape():
    with TestClient(app) as client:
        token=csrf(client.get('/watches/new'))
        form=dict(csrf=token,name='<script>alert(1)</script>',budget='15',qualification='strict',basis='all-in',condition='any',sources=['dealabs','vinted'],delivery='on',pickup='on',centres=['Lyon / Villeurbanne'],radius_km='25',interval_minutes='60',timezone='Europe/Paris',checking_start='00:00',checking_end='00:00',active='on',notify_drops='on')
        assert client.post('/watches/save',data=form).status_code==200
        response=client.get('/')
        assert '&lt;script&gt;' in response.text and '<script>alert(1)</script>' not in response.text
        with db.connect() as conn:wid=conn.execute('SELECT id FROM watches').fetchone()[0]
        assert client.post(f'/watches/{wid}/duplicate',data={'csrf':token}).status_code==200
        assert client.post(f'/watches/{wid}/pause',data={'csrf':token}).status_code==200
        assert client.post(f'/watches/{wid}/resume',data={'csrf':token}).status_code==200
        assert client.post('/settings',data={'csrf':token,'timezone':'Europe/Paris','default_interval':'60','retention_days':'90','telegram_token':'123456:SECRETTEST','telegram_chat':'99999'}).status_code==200
        assert 'SECRETTEST' not in client.get('/settings').text
        assert client.post(f'/watches/{wid}/delete',data={'csrf':token}).status_code==200

def test_nonexistent_dst_time_rejected():
    with pytest.raises(ValueError):timestamp('2026-03-29T02:30','Europe/Paris')
