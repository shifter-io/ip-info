#!/usr/bin/env python3
"""Rebuild embedded standalone HTML and API artifacts. No third-party packages."""
import html, json, re, subprocess, base64
from pathlib import Path
from api_contract import FIELDS, EXAMPLE, ERRORS, openapi
from examples import EXAMPLES, LANGUAGES
from proxy_page import proxy_page
from text_checks import assert_clean_html

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'; WEB.mkdir(exist_ok=True)
DATE='2026-09-29'
SITE_MODIFIED='2026-10-06'
escape=html.escape
CSS='@font-face{font-family:Geist;src:url(data:font/woff2;base64,'+base64.b64encode((ROOT/'site/geist.woff2').read_bytes()).decode()+') format("woff2");font-weight:100 900;font-display:swap;}'+(ROOT/'site/style.css').read_text()
LOGO=(ROOT/'site/shifter-logo.svg').read_text()
JS=(ROOT/'site/app.js').read_text()
ICON='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="15" fill="#0b1426"/><path d="M23 17 9 32l14 15M41 17l14 15-14 15" fill="none" stroke="#5b9fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="m36 18-8 28" stroke="#fff" stroke-width="4" stroke-linecap="round"/></svg>'
PAGES={
 '/':('Free IP Geolocation & ASN API — No API Key | IP Info','Look up IP location, country, city, ISP and ASN for free. No signup or API key. Built for developers and AI agents. Maintained and supported by Shifter.'),
 '/web-proxy':('Free Web Proxy — Browse from Another Country | IP Info','Explore websites from another country with IP Info’s free web proxy, powered by Shifter. Choose a location, enter a URL and start browsing.'),
 '/docs':('IP Geolocation API Documentation & Examples | IP Info','Integrate the free IP Info API. Explore IPv4 and IPv6 requests, JSON fields, errors and examples in nine languages. No API key required.'),
 '/ai':('Free IP Lookup API for AI Agents | IP Info','Give AI agents public IP geolocation and ASN lookups with no API key. Read OpenAPI, llms.txt and practical integration instructions.'),
 '/about':('About IP Info — Maintained by Shifter','Learn about IP Info, the free IP geolocation and ASN API maintained and supported by Shifter, providing IP location and network data.'),
 '/terms':('Terms of Service | IP Info by Shifter','Terms for the free IP Info API, including automated access, acceptable use, data limitations and service availability.'),
 '/privacy':('Privacy Policy | IP Info by Shifter','How IP Info processes IP lookups, operational information and optional Google Analytics data, and how to contact Shifter about privacy.'),
 '/cookies':('Cookie Policy & Analytics Choices | IP Info','Learn about optional analytics cookies and manage your preferences. IP Info lookups work without analytics consent.'),
}
FAQ=[
 ('Is IP Info really free?', 'Yes. IP Info is free to use, with no signup, API key or subscription. Shifter maintains and supports the service. There is no application quota; service capacity and acceptable-use terms still apply.'),
 ('What can I look up?', 'Public IPv4 and IPv6 addresses. Results include location, country, city, ISP, ASN, organization and network classifications where the database has them. Missing attributes are returned as null.'),
 ('How do I check my proxy location?', 'Make a request to /json through your proxy. It returns the IP seen by our service, which should be the proxy exit. You can also supply a known exit IP with /json?ip=ADDRESS. See the proxy example in the documentation.'),
 ('Can I use HTTP as well as HTTPS?', 'Yes. Both protocols support the same API routes, with no forced HTTP redirect. HTTPS protects the connection. HTTP avoids a TLS handshake, but is not necessarily faster on reused connections.'),
 ('How accurate and fresh is the data?', 'Geolocation is approximate, not a street address or a person’s live location. Data may be incomplete or outdated.'),
 ('Can AI agents use the API?', 'Yes. No authentication flow is needed. An agent can read our OpenAPI schema and llms.txt. A call to /json identifies the agent’s network exit; to check a human user’s IP, the agent must supply that IP explicitly.'),
 ('Is this the same database Shifter uses?', 'This service uses the same IP location and network data source as Shifter. Independently running systems may return different results.'),
 ('Does the API detect VPNs or proxies?', 'No. ASN, ISP, connection type and anycast are database attributes. They should not be treated as proof that an IP is a VPN, proxy or residential connection.'),
]

