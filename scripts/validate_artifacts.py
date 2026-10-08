#!/usr/bin/env python3
"""Offline metadata/link/contract checks without external validation services."""
import html, json, re, struct, sys, xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from api_contract import FIELDS, EXAMPLE, openapi
from text_checks import assert_clean_html
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
    for filename in [p.stem for p in sorted(WEB.glob('*.html'))]:
        text=(WEB/(filename+'.html')).read_text(encoding='utf-8'); page=Page(text)
        assert_clean_html(text, filename)
        assert '<meta charset="utf-8">' in text[:1024], (filename, 'early UTF-8 declaration')
        assert not re.search(r'__cp|cpLocation|\ufffd',text,re.I), (filename,'corrupted text')
        matches=re.findall(r'<title>(.*?)</title>',text);assert len(matches)==1
        title=html.unescape(matches[0]);assert title.strip();titles.append(title)
        desc=[a['content'] for t,a in page.tags if t=='meta' and a.get('name')=='description'];assert len(desc)==1;descs+=desc
        for key,expected in [('og:title',title),('twitter:title',title),('og:description',desc[0]),('twitter:description',desc[0])]:
            assert [a['content'] for t,a in page.tags if t=='meta' and (a.get('name')==key or a.get('property')==key)]==[expected],(filename,key)
        def meta(key):
            values=[a.get('content') for t,a in page.tags if t=='meta' and (a.get('name')==key or a.get('property')==key)]
            assert len(values)==1 and values[0], (filename,key)
            return values[0]
        image=meta('og:image'); assert meta('twitter:image')==image
        expected_image='home' if filename in ('index','404') else filename
        assert image==f'https://ip-info.com/meta/{expected_image}.png', (filename,image)
        image_bytes=(WEB/'meta'/f'{expected_image}.png').read_bytes()
        assert image_bytes[:8]==b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II',image_bytes[16:24])==(1200,630), (filename,'social image dimensions')
        assert (meta('og:image:width'),meta('og:image:height'))==('1200','630')
        assert meta('og:image:type')=='image/png'
        assert meta('og:image:alt')==title and meta('twitter:image:alt')==title
        assert meta('twitter:card')=='summary_large_image'
        canonical='https://ip-info.com'+('/' if filename=='index' else '/'+filename)
        assert [a['href'] for t,a in page.tags if t=='link' and a.get('rel')=='canonical']==[canonical]
        assert meta('og:url')==canonical
        icons=[a for t,a in page.tags if t=='link' and a.get('rel')=='icon']
        assert {a['href'] for a in icons}=={'/favicon.ico','/favicon.png','/favicon.svg'},filename
        assert any(a.get('sizes')=='96x96' and a.get('type')=='image/png' for a in icons),filename
        assert [a for t,a in page.tags if t=='link' and a.get('rel')=='apple-touch-icon']==[
            {'rel':'apple-touch-icon','href':'/apple-touch-icon.png','sizes':'180x180'}],filename
        assert [a.get('href') for t,a in page.tags if t=='link' and a.get('rel')=='manifest']==['/site.webmanifest'],filename
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
    urls=ET.fromstring((WEB/'sitemap.xml').read_text());assert len(urls)==8
    docs=(WEB/'docs.html').read_text();full=(WEB/'llms-full.txt').read_text()
    for name,*_ in FIELDS: assert f'<dt>{name}<' in docs;assert f'- {name} (' in full
    assert (WEB/'share.png').read_bytes()[:8]==b'\x89PNG\r\n\x1a\n'
    png=(WEB/'favicon.png').read_bytes()
    assert png[:8]==b'\x89PNG\r\n\x1a\n' and struct.unpack('>II',png[16:24])==(96,96)
    manifest=json.loads((WEB/'site.webmanifest').read_text())
    assert manifest['name']==manifest['short_name']=='IP Info'
    assert manifest['start_url']==manifest['scope']==manifest['id']=='/'
    assert {icon['sizes'] for icon in manifest['icons']}=={'192x192','512x512'}
    for icon in [*manifest['icons'], {'src':'/apple-touch-icon.png','sizes':'180x180','type':'image/png'}]:
        assert icon['type']=='image/png' and icon['src'].startswith('/')
        png=(WEB/icon['src'].lstrip('/')).read_bytes()
        assert png[:8]==b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II',png[16:24])==tuple(map(int,icon['sizes'].split('x')))
    ico=(WEB/'favicon.ico').read_bytes();assert struct.unpack('<HHH',ico[:6])==(0,1,3)
    for i,size in enumerate([16,32,48]):
        width,height,_,_,planes,depth,length,offset=struct.unpack_from('<BBBBHHII',ico,6+i*16)
        assert (width,height,planes,depth)==(size,size,1,32)
        frame=ico[offset:offset+length]
        assert len(frame)==length and frame[:8]==b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II',frame[16:24])==(size,size)
    for output in [*WEB.glob('*.html'), WEB/'openapi.json', WEB/'llms.txt', WEB/'llms-full.txt']:
        assert 'database_date' not in output.read_text(), output
    print(f'Validated {len(titles)} pages, clean metadata, crawlable favicons, internal links/anchors, structured JSON, sitemap, {len(FIELDS)} response fields and OpenAPI consistency.')
if __name__=='__main__':main()
