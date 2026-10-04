import json
from io import BytesIO
import pytest
from scripts.uptime_probe import probe

class Response(BytesIO):
    def __init__(self,status,body):
        super().__init__(body);self.status=status
    def __enter__(self):return self
    def __exit__(self,*_):self.close()

def test_probe_checks_health_payloads_and_login_page():
    payloads={
        '/health/live':{'status':'ok'},
        '/health/ready':{'database':'ok'},
        '/health/worker':{'worker':'ok'},
        '/login':'<html><title>Sign in · PS5 Deal Watcher</title></html>'.encode(),
    }
    def open_url(request,timeout):
        assert timeout==10
        path=request.full_url.removeprefix('https://watcher.test')
        body=payloads[path]
        if isinstance(body,dict):body=json.dumps(body).encode()
        return Response(200,body)
    results=probe('https://watcher.test/',opener=open_url)
    assert [item['path'] for item in results]==['/health/live','/health/ready','/health/worker','/login']

@pytest.mark.parametrize('bad_path,bad_body',[
    ('/health/live',{'status':'degraded'}),
    ('/health/ready',{'database':'error'}),
    ('/health/worker',{'worker':'stale'}),
])
def test_probe_fails_on_unhealthy_json(bad_path,bad_body):
    healthy={'/health/live':{'status':'ok'},'/health/ready':{'database':'ok'},'/health/worker':{'worker':'ok'}}
    def open_url(request,timeout):
        path=request.full_url.removeprefix('https://watcher.test')
        body=bad_body if path==bad_path else healthy[path]
        return Response(200,json.dumps(body).encode())
    with pytest.raises(RuntimeError):probe('https://watcher.test',opener=open_url)

def test_probe_fails_when_login_page_is_not_served():
    healthy={'/health/live':{'status':'ok'},'/health/ready':{'database':'ok'},'/health/worker':{'worker':'ok'}}
    def open_url(request,timeout):
        path=request.full_url.removeprefix('https://watcher.test')
        body=healthy[path] if path in healthy else b'<html>unexpected</html>'
        if isinstance(body,dict):body=json.dumps(body).encode()
        return Response(200,body)
    with pytest.raises(RuntimeError):probe('https://watcher.test',opener=open_url)