def code(text, ident=None):
    return '<pre'+(f' id="{ident}"' if ident else '')+'><code>'+escape(text)+'</code></pre>'
def examples_widget():
    options=''.join(f'<option value="{key}">{escape(label)}</option>' for key,label in LANGUAGES.items())
    tabs=''.join(f'<button type="button" data-language="{key}" aria-pressed="{str(key=="curl").lower()}">{escape("Node.js" if key=="javascript" else label)}</button>' for key,label in LANGUAGES.items())
    return '<div class="integration"><div class="language-tabs" role="group" aria-label="Code language" hidden>'+tabs+'</div><pre id="example-code">'+escape(EXAMPLES['curl']['self'])+'</pre><div class="example-toolbar"><div class="example-controls"><label for="example-language">Language <select id="example-language">'+options+'</select></label><label for="example-mode">Lookup <select id="example-mode"><option value="self">My IP</option><option value="custom">Specific IP</option></select></label><label for="example-protocol">Protocol <select id="example-protocol"><option value="https">HTTPS</option><option value="http">HTTP</option></select></label></div><button class="small" data-copy="example-code">Copy code</button></div></div><script id="examples-data" type="application/json">'+json.dumps(EXAMPLES).replace('<','\\u003c')+'</script>'

def document(path, title, desc, body, extra=''):
    meta_image = 'home' if path == '/' or path not in PAGES else path.strip('/')
    nav=''.join(f'<a href="{route}"'+(' aria-current="page"' if path==route else '')+f'>{label}</a>' for route,label in [('/docs','Documentation'),('/web-proxy','Web Proxy'),('/ai','For AI agents'),('/about','About')])
    from urllib.parse import quote
    # Public pages need crawlable favicon URLs; the offline operations guide is self-contained.
    icons = (f'<link rel="icon" href="data:image/svg+xml,{quote(ICON)}">' if path == '/operations' else
             '<link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="16x16 32x32 48x48">'
             '<link rel="icon" href="/favicon.png" type="image/png" sizes="96x96">'
             '<link rel="icon" href="/favicon.svg" type="image/svg+xml" sizes="any">'
             '<link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">'
             '<link rel="manifest" href="/site.webmanifest">')
    structured={'@context':'https://schema.org','@graph':[{'@type':'Organization','@id':'https://shifter.io/#organization','name':'Shifter','url':'https://shifter.io'}, {'@type':'WebSite','@id':'https://ip-info.com/#website','name':'IP Info','url':'https://ip-info.com/','publisher':{'@id':'https://shifter.io/#organization'}}, {'@type':'WebApplication','name':'IP Info','url':'https://ip-info.com/','applicationCategory':'DeveloperApplication','operatingSystem':'Any','isAccessibleForFree':True,'offers':{'@type':'Offer','price':'0','priceCurrency':'USD'},'publisher':{'@id':'https://shifter.io/#organization'}}]}
    if path == '/web-proxy':
        structured['@graph'][-1].update(name='IP Info Web Proxy', url='https://ip-info.com/web-proxy', description=desc, image='https://ip-info.com/meta/web-proxy.png', applicationCategory='UtilitiesApplication')
    output = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><meta name="description" content="{escape(desc)}"><link rel="canonical" href="https://ip-info.com{path}"><meta name="theme-color" content="#080c16"><meta name="referrer" content="no-referrer"><meta property="og:type" content="website"><meta property="og:site_name" content="IP Info"><meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(desc)}"><meta property="og:url" content="https://ip-info.com{path}"><meta property="og:image" content="https://ip-info.com/meta/{meta_image}.png"><meta property="og:image:type" content="image/png"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:alt" content="{escape(title)}"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{escape(title)}"><meta name="twitter:description" content="{escape(desc)}"><meta name="twitter:image" content="https://ip-info.com/meta/{meta_image}.png"><meta name="twitter:image:alt" content="{escape(title)}">{icons}<link rel="alternate" type="application/json" href="/openapi.json" title="OpenAPI specification"><style>{CSS}</style><script type="application/ld+json">{json.dumps(structured)}</script>{extra}</head>
