"""Embed the proxy presentation; load session behavior from the hosted stable SDK."""
import base64
from html import escape
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'site/proxy'


def data_uri(path):
    return 'data:image/svg+xml;base64,' + base64.b64encode(path.read_bytes()).decode()


def country_artwork(countries, flags):
    """Render approved artwork even offline; this snapshot never grants access.

    countries.json contains ranked public country names. Successful SDK config
    replaces the artwork/count and supplies the only selectable country list.
    """
    rows = []
    for row_index in range(3):
        chips = ''.join(
            '<span class="country-chip" role="listitem">'
            f'<img src="{flags[c["code"]]}" alt="" width="18" height="18">'
            f'<span>{escape(c["name"])}</span>'
            f'<span class="country-chip-code" aria-hidden="true">{escape(c["code"].upper())}</span></span>'
            for c in countries[row_index::3])
        label = f'Available countries, row {row_index + 1}'
        group = f'<div class="country-track-group" role="list" aria-label="{label}">{chips}</div>'
        duplicate = f'<div class="country-track-group" role="list" aria-label="{label}" aria-hidden="true">{chips}</div>'
        rows.append(f'<div class="country-row country-row-{row_index + 1}"><div class="country-track">{group}{duplicate}</div></div>')
    rings = []
    offset = 0
    for ring_index, count in enumerate([3, 4, 5]):
        members = countries[offset:offset + count]
        offset += count
        nodes = ''.join(
            f'<div class="orbit-node" style="--angle:{index * 360 / len(members) + [0, 30, 12][ring_index]:g}deg">'
            f'<div class="orbit-flag"><img src="{flags[c["code"]]}" alt="" width="24" height="24"></div></div>'
            for index, c in enumerate(members))
        rings.append(f'<div class="orbit-ring orbit-ring-{ring_index + 1}"><div class="orbit-track">{nodes}</div></div>')
    return ''.join(rows), ''.join(rings)


def proxy_page(logo):
    brand = 'IP Info<span class="brand-divider" aria-hidden="true"></span><span class="by">by</span><span class="shifter-logo" aria-label="Shifter">' + logo + '</span>'
    body = (SOURCE / 'content.html').read_text().replace('__IP_INFO_BRAND__', brand)
    body = body.replace('/assets/flags/us.svg', data_uri(SOURCE / 'flags/us.svg'))
    body = body.replace('/assets/favicon.svg', data_uri(SOURCE / 'shifter-mark.svg'))
    flags = {p.stem: data_uri(p) for p in sorted((SOURCE / 'flags').glob('*.svg'))}
    countries = json.loads((SOURCE / 'countries.json').read_text(encoding='utf-8'))
    rows, rings = country_artwork(countries, flags)
    body = body.replace('__COUNTRY_ROWS__', rows).replace('__COUNTRY_ORBITS__', rings).replace('__COUNTRY_COUNT__', str(len(countries)))
    script = 'const PROXY_FLAGS = ' + json.dumps(flags) + ';\n'
    script += "const flagAsset = code => PROXY_FLAGS[code] || 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22/%3E';\n"
    for filename in ['sdk-loader.js', 'country-order.js', 'country-picker.js', 'country-marquee.js', 'country-orbits.js', 'page-loading.js', 'shifter-reveal.js', 'app.js']:
        source = (SOURCE / filename).read_text()
        source = re.sub(r'^import .*?;\n', '', source, flags=re.M)
        script += source.replace('export ', '') + '\n'
    script = '(async () => {\n' + script + '''})().catch(() => {
      const notice = document.getElementById('notice');
      notice.textContent = 'The web proxy is temporarily unavailable. Please try again shortly.';
      notice.hidden = false;
      document.getElementById('proxy-retry').hidden = false;
      document.getElementById('go').disabled = true;
      document.getElementById('country-trigger').disabled = true;
    });'''
    css = (SOURCE / 'style.css').read_text() + (SOURCE / 'ip-info.css').read_text()
    return body + '<script>' + script + '</script>', '<style>' + css + '</style>'
