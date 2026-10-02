from scripts.normal_browser import chromium_command


def test_normal_launch_keeps_debugger_private_and_automation_flags_absent():
    args=chromium_command('/tmp/dedicated-profile',9227)
    assert '--remote-debugging-address=127.0.0.1' in args
    assert '--user-data-dir=/tmp/dedicated-profile' in args
    assert args[-1]=='https://www.leboncoin.fr/'
    assert not any('enable-automation' in arg or 'no-sandbox' in arg for arg in args)


def test_attachment_failure_stops_owned_browser(monkeypatch,tmp_path):
    import pytest
    from types import SimpleNamespace
    import scripts.normal_browser as module
    stopped=[]
    process=SimpleNamespace(poll=lambda:None,terminate=lambda:stopped.append('terminate'),wait=lambda **kw:stopped.append('wait'))
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**kw:process)
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(module.urllib.request,'urlopen',lambda *a,**kw:Response())
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    def fail(*a,**kw):raise RuntimeError('simulated attachment failure')
    fake=SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=fail))
    with pytest.raises(RuntimeError):
        with module.normal_context(fake,tmp_path):pass
    assert stopped==['terminate','wait']
