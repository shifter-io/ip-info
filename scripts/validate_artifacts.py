#!/usr/bin/env python3
"""Offline metadata/link/contract checks without external validation services."""
import json, re, sys, xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from api_contract import FIELDS, EXAMPLE, openapi
ROOT=Path(__file__).resolve().parents[1]; WEB=ROOT/'web'
class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.tags=[];self.feed(text)
    def handle_starttag(self,tag,attrs):self.tags.append((tag,dict(attrs)))
def main():
    spec=json.loads((WEB/'openapi.json').read_text());assert spec==openapi()
    assert json.loads((ROOT/'tests/example.json').read_text())==EXAMPLE
    assert spec['security']==[]
    known={'/':WEB/'index.html', **{'/'+p.stem:p for p in WEB.glob('*.html')}, **{'/'+p.name:p for p in WEB.iterdir()}}
    known.update({'/json':None,'/healthz':None,'/readyz':None})
    titles=[];descs=[]
    for filename in ['index','docs','ai','about','terms','privacy','cookies']:
        text=(WEB/(filename+'.html')).read_text(); page=Page(text)
        title=re.search(r'<title>(.*?)</title>',text).group(1);titles.append(title)
        desc=[a['content'] for t,a in page.tags if t=='meta' and a.get('name')=='description'];assert len(desc)==1;descs+=desc
        assert sum(1 for t,_ in page.tags if t=='h1')==1
        assert [a for t,a in page.tags if t=='link' and a.get('rel')=='canonical']
        json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',text,re.S).group(1))
        for tag,attrs in page.tags:
            href=attrs.get('href',''); parts=urlsplit(href)
            if href.startswith('/') and not href.startswith('//'):
                assert parts.path in known,(filename,href)
                target=known[parts.path]
                if parts.fragment and target: assert f'id="{parts.fragment}"' in target.read_text(),(filename,href)
            elif href and not parts.scheme and not href.startswith('#'):
                target=WEB/parts.path
                assert target.is_file(),(filename,href)
                if parts.fragment: assert f'id="{parts.fragment}"' in target.read_text(),(filename,href)
        assert '__EXAMPLES__' not in text and '__FAQ__' not in text
    assert len(titles)==len(set(titles));assert len(descs)==len(set(descs))
    urls=ET.fromstring((WEB/'sitemap.xml').read_text());assert len(urls)==7
    docs=(WEB/'docs.html').read_text();full=(WEB/'llms-full.txt').read_text()
    for name,*_ in FIELDS: assert f'<dt>{name}<' in docs;assert f'- {name} (' in full
    assert (WEB/'share.png').read_bytes()[:8]==b'\x89PNG\r\n\x1a\n'
    for output in [*WEB.glob('*.html'), WEB/'openapi.json', WEB/'llms.txt', WEB/'llms-full.txt']:
        assert 'database_date' not in output.read_text(), output
    print(f'Validated 7 pages, internal links/anchors, metadata, structured JSON, sitemap, {len(FIELDS)} response fields and OpenAPI consistency.')
if __name__=='__main__':main()
