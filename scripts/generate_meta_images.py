#!/usr/bin/env python3
"""Render brand-native 1200×630 social images. Requires Pillow, fonttools and brotli."""
from pathlib import Path
from io import BytesIO
import base64, html, math
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
import xml.etree.ElementTree as ET
from fontTools.pens.basePen import BasePen
from fontTools.svgLib.path import parse_path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/meta'; OUT.mkdir(exist_ok=True)
f=TTFont(ROOT/'site/geist.woff2'); f.flavor=None
buf=BytesIO(); f.save(buf); fontdata=buf.getvalue()
def font(size,bold=False):
    result=ImageFont.truetype(BytesIO(fontdata),size)
    try: result.set_variation_by_axes([650 if bold else 400])
    except (OSError,ValueError): pass
    return result
class LogoPen(BasePen):
    def __init__(self, draw, color):
        super().__init__(None); self.draw=draw; self.color=color; self.points=[]
    def _moveTo(self,p): self.points=[p]
    def _lineTo(self,p): self.points.append(p)
    def _curveToOne(self,a,b,c):
        start=self.points[-1]
        for i in range(1,25):
            t=i/24; u=1-t
            self.points.append(tuple(u**3*start[j]+3*u*u*t*a[j]+3*u*t*t*b[j]+t**3*c[j] for j in (0,1)))
    def _closePath(self):
        self.draw.polygon([(x*2,y*2) for x,y in self.points],fill=self.color)
    def _endPath(self): self._closePath()
logo=Image.new('RGBA',(1070,290)); ld=ImageDraw.Draw(logo)
for path in ET.fromstring((ROOT/'site/shifter-logo.svg').read_text()):
    parse_path(path.attrib['d'],LogoPen(ld,path.attrib['fill']))
logo=logo.resize((166,45),Image.Resampling.LANCZOS)

pages=[
('home','FREE IP INTELLIGENCE','Know the IP.','Build the next thing.','Free geolocation and ASN API.','No signup. No API key.','GET /json','200 OK'),
('web-proxy','FREE WEB PROXY','A whole new','perspective.','Choose a country. Enter a website.','Free to use · Powered by Shifter','/web-proxy','EXPLORE THE WEB'),
('docs','DOCUMENTATION','One request.','All the details.','IP location, ISP and ASN in clean JSON.','IPv4 + IPv6 · Examples in 9 languages','GET /json?ip=8.8.8.8','30 FIELDS'),
('ai','BUILT FOR AI AGENTS','IP intelligence.','Ready for your agent.','Ordinary HTTP. Structured JSON.','OpenAPI · llms.txt · No authentication','/llms.txt','AGENT READY'),
('about','ABOUT IP INFO','Free, on us.','Built by Shifter.','Premium IP intelligence. Zero subscription cost.','Maintained and supported by Shifter.','IP Info + Shifter','OUR STORY'),
('terms','TERMS OF SERVICE','Clear terms.','Open access.','The guidelines behind our free IP API.','Automated access · Acceptable use','/terms','SERVICE TERMS'),
('privacy','PRIVACY POLICY','Your data.','Clearly explained.','How IP Info processes information.','IP lookups · Optional analytics · Your choices','/privacy','PRIVACY'),
('cookies','COOKIE PREFERENCES','Your visit.','Your choice.','Optional analytics. You’re in control.','The API works without analytics consent.','/cookies','YOUR CHOICES')]
for slug,tag,line1,line2,desc,note,endpoint,badge in pages:
    im=Image.new('RGB',(1200,630)); pixels=im.load()
    for y in range(630):
        for x in range(1200):
            glow=math.exp(-(((x-1040)/380)**2+((y-350)/380)**2))*0.65
            pixels[x,y]=(int(11+8*glow),int(14+26*glow),int(23+55*glow))
    d=ImageDraw.Draw(im)
    d.text((64,48),'IP Info',font=font(29,True),fill='#fafafa')
    d.text((173,55),'by',font=font(17),fill='#8792a7');im.paste(logo,(210,42),logo)
    d.text((64,156),tag,font=font(15,True),fill='#579cff')
    d.text((60,198),line1,font=font(62,True),fill='#f7f8fa')
    d.text((60,274),line2,font=font(62,True),fill='#2b7fff')
    d.text((64,379),desc,font=font(25),fill='#d1d6df')
    d.text((64,420),note,font=font(21),fill='#929eaf')
    d.rounded_rectangle((64,514,1136,577),radius=14,fill='#131c2c')
    d.text((86,532),endpoint,font=font(20),fill='#e5eaf3')
    box=d.textbbox((0,0),badge,font=font(13,True)); bw=box[2]
    d.ellipse((1097-bw,539,1103-bw,545),fill='#2b7fff')
    d.text((1113-bw,534),badge,font=font(13,True),fill='#8ab8ff')
    d.text((1000,58),'ip-info.com',font=font(18),fill='#929eaf')
    im.save(OUT/f'{slug}.png',optimize=True)
(ROOT/'web/share.png').write_bytes((OUT/'home.png').read_bytes())
items=''.join(f'<article><h2>{html.escape(p[1].title())}</h2><img alt="{html.escape(p[2]+" "+p[3])}" src="data:image/png;base64,{base64.b64encode((OUT/(p[0]+".png")).read_bytes()).decode()}"></article>' for p in pages)
(ROOT/'docs/meta-images.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IP Info — Social preview images</title><style>body{background:#0b0e17;color:#fafafa;font:16px system-ui;margin:40px auto;padding:0 24px;max-width:1300px}h1{font-size:36px}p{color:#9ba5b5}main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px}h2{font-size:17px;font-weight:500}img{width:100%;border-radius:12px}@media(max-width:750px){main{grid-template-columns:1fr}}</style><h1>IP Info. Ready to share.</h1><p>Eight page-specific previews · 1200 × 630 · Shifter branding</p><main>'+items+'</main></html>')
print('Created eight social images and standalone review gallery.')