<body data-page="{path}" data-ga4="__GA4_ID__"><a class="skip" href="#main">Skip to content</a><header class="site-header"><div class="wrap header-inner"><a class="brand" href="/" aria-label="IP Info home">IP Info<span class="brand-divider" aria-hidden="true"></span><span class="by">by</span><span class="shifter-logo" aria-label="Shifter">{LOGO}</span></a><button class="menu-toggle" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="main-navigation" hidden><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button><nav id="main-navigation" class="nav" aria-label="Main navigation">{nav}</nav><a class="button primary small header-action" href="/#lookup">Check an IP <span aria-hidden="true">↗</span></a></div></header>
<main id="main">{body}</main>
<footer class="site-footer"><div class="wrap footer-unified"><div class="footer-identity"><a class="brand" href="/">IP Info<span class="brand-divider" aria-hidden="true"></span><span class="shifter-logo" aria-label="Shifter">{LOGO}</span></a><p>Free IP intelligence for the things you build.<br>Maintained and supported by <a href="https://shifter.io">Shifter</a>.</p><small>© 2026 Shifter · IP Info</small></div><nav class="footer-navigation" aria-label="Footer navigation"><div class="footer-links"><a href="/docs">API docs</a><a href="/web-proxy">Web Proxy</a><a href="/ai">AI agents</a><a href="/llms.txt">llms.txt</a><a href="/openapi.json">OpenAPI</a><a href="mailto:hi@shifter.io">Support</a></div><div class="footer-links footer-legal"><a href="/terms">Terms</a><a href="/privacy">Privacy</a><a href="/cookies">Cookies</a><button type="button" data-cookie-preferences>Cookie preferences</button></div></nav></div></footer>
<aside class="cookie-panel" id="cookie-panel" hidden aria-labelledby="cookie-heading"><h2 id="cookie-heading">Your analytics choice</h2><p>May we use Google Analytics to understand website usage? Your IP searches and results are never included in analytics events. The API works either way. <a href="/cookies">Cookie details</a></p><div class="cookie-actions"><button id="cookie-reject" type="button">Reject analytics</button><button id="cookie-accept" type="button">Accept analytics</button></div></aside><div class="toast" id="toast" role="status" hidden></div><script>{JS}</script></body></html>'''

    # Attribute outbound Shifter visits without loading analytics on this site.
    # Apply to real website links only, preserving mailto, schema IDs and API examples.
    def shifter_link(match):
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parts = urlsplit(html.unescape(match.group(2)))
        if parts.scheme not in ('http', 'https') or parts.hostname not in ('shifter.io', 'www.shifter.io'):
            return match.group(0)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(utm_source='ip-info.com', utm_medium='referral', utm_campaign='ip_info', utm_content='home' if path=='/' else path.strip('/'))
        return match.group(1) + escape(urlunsplit(parts._replace(query=urlencode(query))), quote=True) + '"'
    output = re.sub(r'(<a[^>]*href=")([^"]+)"', shifter_link, output)

    # Relative artifact links work when HTML is opened from disk, even without JS.
    # The Rust renderer restores clean canonical links when serving these pages.
    def local_link(match):
        original = match.group(2)
        target, marker, fragment = original.partition('#')
        if target in PAGES:
            filename = 'index.html' if target == '/' else target[1:] + '.html'
        elif target in ['/llms.txt', '/llms-full.txt', '/openapi.json']:
            filename = target[1:]
        else:
            return match.group(0)
        if path == '/operations': filename = '../web/' + filename
        return match.group(1) + filename + (marker + fragment if marker else '') + '"'
    output = re.sub(r'(<a[^>]*href=")([^"]+)"', local_link, output)
    if re.search(r'__cp|cpLocation|\ufffd', output, re.I):
        raise ValueError(f'Corrupted text in generated page: {path}')
    assert_clean_html(output, path)
    return output

def article(eyebrow, title, intro, content):
    return f'<div class="wrap"><header class="page-hero"><p class="eyebrow">{eyebrow}</p><h1>{title}</h1><p class="lead">{intro}</p></header><article class="prose">{content}</article></div>'

def field_reference():
    return '<dl class="field-list">'+''.join(f'<div><dt>{name}<small>{kind}{" | null" if nullable else ""}</small></dt><dd>{escape(desc)}</dd></div>' for name,kind,nullable,_,desc in FIELDS)+'</dl>'

def main():
    rs='// Generated by scripts/generate_site.py from api_contract.py.\n#[derive(Debug, serde::Serialize)]\npub struct LookupResponse {\n'
    for name,kind,nullable,_,_ in FIELDS:
        typ={'string':'String','integer':'u32','number':'f64','boolean':'bool'}[kind]
        rs+=f'    pub {name}: '+(f'Option<{typ}>' if nullable else typ)+',\n'
    (ROOT/'src/response.rs').write_text(rs+'}\n')
    (ROOT/'tests/example.json').write_text(json.dumps(EXAMPLE,indent=2)+'\n')
    (WEB/'openapi.json').write_text(json.dumps(openapi(),indent=2)+'\n')
    (WEB/'favicon.svg').write_text(ICON)
    (WEB/'site.webmanifest').write_text(json.dumps({
        'name': 'IP Info', 'short_name': 'IP Info', 'id': '/',
        'start_url': '/', 'scope': '/', 'display': 'standalone',
        'theme_color': '#080c16', 'background_color': '#080c16',
        'icons': [{'src': f'/android-chrome-{size}x{size}.png',
                   'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'any'}
                  for size in (192, 512)],
    }, indent=2)+'\n')
    content={}
    content['/']=(ROOT/'site/home.html').read_text().replace('__SHIFTER_LOGO__',LOGO).replace('__EXAMPLES__',examples_widget()).replace('__FAQ__',''.join(f'<details><summary>{q}</summary><p>{a}</p></details>' for q,a in FAQ))
    sample=code(json.dumps(EXAMPLE,indent=2),'full-response')
    snippets=''.join(f'<details class="example-static"><summary>{label} — complete examples</summary><h3>Detect caller IP</h3>{code(EXAMPLES[lang]["self"])}<h3>Look up a supplied IP</h3>{code(EXAMPLES[lang]["custom"])}</details>' for lang,label in LANGUAGES.items())
    error_list='<dl class="field-list">'+''.join(f'<div><dt>{status} · {code_}</dt><dd>{desc}</dd></div>' for status,(code_,desc) in ERRORS.items())+'</dl>'
    proxy='curl --fail --max-time 15 \\\n  --proxy http://p.shifter.io:443 \\\n  --proxy-user "customer-USERNAME-country-us-sid-123ABC:PASSWORD" \\\n  https://ip-info.com/json'
    request_examples=code('curl --fail "https://ip-info.com/json"\ncurl --fail "https://ip-info.com/json?ip=8.8.8.8"\ncurl --fail "https://ip-info.com/8.8.8.8/json"\ncurl --fail "https://ip-info.com/json?ip=2001:4860:4860::8888"')
    content['/docs']=article('Developer documentation','Your IP. No credentials.','Everything you need to add IP intelligence to your application.',f'''<nav class="toc" aria-label="On this page"><a href="#requests">Requests</a><a href="#myip">Plain-text IP</a><a href="#response">Response</a><a href="#fields">Fields</a><a href="#examples">Examples</a><a href="#errors">Errors</a><a href="#proxies">Proxies</a></nav>
