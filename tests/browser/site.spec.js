const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
test('every page keeps clean search metadata and loads crawlable icons',async({page,request})=>{
  const titles = new Set();
  for (const route of ['/','/docs','/ai','/about','/terms','/privacy','/cookies','/missing/nested-page']) {
    const response = await page.goto(route);
    expect(response.status()).toBe(route.startsWith('/missing') ? 404 : 200);
    expect(await response.text()).not.toMatch(/__cp|cpLocation|\uFFFD/i);
    const title = await page.title();
    expect(title.length).toBeGreaterThan(0);
    expect(titles.has(title)).toBe(false);titles.add(title);
    await expect(page.locator('meta[property="og:title"]')).toHaveAttribute('content',title);
    await expect(page.locator('meta[name="twitter:title"]')).toHaveAttribute('content',title);
    expect(await page.locator('body').innerText()).not.toMatch(/__cp|cpLocation|\uFFFD/i);
    const icons = await page.locator('link[rel="icon"]').evaluateAll(links => links.map(e=>e.getAttribute('href')));
    expect(icons).toEqual(['/favicon.ico','/favicon.png','/favicon.svg']);
    // Exercise the browser's decoders as well as server status/MIME types.
    for (const [url,type] of [['/favicon.ico','image/x-icon'],['/favicon.png','image/png'],['/favicon.svg','image/svg+xml']]) {
      const icon = await request.get(url);
      expect(icon.status()).toBe(200);expect(icon.headers()['content-type']).toBe(type);
      expect(await page.evaluate(async url=>{
        const image=new Image();image.src=url;await image.decode();
        return image.naturalWidth>0 && image.naturalWidth===image.naturalHeight;
      },url)).toBe(true);
    }
  }
});
test('desktop lookup, examples, metadata and navigation',async({page})=>{
  await page.goto('/');
  await expect(page).toHaveTitle('Free IP Geolocation & ASN API — No API Key | IP Info');
  await expect(page.getByRole('heading',{level:1})).toContainText('Free IP geolocation');
  await page.locator('#ip-input').fill('8.8.8.8');
  await page.getByRole('button',{name:'Look up IP',exact:true}).click();
  await expect(page.locator('[data-result="ip"]')).toHaveText('8.8.8.8');
  await expect(page.locator('[data-result="city"]')).toContainText('Mountain View');
  const response=JSON.parse(await page.locator('#result-json').textContent());
  expect(response.asn).toBe(15169); expect(response.postal).toBe('94043');
  await page.getByRole('button',{name:'Rust',exact:true}).click();
  // Native selects are hidden behind custom menus; drive the visible controls.
  await page.locator('button[aria-controls="example-mode-menu"]').click();
  await page.locator('#example-mode-menu').getByRole('option',{name:'Specific IP',exact:true}).click();
  await page.locator('button[aria-controls="example-protocol-menu"]').click();
  await page.locator('#example-protocol-menu').getByRole('option',{name:'HTTP',exact:true}).click();
  await expect(page.locator('#example-code')).toContainText('http://ip-info.com/json?ip=8.8.8.8');
  await page.getByRole('button',{name:'Copy code',exact:true}).click();
  await expect(page.locator('#toast')).toContainText('Copied');
  await page.locator('#ip-input').fill('not-an-ip');
  await page.getByRole('button',{name:'Look up IP',exact:true}).click();
  await expect(page.locator('#lookup-status')).toContainText('literal IPv4');
  await expect(page.locator('#lookup-results')).toBeHidden();
  await page.goto('/docs');
  await expect(page.locator('.field-list').first().locator('dt')).toHaveCount(29);
  await expect(page.locator('link[rel=canonical]')).toHaveAttribute('href','https://ip-info.com/docs');
  expect(await page.locator('script[type="application/ld+json"]').evaluate(e=>JSON.parse(e.textContent)['@graph'].length)).toBe(3);
});
test('mobile layout, keyboard and visual captures',async({page},testInfo)=>{
  await page.setViewportSize({width:1440,height:1040});await page.goto('/');
  await page.screenshot({path:testInfo.outputPath('home-desktop.png'),fullPage:true});
  for (const width of [390,320]) {
    await page.setViewportSize({width,height:844});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:testInfo.outputPath('home-mobile.png'),fullPage:true});
  await page.goto('/docs');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.keyboard.press('Tab'); await expect(page.locator('.skip')).toBeFocused();
  await page.keyboard.press('Enter');
  await page.screenshot({path:testInfo.outputPath('docs-mobile.png'),fullPage:true});
});
test('content and all examples work without JavaScript',async({browser,baseURL})=>{
  const context=await browser.newContext({javaScriptEnabled:false,baseURL});
  const page=await context.newPage();
  await page.goto('/docs');
  await expect(page.getByRole('heading',{name:'The full JSON response'})).toBeVisible();
  const examples=page.locator('.example-static'); await expect(examples).toHaveCount(9);
  await examples.nth(2).locator('summary').click();
  await expect(examples.nth(2).locator('pre').first()).toContainText('https://ip-info.com/json');
  await page.goto('/');
  await page.locator('#ip-input').fill('8.8.8.8');await page.locator('#ip-input').press('Enter');
  await expect(page.locator('body')).toContainText('Mountain View');
  await context.close();
});
test('analytics consent, event sanitization and withdrawal',async({page})=>{
  // Inject a synthetic public measurement ID into a local response, intercept Google
  // before any network access. No events go to a real analytics property.
  const google=[];
  await page.route(/https:\/\/.*(?:googletagmanager|google-analytics)\.com\//,async route=>{
    google.push(route.request().url());
    await route.fulfill({contentType:'text/javascript',body:'/* consent test: no external analytics */'});
  });
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin===new URL(test.info().project.use.baseURL).origin && url.pathname==='/') {
      const response=await route.fetch();
      const body=(await response.text()).replace(/data-ga4="[^"]*"/,'data-ga4="G-TEST12345"');
      return route.fulfill({response,body});
    }
    return route.fallback();
  });
  await page.goto('/?secret=8.8.8.8#private');
  await expect(page.locator('#cookie-panel')).toBeVisible();expect(google).toHaveLength(0);
  await page.getByRole('button',{name:'Reject analytics',exact:true}).click();await page.reload();expect(google).toHaveLength(0);
  await page.getByRole('button',{name:'Cookie preferences',exact:true}).click();
  await page.getByRole('button',{name:'Accept analytics',exact:true}).click();
  await expect.poll(()=>google.length).toBe(1);
  await page.locator('#ip-input').fill('8.8.8.8');await page.getByRole('button',{name:'Look up IP',exact:true}).click();
  await expect(page.locator('[data-result="ip"]')).toHaveText('8.8.8.8');
  const queue=await page.evaluate(()=>Array.from(window.dataLayer,e=>Array.from(e)));
  const text=JSON.stringify(queue);
  for(const secret of ['8.8.8.8','Mountain View','15169','secret=','private','?ip='])expect(text).not.toContain(secret);
  expect(text).toContain('lookup_success');expect(text).toContain('https://ip-info.com/');
  await page.evaluate(()=>document.cookie='_ga=test-cookie; path=/');
  await page.getByRole('button',{name:'Cookie preferences',exact:true}).click();
  await Promise.all([page.waitForEvent('load'),page.getByRole('button',{name:'Reject analytics',exact:true}).click()]);
  expect(google).toHaveLength(1);
  expect(await page.evaluate(()=>document.cookie)).not.toContain('_ga');
  expect(await page.evaluate(()=>document.querySelector('#ga4-loader'))).toBeNull();
});
test('static artifact opens with no external resources',async({page})=>{
  await page.route('https://ip-info.com/json',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":{"message":"Production not deployed."}}'}));
  await page.goto('file://'+path.resolve('web/index.html'));
  await expect(page.getByRole('heading',{level:1})).toContainText('Free IP geolocation');
  await expect(page.locator('#lookup-status')).toContainText('Production not deployed.');
  expect(fs.statSync('web/share.png').size).toBeGreaterThan(1000);
});
test('standalone documentation navigation works without JavaScript',async({browser})=>{
  const context=await browser.newContext({javaScriptEnabled:false});
  const page=await context.newPage();
  await page.goto('file://'+path.resolve('web/index.html'));
  await page.getByRole('link',{name:'Documentation',exact:true}).click();
  await expect(page).toHaveURL(/\/web\/docs\.html$/);
  await expect(page.getByRole('heading',{name:'The full JSON response'})).toBeVisible();
  await page.getByRole('link',{name:'Privacy',exact:true}).click();
  await expect(page.getByRole('heading',{level:1})).toHaveText('Your lookup, explained.');
  await context.close();
});
