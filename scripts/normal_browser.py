"""Launch ordinary Chromium, then attach Playwright through a private CDP port."""
from contextlib import contextmanager
from pathlib import Path
import os
import socket
import subprocess
import tempfile
import time
import urllib.request


def chromium_command(profile,port,url='https://www.leboncoin.fr/'):
    return ['/usr/bin/chromium','--user-data-dir='+str(profile),
            '--no-sandbox',
            '--no-errdialogs','--disable-session-crashed-bubble',
            '--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),
            '--no-first-run','--no-default-browser-check',url]


def chromium_probe(timeout=12):
    """Verify Chromium can launch under the container's actual runtime limits."""
    with tempfile.TemporaryDirectory(prefix='chromium-health-') as profile:
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
        endpoint='http://127.0.0.1:'+str(port)
        process=subprocess.Popen(chromium_command(profile,port,'about:blank'),
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    return False
                try:
                    with urllib.request.urlopen(endpoint+'/json/version',timeout=1):
                        return True
                except Exception:
                    time.sleep(.2)
            return False
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=3)


def clear_stale_profile_lock(profile):
    """Remove Chromium singleton links only when their recorded process is gone."""
    profile=Path(profile)
    lock=profile/'SingletonLock'
    if not lock.is_symlink():
        return
    try:
        host,pid_text=lock.resolve(strict=False).name.rsplit('-',1)
        pid=int(pid_text)
    except (ValueError,OSError):
        return
    if host==socket.gethostname() and Path(f'/proc/{pid}').exists():
        return
    for name in ('SingletonLock','SingletonCookie','SingletonSocket'):
        link=profile/name
        if link.is_symlink():
            link.unlink(missing_ok=True)


@contextmanager
def normal_context(playwright,profile):
    clear_stale_profile_lock(profile)
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    browser=None
    process=subprocess.Popen(chromium_command(profile,port),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+30
        endpoint='http://127.0.0.1:'+str(port)
        while True:
            if process.poll() is not None:raise RuntimeError('Ordinary Chromium exited before attachment')
            try:
                with urllib.request.urlopen(endpoint+'/json/version',timeout=1):pass
                break
            except Exception:
                if time.monotonic()>=deadline:raise RuntimeError('Ordinary Chromium startup timed out')
                time.sleep(.25)
        time.sleep(float(os.environ.get('LEBONCOIN_ATTACH_DELAY','8')))
        browser=playwright.chromium.connect_over_cdp(endpoint,timeout=15000)
        yield browser.contexts[0]
    finally:
        try:
            if browser is not None:browser.close()
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=5)
