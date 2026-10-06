const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const loader='https://web.p.shifter.io/sdk/v1/shifter-web-proxy.js';
const countries=fs.readdirSync(path.resolve('site/proxy/flags')).filter(f=>f.endsWith('.svg')).map(f=>({code:f.slice(0,-4),name:new Intl.DisplayNames(['en'],{type:'region'}).of(f.slice(0,-4).toUpperCase())}));
async function fixture(page) {
  await page.addInitScript(countries=>{window.proxyCountries=countries;},countries);
  await page.route(loader,route=>route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.resolve('tests/browser/fixtures/proxy-sdk.js'),'utf8')}));
}
async function start(page) {
  await page.locator('#address').fill('example.com');
  await page.locator('#go').click();
  await expect(page.locator('body')).toHaveClass(/is-browsing/);
}
test('Web Proxy keeps shared branding and navigation on desktop and mobile',async({page},info)=>{
  await fixture(page);
  await page.emulateMedia({reducedMotion:'reduce'});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await page.locator('.nav').getByRole('link',{name:'Web Proxy',exact:true}).click();
  await expect(page).toHaveURL(/\/web-proxy$/);
  await expect(page.locator('.nav a[aria-current="page"]')).toHaveText('Web Proxy');
  await expect(page.locator('.site-footer').getByRole('link',{name:'Web Proxy',exact:true})).toHaveAttribute('href','/web-proxy');
  await expect(page.locator('#go')).toBeEnabled();
  await expect(page.locator('#home')).toBeHidden();
  await expect(page.locator('link[rel=canonical]')).toHaveAttribute('href','https://ip-info.com/web-proxy');
  for (const width of [1440,1024,820,768,390,320]) {
    await page.setViewportSize({width,height:950});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width<=1000) {
      expect(await page.locator('#address').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
      await page.locator('#address').fill('example.com');
      await expect(page.locator('#go')).toBeInViewport();
    }
    if(width<=768) {
      await expect(page.locator('.nav')).toBeHidden();
      await page.getByRole('button',{name:'Open menu',exact:true}).click();
    } else await expect(page.locator('.menu-toggle')).toBeHidden();
    await expect(page.locator('.nav').getByRole('link',{name:'Web Proxy',exact:true})).toBeInViewport();
    const boxes=await page.locator('.header-inner > *').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width};}).filter(r=>r.width));
    for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++) {
      const a=boxes[i],b=boxes[j]; expect(a.right<=b.x+1||b.right<=a.x+1||a.bottom<=b.y+1||b.bottom<=a.y+1).toBe(true);
    }
    if([1440,390].includes(width))await page.screenshot({path:info.outputPath(`landing-${width}.png`),fullPage:true});
    if(width<=768) await page.getByRole('button',{name:'Close menu',exact:true}).click();
  }
  expect(errors).toEqual([]);
});
test('SDK controls preserve the session across home, resume, navigation and country changes',async({page},info)=>{
  await fixture(page);await page.goto('/web-proxy');await start(page);
  await expect(page.locator('#home')).toContainText('IP Info');
  await expect(page.locator('#home .by')).toBeVisible();
  await expect(page.locator('#home .shifter-logo')).toBeVisible();
  await expect(page.locator('.site-header')).toBeHidden();
  await page.locator('#address').fill('https://example.org/');await page.locator('#go').click();
  for(const id of ['back','forward','reload'])await page.locator('#'+id).click();
  await page.locator('#country-trigger').click();await page.locator('#country-search').fill('Germany');
  await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
  await expect(page.locator('#country')).toHaveValue('de');
  await page.locator('#home').click();await expect(page.locator('#resume')).toBeVisible();
  await expect(page.locator('.site-header')).toBeVisible();await page.locator('#resume').click();
  await page.evaluate(()=>window.proxyEmit({loading:true}));
  await expect(page.locator('#page-loading')).toBeVisible();await expect(page.locator('#page-loading')).toContainText('IP Info');
  await page.evaluate(()=>window.proxyEmit({loading:false}));
  for (const width of [1440,1024,768,390,320]) {
    await page.setViewportSize({width,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width<=1000) expect(await page.locator('#address').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
    await expect(page.locator('#home')).toBeInViewport();await expect(page.locator('#go')).toBeInViewport();
    await expect(page.locator('#session-menu')).toBeInViewport();
    expect(await page.locator('#address').evaluate(n=>n.getBoundingClientRect().width)).toBeGreaterThan(40);
    if([1440,390].includes(width))await page.screenshot({path:info.outputPath(`browser-${width}.png`)});
  }
  await page.locator('#session-menu summary').click();await page.locator('[data-browser-action="stop"]').click();
  await expect(page.locator('body')).not.toHaveClass(/is-browsing/);
  await expect(page.locator('#runtime-host iframe')).toHaveCount(0);
  expect(await page.evaluate(()=>window.proxyCalls.map(x=>x[0]))).toEqual(['search','navigate','back','forward','reload','changeCountry','stop']);
});
test('cancellation, verification rejection, country rollback and quota expiry stay SDK-driven',async({page})=>{
  await fixture(page);await page.goto('/web-proxy');
  await page.evaluate(()=>window.proxyCancel=true);await page.locator('#address').fill('example.com');await page.locator('#go').click();
  await expect(page.locator('body')).not.toHaveClass(/is-browsing/);await expect(page.locator('#notice')).toBeHidden();
  await page.evaluate(()=>{window.proxyCancel=false;window.proxyReject=true;});await page.locator('#go').click();
  await expect(page.locator('#notice')).toContainText('Verification failed');
  await page.evaluate(()=>window.proxyReject=false);await start(page);
  await page.evaluate(()=>window.proxyCountryFailure=true);
  await page.locator('#country-trigger').click();await page.locator('#country-search').fill('Germany');await page.keyboard.press('Enter');
  await expect(page.locator('#country')).toHaveValue('us');await expect(page.locator('#notice')).toContainText('Location unavailable');
  await page.evaluate(()=>window.proxyEmit({status:'exhausted',active:false,remainingSeconds:0}));
  await expect(page.locator('#expired')).toBeVisible();await expect(page.locator('#runtime-host')).toBeHidden();
  await page.locator('#expired-home').click();await expect(page.locator('.site-header')).toBeVisible();
});
test('blocked hosted loader and configuration fail closed with a retry',async({page})=>{
  await page.route(loader,route=>route.fulfill({status:404,body:''}));
  await page.goto('/web-proxy');
  await expect(page.locator('#notice')).toContainText('temporarily unavailable');
  await expect(page.locator('#country-count')).toHaveText('54');
  await expect(page.locator('.country-track-group:not([aria-hidden]) .country-chip')).toHaveCount(54);
  await expect(page.locator('.orbit-ring')).toHaveCount(3);
  await expect(page.locator('.orbit-flag')).toHaveCount(12);
  await expect(page.locator('#go')).toBeDisabled();await expect(page.locator('#country-trigger')).toBeDisabled();
  await fixture(page);await page.addInitScript(()=>window.proxyInitFailure=true);await page.locator('#proxy-retry').click();
  await expect(page.locator('#notice')).toContainText('temporarily unavailable');await expect(page.locator('#go')).toBeDisabled();
});

test('proxy metadata and readable content are present without JavaScript and its social image decodes',async({browser,baseURL,request})=>{
  const context=await browser.newContext({baseURL,javaScriptEnabled:false});
  const page=await context.newPage();
  const response=await page.goto('/web-proxy');
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toMatch(/text\/html;\s*charset=utf-8/i);
  const title='Free Web Proxy — Browse from Another Country | IP Info';
  const description='Explore websites from another country with IP Info’s free web proxy, powered by Shifter. Choose a location, enter a URL and start browsing.';
  await expect(page).toHaveTitle(title);
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content',description);
  for(const prefix of ['og','twitter']) {
    const attr=prefix==='og'?'property':'name';
    await expect(page.locator(`meta[${attr}="${prefix}:title"]`)).toHaveAttribute('content',title);
    await expect(page.locator(`meta[${attr}="${prefix}:description"]`)).toHaveAttribute('content',description);
    await expect(page.locator(`meta[${attr}="${prefix}:image"]`)).toHaveAttribute('content','https://ip-info.com/meta/web-proxy.png');
    await expect(page.locator(`meta[${attr}="${prefix}:image:alt"]`)).toHaveAttribute('content',title);
  }
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute('href','https://ip-info.com/web-proxy');
  await expect(page.locator('h1')).toHaveCount(1);
  await expect(page.locator('h1')).toContainText('Free web proxy.');
  await expect(page.getByRole('heading',{name:'Your next destination. Three simple steps.'})).toBeVisible();
  await expect(page.locator('#country-count')).toHaveText('54');
  await expect(page.locator('.country-track-group:not([aria-hidden]) .country-chip')).toHaveCount(54);
  await expect(page.locator('.orbit-flag')).toHaveCount(12);
  const text=await page.locator('body').innerText();
  expect(text).not.toMatch(/\uFFFD|[\u0080-\u009f\u200b\ufeff]|Ã[\u0080-\u00bf]|â€|ðŸ|__IP_INFO_BRAND__|__cp|cpLocation/);
  expect(text).toContain('Shifter’s free web proxy');
  const schema=await page.locator('script[type="application/ld+json"]').evaluate(el=>JSON.parse(el.textContent));
  const app=schema['@graph'].find(node=>node['@type']==='WebApplication');
  expect(app).toMatchObject({name:'IP Info Web Proxy',url:'https://ip-info.com/web-proxy',description,image:'https://ip-info.com/meta/web-proxy.png'});
  const image=await request.get('/meta/web-proxy.png');
  expect(image.status()).toBe(200);expect(image.headers()['content-type']).toBe('image/png');
  expect(await page.evaluate(async()=>{const image=new Image();image.src='/meta/web-proxy.png';await image.decode();return [image.naturalWidth,image.naturalHeight];})).toEqual([1200,630]);
  expect(await (await request.get('/sitemap.xml')).text()).toContain('<loc>https://ip-info.com/web-proxy</loc>');
  await context.close();
});


test('approved country artwork animates with the SDK blocked and respects reduced motion',async({page},info)=>{
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.route(loader,route=>route.abort());
  await page.goto('/web-proxy');
  await page.evaluate(()=>document.fonts.ready);
  await expect(page.locator('#country-count')).toHaveText('54');
  await expect(page.locator('.country-track-group:not([aria-hidden]) .country-chip')).toHaveCount(54);
  await expect(page.locator('.country-chip').filter({hasText:'Czech Republic'}).first()).toBeAttached();
  const track=page.locator('.country-track').first();
  const initialTrack=await track.evaluate(el=>getComputedStyle(el).transform);
  await expect.poll(()=>track.evaluate(el=>getComputedStyle(el).transform)).not.toBe(initialTrack);
  await page.locator('.orbit-section').scrollIntoViewIfNeeded();
  const orbit=page.locator('.orbit-track').first();
  const initialOrbit=await orbit.evaluate(el=>getComputedStyle(el).transform);
  await expect.poll(()=>orbit.evaluate(el=>getComputedStyle(el).transform)).not.toBe(initialOrbit);
  await expect(page.locator('.orbit-flag img')).toHaveCount(12);
  expect(await page.locator('.orbit-copy p').first().evaluate(el=>{const s=getComputedStyle(el);return {size:s.fontSize,line:s.lineHeight,margin:s.margin};})).toEqual({size:'14px',line:'25.9px',margin:'14px 0px'});
  expect(await page.locator('#web-proxy').evaluate(el=>getComputedStyle(el).webkitFontSmoothing)).toBe('antialiased');
  await page.locator('.orbit-section').screenshot({path:info.outputPath('approved-orbits.png')});
  await page.emulateMedia({reducedMotion:'reduce'});
  expect(await track.evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
  expect(await orbit.evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
  await expect(page.locator('.orbit-flag')).toHaveCount(12);
});