<div class="callout">Free public access. No signup, API key or application quota. Respect the <a href="/terms">acceptable-use terms</a>; availability depends on service capacity.</div>
<h2 id="requests">Make a request</h2><p>Use <code>GET /json</code> to detect the caller, <code>GET /json?ip=ADDRESS</code> for a supplied address, or <code>GET /ADDRESS/json</code> for the path form. Both IPv4 and IPv6 literals are supported. URL-encode query values.</p>{request_examples}
<p>Replace <code>https://</code> with <code>http://</code> for HTTP access. HTTP is not redirected; HTTPS encrypts the connection. Reused HTTPS connections can avoid a fresh handshake.</p>
<p>JSON lookups accept only public unicast addresses. Private, loopback, multicast, documentation and other special-purpose ranges are rejected. IPv4-mapped IPv6 addresses are normalized to IPv4. Hostnames, duplicate parameters, unknown parameters and conflicting path/query IPs are rejected. Matching path/query values are accepted.</p>
<h2 id="myip">Get only your IP address</h2><p>Use <code>GET /myip</code> for just the visitor’s IPv4 or IPv6 address, followed by a newline, with <code>Content-Type: text/plain; charset=utf-8</code>. No JSON wrapper or geolocation fields are included.</p>{code('curl --fail https://ip-info.com/myip')}{code('8.8.8.8')}<p>The example address is illustrative. This endpoint uses the same trusted-proxy and authenticated-ingress rules as <code>/json</code> and reports the requesting device or proxy’s network exit. Query parameters are ignored and cannot override the caller address. It works without the geolocation database and also returns local/private caller addresses when run locally. IPv4-mapped IPv6 addresses are normalized to IPv4.</p><p>Responses use <code>Cache-Control: no-store</code> and support public cross-origin GET. If the caller cannot be determined or trusted-ingress headers are invalid, the response is HTTP 400 with the standard JSON error body. HEAD returns the same headers with no body.</p>
<h2 id="response">The full JSON response</h2><p>This example illustrates the response format. Live values may differ. Every listed field is present; unavailable values are <code>null</code>.</p>{sample}<button data-copy="full-response">Copy response</button>
<h2 id="fields">Field reference</h2>{field_reference()}
<h2 id="examples">Use your language</h2>{examples_widget()}<p>Complete examples remain available below without JavaScript. The interactive selector also offers HTTP variants.</p>{snippets}
<h2 id="proxies">Verify a Shifter proxy exit</h2><p>Send the caller-detection request through your proxy to see its exit IP and database location. Replace the username and password with your own Shifter credentials; do not put credentials into the IP Info URL.</p>{code(proxy)}<p>Compare <code>country</code> with your requested country code. Different services may report different city or country values.</p>
<h2 id="errors">Errors and retries</h2>{code(json.dumps({'error':{'code':'invalid_ip','message':'Supply a literal IPv4 or IPv6 address.'}},indent=2))}{error_list}<p>Fix 4xx inputs before retrying. For 503/504 or connection failures, use bounded exponential backoff, for example 1, 2 and 4 seconds, then report failure. Low-level malformed HTTP may be rejected before routing.</p>
<h2>Browser access and caching</h2><p>Public GET requests allow cross-origin reads. API responses use <code>Cache-Control: no-store</code>; do not cache visitor-specific responses in shared caches. An HTTPS page must use HTTPS for fetch requests to avoid mixed-content blocking.</p>
<h2>Data limitations</h2><p>Coordinates are approximate. Anycast IPs may be used in many locations. ASN and ISP fields do not establish a person’s identity or prove VPN/proxy status. The first subdivision maps to region and the second to district. English names only are returned. Data may be incomplete or outdated.</p><p>Download the <a href="/openapi.json">OpenAPI 3.1 definition</a> or read the <a href="/llms-full.txt">plain-text reference</a>.</p>''')
    instructions='''Use IP Info for approximate public-IP geolocation and ASN lookup.
