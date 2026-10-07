#!/usr/bin/env python3
"""Render README.md as standalone docs/readme.html. Requires Markdown (pip install Markdown)."""
import base64
import html
import re
from pathlib import Path
from urllib.parse import urlsplit

import markdown

ROOT = Path(__file__).resolve().parents[1]


def main():
    body = markdown.markdown(
        (ROOT / 'README.md').read_text(),
        extensions=['tables', 'fenced_code', 'toc'],
        extension_configs={'toc': {'permalink': False}},
    )

    def embed_image(match):
        path = ROOT / html.unescape(match[1])
        mime = 'image/svg+xml' if path.suffix == '.svg' else 'image/png'
        return 'src="data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode() + '"'

    body = re.sub(r'src="(docs/assets/[^"]+)"', embed_image, body)

    def repo_link(match):
        href = html.unescape(match[1])
        if href.startswith('#') or urlsplit(href).scheme:
            return match[0]
        # Keep copied HTML useful outside the checkout; documentation/source links
        # resolve to the public repository rather than missing sibling files.
        return 'href="https://github.com/shifter-io/ip-info/blob/main/' + html.escape(href, quote=True) + '"'

    body = re.sub(r'href="([^"]+)"', repo_link, body)
    css = '''
:root{color-scheme:light dark;--bg:#fff;--fg:#1f2937;--muted:#526174;--line:#dce3eb;--code:#f4f7fa;--link:#175cca}
@media(prefers-color-scheme:dark){:root{--bg:#0e1420;--fg:#e3e9f2;--muted:#a6b3c6;--line:#2a374b;--code:#151f30;--link:#79adff}}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1040px;padding:48px 40px 80px;margin:auto}h1,h2,h3{line-height:1.3;letter-spacing:-.025em}h1{font-size:36px;margin:28px 0 14px}h2{font-size:27px;margin:52px 0 20px;padding-bottom:12px;border-bottom:1px solid var(--line)}h3{font-size:20px;margin:30px 0 12px}p{margin:16px 0}a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible{outline:2px solid var(--link);outline-offset:4px}img{max-width:100%;height:auto}p:first-child{margin-top:0}li{margin:7px 0}code{font: .88em/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--code);border-radius:4px;padding:2px 5px}pre{padding:20px 24px;background:var(--code);border:1px solid var(--line);border-radius:10px;overflow:auto}pre code{padding:0;background:none;font-size:14px}table{width:100%;border-collapse:collapse;font-size:15px;margin:24px 0}th,td{border:1px solid var(--line);padding:13px 16px;text-align:left;vertical-align:top}th{background:var(--code);font-weight:600}strong{font-weight:650}footer{border-top:1px solid var(--line);padding-top:24px;margin-top:48px;font-size:13px;color:var(--muted)}
@media(max-width:640px){main{padding:22px 18px 48px}h1{font-size:27px}h2{font-size:23px}table{display:block;overflow:auto}th,td{min-width:140px;padding:10px}pre{padding:16px}}
@media print{main{max-width:none;padding:0}body{font-size:11px}h2{break-after:avoid}pre,table{break-inside:avoid}}
'''
    document = '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>IP Info by Shifter — Free IP Geolocation &amp; ASN API</title>
<meta name="description" content="Free IPv4 and IPv6 geolocation, ASN and ISP lookups for developers and AI agents. No API key. Explore IP Info and Shifter’s Free Web Proxy.">
<style>''' + css + '</style></head><body><main>' + body + '''
<footer>Generated from README.md. Rebuild with <code>python3 scripts/render_readme.py</code>.</footer>
</main></body></html>\n'''
    (ROOT / 'docs/readme.html').write_text(document)
    print('Rendered standalone docs/readme.html')


if __name__ == '__main__':
    main()
