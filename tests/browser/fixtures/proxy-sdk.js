// UI contract fixture only. No CAPTCHA, authorization or proxy traffic is real.
window.proxyCalls = [];
window.ShifterWebProxy = {
  create({container}) {
    const state = {status:'initializing', countries:[], country:'us', active:false, busy:false, loading:false, persistent:true, remainingSeconds:1800, session:{remainingBytes:104857600}};
    const listeners = [];
    function emit(patch = {}) { Object.assign(state,patch); listeners.forEach(fn => fn(structuredClone(state))); }
    window.proxyEmit = emit;
    function record(method, value) { window.proxyCalls.push([method, value]); }
    return {
      getState: () => structuredClone(state),
      subscribe(fn) { listeners.push(fn); fn(structuredClone(state)); return () => {}; },
      async init() {
        if (window.proxyInitFailure) throw new Error('Configuration unavailable');
        emit({status:'ready', countries:window.proxyCountries});
      },
      async search(value) {
        record('search',value);
        emit({status:'verifying',busy:true});
        if (window.proxyCancel) { emit({status:'ready',busy:false}); throw Object.assign(new Error('Cancelled'),{code:'CANCELLED'}); }
        if (window.proxyReject) { emit({status:'ready',busy:false}); throw new Error('Verification failed. Please try again.'); }
        const url = new URL(value.url.includes('://') ? value.url : 'https://'+value.url).href;
        const frame = document.createElement('iframe');
        frame.style.cssText = 'border:0;width:100%;height:100%;display:block';
        frame.title = 'SDK fixture destination'; frame.srcdoc = '<h1>Destination fixture</h1>';
        container.replaceChildren(frame);
        emit({status:'browsing',busy:false,active:true,url,country:value.country});
      },
      async navigate(url) { record('navigate',url); emit({url}); },
      async back() { record('back'); },
      async forward() { record('forward'); },
      async reload() { record('reload'); },
      async changeCountry(country) {
        record('changeCountry',country);
        if (window.proxyCountryFailure) throw new Error('Location unavailable');
        emit({country});
      },
      async stop() { record('stop'); container.replaceChildren(); emit({active:false,status:'stopped'}); },
      async destroy() { record('destroy'); container.replaceChildren(); }
    };
  }
};
