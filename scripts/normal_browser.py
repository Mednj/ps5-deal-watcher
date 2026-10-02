"""Launch ordinary Chromium, then attach Playwright through a private CDP port."""
from contextlib import contextmanager
from pathlib import Path
import os
import socket
import subprocess
import tempfile
import time
import urllib.request


def chromium_command(profile,port):
    return ['/usr/bin/chromium','--user-data-dir='+str(profile),
            '--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(port),
            '--no-first-run','--no-default-browser-check','https://www.leboncoin.fr/']


@contextmanager
def normal_context(playwright,profile):
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
    browser=None
    with tempfile.TemporaryFile() as log:
        process=subprocess.Popen(chromium_command(profile,port),stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+20
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