Authentication: none. Cost: free.
If an IP is supplied: GET https://ip-info.com/json?ip=<URL-encoded-IP>.
If checking your own execution environment: GET https://ip-info.com/json.
For only your caller IP as plain text: GET https://ip-info.com/myip (address plus newline; no JSON).
Do not describe your server/proxy exit as the human user's IP.
Use country for country-code comparisons and asn for numeric ASN checks.
Treat null as unavailable; never fabricate missing data.
Treat location and network data as approximate and potentially outdated.
Geolocation is approximate. This is not VPN/proxy detection.
Handle JSON errors and use bounded backoff for temporary failures.'''
    content['/ai']=article('For AI agents','IP intelligence without an auth flow.','A simple HTTP tool for assistants, automated checks and agent workflows.',f'''<div class="actions"><a class="button primary" href="/openapi.json">OpenAPI schema</a><a class="button" href="/llms.txt">llms.txt</a><a class="button" href="/llms-full.txt">Full text reference</a></div><h2>Give your agent these instructions</h2>{code(instructions,'agent-instructions')}<button data-copy="agent-instructions">Copy instructions</button><h2>Caller does not mean human user</h2><p>When an agent calls <code>/json</code>, the response describes its runtime or proxy’s network exit. To check another person’s IP, supply an IP they have explicitly provided or your application has legitimately obtained. Do not infer it from the agent’s own connection.</p><h2>Minimal integration</h2>{code(EXAMPLES['python']['custom'])}<h2>Predictable data, clear limitations</h2><p>Responses contain explicit numeric, string, boolean and nullable fields. There are no login pages or API-key exchanges. Handle unavailable fields and preserve uncertainty around location and network classifications.</p><p>The <a href="/docs">human reference</a>, <a href="/openapi.json">OpenAPI schema</a> and text reference are generated from the same response definition. No MCP server is required: ordinary HTTP is sufficient.</p>''')
    content['/about']=article('An open door to IP data','Maintained and supported by Shifter.','IP Info makes useful IP intelligence freely available to developers, customers and AI agents.','''<h2>Why we built IP Info</h2><p>Checking an IP should not require a subscription or an authentication workflow. IP Info gives you a public way to inspect location and network data, including the country information used when validating Shifter proxies.</p><h2>Where the data comes from</h2><p>Lookups use a licensed IP location and network database, the same data source used by Shifter. Different systems may return different results. Database downloads are not offered by this service; the data provider retains its rights in its data.</p><h2>What free means</h2><p>No signup. No API key. No subscription fee or application quota. Automated and commercial application lookups are welcome under the terms. This is a shared service with finite capacity, not an availability guarantee.</p><h2>Contact Shifter</h2><p>For support, data discrepancies, privacy requests or abuse reports, email <a href="mailto:hi@shifter.io">hi@shifter.io</a>. Do not include proxy passwords or other credentials.</p><p>Learn more about <a href="https://shifter.io">Shifter’s proxy network</a>.</p>''')
    content['/terms']=article('Terms of service','Free access. Responsible use.',f'Last updated {DATE}. These terms apply to IP Info at ip-info.com.','''<h2>The service</h2><p>IP Info is maintained and supported by Shifter. Using the website or API means accepting these terms. The service is currently provided without fees, signup or an API key. These terms do not create a paid Shifter subscription.</p><h2>Permitted use</h2><p>You may use the API in applications, scripts and AI agents, including commercial applications, subject to applicable law and these terms. Make requests you need for your application, and handle temporary failures responsibly.</p><h2>Acceptable use</h2><p>Do not disrupt the service, deliberately exhaust capacity, bypass technical protections, use it for unlawful activity, or attempt to obtain credentials or non-public systems. Shifter may restrict abusive traffic or suspend access to protect the service. No application quota does not mean unlimited capacity.</p><h2>Data and third-party rights</h2><p>Location and network information comes from a licensed third-party database. Location is approximate and may be incomplete, outdated or incorrect. It does not identify a person, provide a precise physical address, or establish VPN/proxy status. Rights in the database remain with its owners. API access does not grant a database download, bulk redistribution license, or rights beyond those Shifter can lawfully provide.</p><h2>Availability and reliance</h2><p>The service is provided as available, without an uptime, accuracy or support-response guarantee. Independently verify data before consequential decisions. To the extent permitted by applicable law, Shifter does not provide warranties of accuracy or fitness for a particular purpose and is not responsible for losses resulting from reliance on the data or service interruptions. Nothing here excludes rights or liability that cannot lawfully be excluded.</p><h2>Changes</h2><p>Shifter may change or discontinue the service. Material changes will be described on this site with an updated date. Changes do not authorize charging you without a separate agreement.</p><h2>Privacy and contact</h2><p>See our <a href="/privacy">privacy policy</a> and <a href="/cookies">cookie policy</a>. Contact <a href="mailto:hi@shifter.io">hi@shifter.io</a> for support or questions about these terms.</p>''')
    content['/privacy']=article('Privacy policy','Your lookup, explained.',f'Last updated {DATE}. This policy describes IP Info, maintained and supported by Shifter.','''<h2>Information needed for a lookup</h2><p>To deliver a response, the service receives your network IP address and any IP you supply for lookup. It uses a local IP location and network database to return location and network information. Individual queries are not sent to the data provider. Application request logs are disabled by default; the application does not retain a lookup history.</p><h2>Hosting and operational data</h2><p>Production hosting uses Bunny infrastructure to deliver requests and protect availability. The hosting provider necessarily processes network and request information. Infrastructure processing is separate from application logging and optional website analytics. For questions about infrastructure records and retention, contact Shifter at <a href="mailto:hi@shifter.io">hi@shifter.io</a>. This policy does not claim that no network data is processed.</p><h2>Optional Google Analytics</h2><p>Where enabled, Google Analytics 4 loads only after you accept analytics. It receives sanitized website page views and a small set of interaction events: code copying, language selection, and lookup success or failure. We do not include entered IP addresses, result JSON, returned location or ASN data, query strings, fragments or lookup URLs in analytics events.</p><p>Google receives the network information needed to deliver its script and collect events. Advertising features, Google Signals and User-ID are not used. Rejecting analytics does not affect the API. Our <a href="/cookies">cookie policy</a> explains preferences and withdrawal. See <a href="https://policies.google.com/privacy">Google’s privacy policy</a> for its processing.</p><h2>Support and your choices</h2><p>If you contact Shifter, your message and contact details are processed to address your request. Avoid sending credentials. You may ask about your data, request access or deletion where applicable, or raise a privacy concern at <a href="mailto:hi@shifter.io">hi@shifter.io</a>. Shifter uses this public contact for privacy requests.</p><h2>Retention and security</h2><p>The application keeps no lookup history. Your analytics preference is retained in your browser for up to 180 days, and configured analytics cookies expire after up to 180 days. Support and infrastructure records have separate purposes; contact Shifter for the retention applicable to your request. We use HTTPS for encrypted access when you choose it; HTTP remains available and is not encrypted.</p><h2>Changes</h2><p>Updates will be published here with a revised date. Review this page and your cookie preferences when your needs change.</p>''')
    content['/cookies']=article('Cookie policy','You choose whether analytics runs.',f'Last updated {DATE}. API access never depends on analytics consent.','''<h2>Essential preference storage</h2><p>The website stores your analytics choice in local storage under <code>ipinfo-analytics-consent-v1</code> for up to 180 days. This records your choice, not your IP searches. The API does not require cookies.</p><h2>Optional analytics cookies</h2><p>If Google Analytics is enabled and you accept it, it may set <code>_ga</code> and <code>_ga_*</code> cookies to measure website usage. This integration configures a maximum cookie lifetime of 180 days. No Google analytics script or request is loaded before you accept.</p><h2>Reject or withdraw</h2><p>Use Cookie preferences at any time. Rejecting analytics stops this site’s collection and removes its accessible analytics cookies. If analytics was already running, the page reloads to remove its installed listeners. Previously collected data is not automatically erased by withdrawing consent; contact Shifter about applicable data rights.</p><button type="button" data-cookie-preferences>Open cookie preferences</button><h2>What we measure</h2><p>Sanitized page views, code copying, language selection and lookup success/failure. Entered IPs, returned JSON and lookup URLs are excluded. Read the <a href="/privacy">privacy policy</a> or contact <a href="mailto:hi@shifter.io">hi@shifter.io</a>.</p>''')
    content['/web-proxy'], proxy_extra = proxy_page(LOGO)
    for path,(title,desc) in PAGES.items():
        (WEB/('index.html' if path=='/' else path[1:]+'.html')).write_text(document(path,title,desc,content[path],proxy_extra if path == '/web-proxy' else ''))
    (WEB/'404.html').write_text(document('/404','Page not found | IP Info','This page does not exist.',article('404','Nothing at this address.','The page you requested could not be found.','<p><a class="button primary" href="/">Return to IP Info</a> <a class="button" href="/docs">Read the API docs</a></p>'),'<meta name="robots" content="noindex">'))
    brief='''# IP Info by Shifter

