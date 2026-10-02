#!/usr/bin/env python3
import argparse, json
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args): return None
opener=build_opener(NoRedirect)
def request(base,path,headers=None):
    try: response=opener.open(Request(base+path,headers=headers or {}),timeout=15)
    except HTTPError as e: response=e
    with response: return response.status,response.headers,response.read()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('base');parser.add_argument('--production',action='store_true');args=parser.parse_args();base=args.base.rstrip('/')
    for ip in ['8.8.8.8','1.1.1.1','2001:4860:4860::8888']:
        status,h,body=request(base,'/json?ip='+ip); data=json.loads(body)
        assert status==200,(status,data);assert data['ip']==ip;assert h['Cache-Control']=='no-store';assert h['X-Robots-Tag']=='noindex'
    assert request(base,'/json?ip=127.0.0.1')[0]==400
    assert request(base,'/readyz')[0]==200
    assert request(base,'/no-such-page')[0]==404
    for path in ['/','/docs','/ai','/about','/terms','/privacy','/cookies','/llms.txt','/llms-full.txt','/openapi.json','/sitemap.xml','/robots.txt','/share.png']:
        assert request(base,path)[0]==200,path
    if args.production:
        status,_,body=request(base,'/json');assert status==200,'Caller detection or HTTP redirect failure';ip=json.loads(body)['ip']
        for header in ['X-Forwarded-For','CDN-Real-IP','X-Real-IP']:
            status,_,body=request(base,'/json',{header:'1.1.1.1'});assert status==200;assert json.loads(body)['ip']==ip,'Spoofable '+header
        _,h,_=request(base,'/');assert h.get('X-Robots-Tag')!='noindex','Production is not indexable'
    print('All smoke checks passed for '+base)
if __name__=='__main__':main()
