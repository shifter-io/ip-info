// Fetch the stable hosted loader on every page load. Its release modules are
// immutable; promoting a compatible v1 release needs no IP Info rebuild.
function loadSharedSdk() {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://web.p.shifter.io/sdk/v1/shifter-web-proxy.js';
    script.async = true;
    const timer = setTimeout(() => finish(new Error('SDK load timed out')), 15000);
    function finish(error) {
      clearTimeout(timer);
      script.onload = script.onerror = null;
      if (error) { script.remove(); reject(error); }
      else resolve();
    }
    script.onload = () => finish(window.ShifterWebProxy ? null : new Error('SDK unavailable'));
    script.onerror = () => finish(new Error('SDK unavailable'));
    document.head.append(script);
  });
}