> Free public IP geolocation and ASN API. No signup. No API key. Maintained and supported by Shifter.

Use GET https://ip-info.com/myip for only the caller's IP as plain text (address plus newline). Use GET https://ip-info.com/json for the caller's network exit or GET https://ip-info.com/json?ip=ADDRESS for a public IPv4/IPv6 literal. HTTP is also supported. The caller may be an agent's server or proxy, not its human user. Missing fields are null; locations are approximate. No application quota; acceptable-use terms and finite capacity apply.

## Documentation
- [API reference](https://ip-info.com/docs): Requests, response fields, errors and examples.
- [OpenAPI 3.1](https://ip-info.com/openapi.json): Machine-readable API contract; security is empty.
- [Agent integration](https://ip-info.com/ai): Instructions and caller-IP caveats.
- [Full reference](https://ip-info.com/llms-full.txt): Complete plain-text reference.
- [Data provenance](https://ip-info.com/about): IP location and network data, maintained by Shifter.
- [Terms](https://ip-info.com/terms): Permitted automation and acceptable use.
- [Privacy](https://ip-info.com/privacy): Data processing and optional analytics.
'''
    (WEB/'llms.txt').write_text(brief)
    full=brief+'\n## Agent instructions\n'+instructions+'\n\n## Request routes\nGET /myip (plain-text caller IP plus newline; ignores query parameters; no database required; local/private caller IPs allowed; standard JSON errors)\nGET /json\nGET /json?ip=ADDRESS\nGET /ADDRESS/json\n\nBoth https://ip-info.com and http://ip-info.com are supported. JSON lookups accept literal public IPs only. Private, reserved and special-purpose ranges are rejected. Duplicate/unknown parameters and conflicting path/query targets return 400. IPv4-mapped IPv6 is normalized.\n\n## Full example\n'+json.dumps(EXAMPLE,indent=2)+'\n\n## Response fields\n'
    full+='\n'.join(f'- {n} ({t}{" | null" if null else ""}): {d}' for n,t,null,_,d in FIELDS)
    full+='\n\n## Errors\n'+ '\n'.join(f'{status}: {c} — {d}' for status,(c,d) in ERRORS.items())+'\nError body: {"error":{"code":"invalid_ip","message":"Supply a literal IPv4 or IPv6 address."}}\nAPI responses use Cache-Control: no-store and allow public cross-origin GET. For temporary failures, use bounded exponential backoff. This release does not automatically update daily. Network classifications do not prove VPN/proxy use.\n\n## Code examples\n'
    for lang,label in LANGUAGES.items():
        for mode in ['self','custom']: full+=f'\n### {label}: {mode}\n```\n{EXAMPLES[lang][mode]}\n```\n'
    full+='\n## Shifter proxy exit example\n'+proxy+'\n'
    (WEB/'llms-full.txt').write_text(full)
    (WEB/'robots.txt').write_text('User-agent: *\nAllow: /\nSitemap: https://ip-info.com/sitemap.xml\n')
    (WEB/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>https://ip-info.com{path}</loc><lastmod>{SITE_MODIFIED}</lastmod></url>' for path in PAGES)+'</urlset>\n')
    (ROOT/'docs/operations.html').write_text(document('/operations','IP Info — Build and deployment guide','Local operation, Bunny deployment, validation and launch checks.',(ROOT/'site/operations.html').read_text(),'<meta name="robots" content="noindex">'))
    subprocess.run(['rustfmt', str(ROOT/'src/response.rs')],check=True)
    print('Generated 8 standalone pages, OpenAPI, agent references, sitemap and Rust response type.')

if __name__=='__main__': main()
