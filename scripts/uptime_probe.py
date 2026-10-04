"""Check the public app endpoints from an independent runner."""
import json
from html import unescape
import os
import re
import time
from urllib.request import Request,urlopen

JSON_CHECKS={
    '/health/live':('status','ok'),
    '/health/ready':('database','ok'),
    '/health/worker':('worker','ok'),
}

def probe(base_url,timeout=10,opener=None):
    opener=opener or urlopen
    base_url=base_url.rstrip('/')
    results=[]
    checks=[(path,expected) for path,expected in JSON_CHECKS.items()]
    checks.append(('/login',None))
    for path,expected in checks:
        request=Request(base_url+path,headers={'User-Agent':'PS5-Deal-Watcher-Uptime/1.0'})
        started=time.monotonic()
        with opener(request,timeout=timeout) as response:
            status=getattr(response,'status',None)
            if status is None:status=response.getcode()
            body=response.read(1_000_000)
            if status!=200:raise RuntimeError(f'{path} returned HTTP {status}.')
        if expected:
            try:data=json.loads(body)
            except (TypeError,ValueError) as exc:raise RuntimeError(f'{path} returned invalid JSON.') from exc
            if data.get(expected[0])!=expected[1]:raise RuntimeError(f'{path} did not report {expected[0]}={expected[1]}.')
        else:
            html=unescape(body.decode('utf-8',errors='replace'))
            if not re.search(r'<title>\s*sign in\s*[·|]\s*ps5 deal watcher\s*</title>',html,re.I):
                raise RuntimeError('/login did not return the expected sign-in page.')
        results.append({'path':path,'status':200,'milliseconds':round((time.monotonic()-started)*1000)})
    return results

def main():
    base_url=os.environ.get('UPTIME_BASE_URL','https://deals-watcher.yndevs.com')
    for result in probe(base_url):
        print(f"{result['path']} HTTP {result['status']} ({result['milliseconds']} ms)",flush=True)

if __name__=='__main__':main()
