(() => {
  'use strict';
  const $ = (q) => document.querySelector(q);
  const storageKey = 'ipinfo-analytics-consent-v1';
  const measurement = document.body.dataset.ga4 || '';
  const hasAnalytics = /^G-[A-Z0-9]{4,22}$/.test(measurement);
  const allowedPages = new Set(['/', '/docs', '/ai', '/about', '/terms', '/privacy', '/cookies']);
  const canonicalPath = allowedPages.has(document.body.dataset.page) ? document.body.dataset.page : '/';
  let consent = 'denied', gaLoaded = false;
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey));
    if (stored && stored.expires > Date.now()) consent = stored.value;
    else consent = 'unset';
  } catch (_) { consent = 'unset'; }
  const panel = $('#cookie-panel');
  function toast(message) {
    const el = $('#toast'); if (!el) return;
    el.textContent = message; el.hidden = false;
    clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, 3500);
  }
  function event(name, params = {}) {
    if (!hasAnalytics || consent !== 'granted' || !gaLoaded) return;
    if (!['code_copy','language_select','lookup_success','lookup_failure'].includes(name)) return;
    const safe = {};
    if (['curl','javascript','python','php','go','rust','java','csharp','ruby'].includes(params.language)) safe.language = params.language;
    if (['self','custom'].includes(params.mode)) safe.mode = params.mode;
    window.gtag('event', name, safe);
  }
  function startAnalytics() {
    if (!hasAnalytics || consent !== 'granted' || gaLoaded) return;
    gaLoaded = true;
    window['ga-disable-' + measurement] = false;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', {analytics_storage:'granted', ad_storage:'denied', ad_user_data:'denied', ad_personalization:'denied'});
    window.gtag('set', {allow_google_signals:false, allow_ad_personalization_signals:false, ads_data_redaction:true});
    window.gtag('js', new Date());
    window.gtag('config', measurement, {
      send_page_view:false, allow_google_signals:false, allow_ad_personalization_signals:false,
      page_location:'https://ip-info.com' + canonicalPath, page_referrer:'', page_title:document.title,
      cookie_expires:60*60*24*180, cookie_update:false
    });
    window.gtag('event','page_view',{page_location:'https://ip-info.com' + canonicalPath,page_referrer:'',page_title:document.title});
    const script = document.createElement('script'); script.async = true;
    script.id = 'ga4-loader'; script.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(measurement);
    document.head.appendChild(script);
  }
  function clearAnalyticsCookies() {
    const names = document.cookie.split(';').map(v => v.trim().split('=')[0]).filter(n => /^_ga(?:_|$)|^_gid$|^_gat/.test(n));
    const host = location.hostname.split('.');
    const domains = ['', location.hostname, '.'+location.hostname];
    for (let i=1;i<host.length-1;i++) domains.push('.'+host.slice(i).join('.'));
    for (const name of names) for (const domain of domains) {
      document.cookie = name+'=; Max-Age=0; path=/'+(domain?'; domain='+domain:'');
    }
  }
  function choose(value) {
    const wasLoaded = gaLoaded;
    consent = value;
    try { localStorage.setItem(storageKey,JSON.stringify({value,expires:Date.now()+180*86400000})); } catch (_) {}
    panel.hidden = true;
    if (value === 'granted') startAnalytics();
    else {
      window['ga-disable-' + measurement] = true;
      clearAnalyticsCookies();
      $('#ga4-loader')?.remove();
      window.dataLayer = []; gaLoaded = false;
      // A full reload removes every listener installed by Google's external script.
      // Persisted denial prevents it being loaded on the next document.
      if (wasLoaded) location.reload();
    }
    toast(value === 'granted' ? 'Analytics enabled.' : 'Analytics disabled. Your lookup still works.');
  }
  document.querySelectorAll('[data-cookie-preferences]').forEach(el => el.addEventListener('click', () => {
    if (!hasAnalytics) { toast('Analytics is not enabled on this site.'); return; }
    panel.hidden = false; $('#cookie-reject').focus();
  }));
  $('#cookie-accept')?.addEventListener('click',()=>choose('granted'));
  $('#cookie-reject')?.addEventListener('click',()=>choose('denied'));
  if (hasAnalytics && consent === 'unset') panel.hidden = false;
  if (hasAnalytics && consent === 'granted') startAnalytics();
  if (consent !== 'granted') clearAnalyticsCookies();

  const base = location.protocol === 'file:' ? 'https://ip-info.com' : location.origin;
  let lookupController;
  async function lookup(ip) {
    lookupController?.abort(); lookupController = new AbortController();
    const controller = lookupController;
    const status = $('#lookup-status'); const mode = ip ? 'custom' : 'self';
    status.hidden = false; status.classList.remove('error'); status.textContent = ip ? 'Looking up this IP…' : 'Checking your network exit…';
    $('#lookup-submit').disabled = true;
    $('#lookup-results').hidden = true;
    const timer = setTimeout(()=>controller.abort(),10000);
    try {
      const response = await fetch(base+'/json'+(ip ? '?ip='+encodeURIComponent(ip) : ''),{cache:'no-store',credentials:'omit',signal:controller.signal});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'Lookup is temporarily unavailable.');
      if (!ip && !$('#ip-input').value.trim()) $('#ip-input').value = result.ip;
      const values = {ip:result.ip,country:[result.country_name,result.country].filter(Boolean).join(' · '),city:[result.city,result.region].filter(Boolean).join(', '),asn:result.asn ? 'AS'+result.asn : null,isp:result.isp,timezone:result.timezone};
      for (const [key,value] of Object.entries(values)) $('[data-result="'+key+'"]').textContent = value ?? 'Not available';
      $('#result-json').textContent = JSON.stringify(result,null,2);
      $('.json-box').classList.remove('expanded');
      $('#json-expand').setAttribute('aria-expanded','false');
      $('#json-expand').textContent = 'View full JSON ↓';
      $('#lookup-results').hidden = false;
      status.textContent = ''; status.hidden = true;
      event('lookup_success',{mode});
    } catch (err) {
      if (lookupController !== controller) return;
      status.classList.add('error');
      status.textContent = err.name === 'AbortError' ? 'The lookup timed out. Please try again.' : (err instanceof TypeError ? 'Unable to reach the API. Try again or open /json directly.' : err.message);
      if (!ip && /public unicast/.test(status.textContent)) status.textContent = 'You are viewing a local preview. Enter a public IP to try the live database.';
      event('lookup_failure',{mode});
    } finally {
      clearTimeout(timer);
      if (lookupController === controller) { $('#lookup-submit').disabled = false; }
    }
  }
  $('#lookup-form')?.addEventListener('submit',e=>{e.preventDefault();lookup($('#ip-input').value.trim());});
  if ($('#lookup-form')) {
    const localPreview = ['localhost', '127.0.0.1', '[::1]', '::1'].includes(location.hostname);
    if (localPreview) $('#ip-input').value = '8.8.8.8';
    lookup(localPreview ? '8.8.8.8' : '');
  }
  const examples = $('#examples-data') ? JSON.parse($('#examples-data').textContent) : null;
  function renderExample() {
    if (!examples) return;
    const lang=$('#example-language').value, mode=$('#example-mode').value, protocol=$('#example-protocol').value;
    $('#example-code').textContent=examples[lang][mode].replaceAll('https://ip-info.com',protocol+'://ip-info.com');
  }
  for (const id of ['example-language','example-mode','example-protocol']) $('#'+id)?.addEventListener('change',()=>{renderExample();if(id==='example-language')event('language_select',{language:$('#example-language').value});});
  const languageTabs = $('.language-tabs');
  if (languageTabs) {
    languageTabs.hidden = false;
    const languageLabel = $('#example-language').closest('label');
    languageLabel.hidden = true;
    document.querySelectorAll('[data-language]').forEach(button => button.addEventListener('click', () => {
      $('#example-language').value = button.dataset.language;
      document.querySelectorAll('[data-language]').forEach(tab => tab.setAttribute('aria-pressed', String(tab === button)));
      renderExample(); event('language_select', {language:button.dataset.language});
    }));
  }
  // Custom menus keep native selects as the value source and no-JS fallback.
  for (const id of ['example-mode','example-protocol']) {
    const select = $('#'+id); if (!select) continue;
    const label = select.closest('label');
    const wrapper = document.createElement('div'); wrapper.className='custom-select';
    const trigger = document.createElement('button'); trigger.type='button'; trigger.className='select-trigger';
    trigger.setAttribute('aria-haspopup','listbox'); trigger.setAttribute('aria-expanded','false');
    const menu = document.createElement('div'); menu.className='select-menu'; menu.id=id+'-menu'; menu.hidden=true;
    menu.setAttribute('role','listbox'); menu.setAttribute('aria-label',id==='example-mode'?'Lookup mode':'Protocol');
    trigger.setAttribute('aria-controls',menu.id);
    const options = [...select.options].map(option=>{
      const button=document.createElement('button'); button.type='button'; button.setAttribute('role','option'); button.textContent=option.textContent;
      button.addEventListener('click',()=>{select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));sync();close();trigger.focus();});
      menu.append(button); return button;
    });
    function sync(){trigger.textContent=select.selectedOptions[0].textContent;trigger.setAttribute('aria-label',(id==='example-mode'?'Lookup: ':'Protocol: ')+trigger.textContent);options.forEach((button,index)=>button.setAttribute('aria-selected',String(select.options[index].selected)));}
    function close(){menu.hidden=true;trigger.setAttribute('aria-expanded','false');}
    function open(){menu.hidden=false;trigger.setAttribute('aria-expanded','true');options[select.selectedIndex].focus();}
    trigger.addEventListener('click',()=>menu.hidden?open():close());
    trigger.addEventListener('keydown',e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open();}});
    menu.addEventListener('keydown',e=>{const i=options.indexOf(document.activeElement);if(e.key==='Escape'){e.preventDefault();close();trigger.focus();}else if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?options.length-1:(i+(e.key==='ArrowDown'?1:-1)+options.length)%options.length;options[n].focus();}});
    wrapper.addEventListener('focusout',e=>{if(!wrapper.contains(e.relatedTarget))close();});
    document.addEventListener('click',e=>{if(!wrapper.contains(e.target))close();});
    select.addEventListener('change',sync);
    select.hidden=true;label.removeAttribute('for');
    wrapper.append(trigger,menu);label.append(wrapper);sync();
  }
  renderExample();
  $('#json-expand')?.addEventListener('click', () => {
    const expanded = $('#json-expand').getAttribute('aria-expanded') !== 'true';
    $('.json-box').classList.toggle('expanded', expanded);
    $('#json-expand').setAttribute('aria-expanded', String(expanded));
    $('#json-expand').textContent = expanded ? 'Show less ↑' : 'View full JSON ↓';
  });
  document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
    const source=$('#'+button.dataset.copy); if(!source)return;
    try {
      if(navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(source.textContent);
      else {const area=document.createElement('textarea');area.value=source.textContent;area.style.position='fixed';area.style.left='-9999px';document.body.append(area);area.select();const copied=document.execCommand('copy');area.remove();if(!copied)throw new Error('copy');}
      if (button.classList.contains('json-copy')) {
        clearTimeout(button.copyTimer);
        button.classList.add('copied'); button.setAttribute('aria-label','JSON copied'); button.title='Copied!';
        button.copyTimer=setTimeout(()=>{button.classList.remove('copied');button.setAttribute('aria-label','Copy JSON');button.title='Copy JSON';},2000);
      }
      toast('Copied to clipboard.'); event('code_copy');
    } catch (_) {toast('Select the code and copy it manually.');}
  }));

  // Shifter's scroll threshold, reveal distance, duration and easing, without React.
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const syncHeader = () => document.querySelector('.site-header').classList.toggle('scrolled', scrollY > 10);
  addEventListener('scroll', syncHeader, {passive:true}); syncHeader();
  if (!reducedMotion.matches && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.remove('reveal-pending'); observer.unobserve(entry.target); }
    }), {rootMargin:'-50px'});
    document.querySelectorAll('.center-heading,.feature,.integration-copy,.agent-banner,.faq-section,.closing-section').forEach(el => {
      if (el.getBoundingClientRect().top >= innerHeight) {
        el.classList.add('scroll-reveal','reveal-pending'); observer.observe(el);
      }
    });
    // Keyboard navigation and fragment links must never focus invisible content.
    document.addEventListener('focusin', e => e.target.closest('.reveal-pending')?.classList.remove('reveal-pending'));
    reducedMotion.addEventListener('change', () => {
      if (reducedMotion.matches) { observer.disconnect(); document.querySelectorAll('.reveal-pending').forEach(el=>el.classList.remove('reveal-pending')); }
    });
  }
  // Typing cadence follows Shifter's hero: 40ms erase, 80ms type, 2s hold.
  const audience = $('#audience');
  if (audience && !reducedMotion.matches) {
    const words = ['developers.', 'your team.', 'AI agents.'];
    let index=0, count=words[0].length, deleting=true;
    const tick = () => {
      if (reducedMotion.matches) { audience.textContent=words[0]; return; }
      if (document.hidden) { setTimeout(tick,2000); return; }
      count += deleting ? -1 : 1;
      audience.textContent=words[index].slice(0,count);
      let delay=deleting?40:80;
      if (count===0) { deleting=false; index=(index+1)%words.length; delay=300; }
      else if(count===words[index].length) { deleting=true; delay=2000; }
      setTimeout(tick,delay);
    };
    setTimeout(tick,2000);
  }
})();
