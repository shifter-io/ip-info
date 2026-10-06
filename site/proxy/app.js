import {initShifterReveals} from './shifter-reveal.js';
import {renderCountryOrbits} from './country-orbits.js';
import {renderCountryMarquee} from './country-marquee.js';
import {CountryPicker} from './country-picker.js';
initShifterReveals();
document.getElementById('proxy-retry').onclick = () => location.reload();
await loadSharedSdk();
const $ = id => document.getElementById(id);
const countryPicker = new CountryPicker();
const proxy = window.ShifterWebProxy.create({container:$('runtime-host')});
let current = proxy.getState(), configured = false, landingScroll = 0, countriesLoaded = false, loading = false;
function notice(text = '') { $('notice').textContent = text; $('notice').hidden = !text; }
function allowance(id, text) { $(id).textContent = text; $('menu-' + id).textContent = text; }
function browserMode(on) {
  if (on && !document.body.classList.contains('is-browsing')) landingScroll = window.scrollY;
  document.body.classList.toggle('is-browsing', on);
  $('session-menu').open = false;
  $('browser').setAttribute('aria-label', on ? 'Web proxy browser' : 'Start browsing');
  $('resume').hidden = !current.active || on;
  $('go-label').textContent = on ? 'Go' : 'Search';
  $('address').placeholder = on ? 'Website URL' : 'Enter a website URL';
  if (!on) { window.scrollTo(0, landingScroll); $('address').focus({preventScroll:true}); }
  else $('browser').focus({preventScroll:true});
}
const labels = {idle:'Ready to browse', initializing:'Preparing…', ready:'Ready to browse', verifying:'Verify to start browsing', connecting:'Connecting through Shifter…', browsing:'Browsing through Shifter', interrupted:'Connection interrupted', stopped:'Browsing stopped', expired:'Daily allowance ended', exhausted:'Daily allowance ended'};
proxy.subscribe(state => {
  current = state;
  const ended = ['expired','exhausted'].includes(state.status);
  if (state.countries.length && !countriesLoaded) {
    countriesLoaded = true;
    countryPicker.setCountries(state.countries); renderCountryMarquee(state.countries); renderCountryOrbits(state.countries);
    $('country-count').textContent = state.countries.length;
  }
  if (state.active) countryPicker.setValue(state.country);
  if (state.url && document.activeElement !== $('address')) $('address').value = state.url;
  $('status').textContent = labels[state.status] || 'Ready to browse';
  $('session-menu').querySelector('summary').title = $('status').textContent + ' · Session details and browser controls';
  const seconds = state.remainingSeconds || 0;
  allowance('timer',`${Math.floor(seconds/60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`);
  allowance('traffic',`${((state.session?.remainingBytes || 0)/1048576).toFixed(1)} MiB`);
  $('go').disabled = state.busy || !configured;
  countryPicker.setDisabled(state.busy || !configured);
  for (const id of ['back','forward','reload','stop']) $(id).disabled = state.busy || !state.active;
  document.querySelectorAll('[data-browser-action]').forEach(button => { button.disabled = $(button.dataset.browserAction).disabled; });
  $('runtime-host').hidden = !state.active;
  $('empty').hidden = state.active || ended;
  $('expired').hidden = !ended;
  $('resume').hidden = !state.active || document.body.classList.contains('is-browsing');
  // The SDK owns loading deadlines, including silent connection recovery.
  if (state.loading !== loading) {
    loading = state.loading;
    $('page-loading').hidden = !loading;
    $('viewport').setAttribute('aria-busy', String(loading));
  }
  notice(state.error?.message || (state.persistent === false ? 'Browser storage is unavailable. Your session will not be remembered after this page closes.' : ''));
  if (ended) browserMode(true);
});
async function run(action) {
  try { await action(); }
  catch (error) { if (error.code !== 'CANCELLED') notice(error.message); }
}
$('navigate').addEventListener('submit', event => {
  event.preventDefault(); if (current.busy || !configured) return;
  // Release the mobile keyboard before the SDK opens verification.
  $('address').blur();
  run(async () => {
    if (document.body.classList.contains('is-browsing') && current.active) await proxy.navigate($('address').value);
    else await proxy.search({url:$('address').value,country:$('country').value});
    if (current.active) browserMode(true);
  });
});
$('country').addEventListener('change', () => {
  if (!current.active || current.busy) return;
  run(async () => {
    try { await proxy.changeCountry($('country').value); notice('Location changed. You may need to sign in to the website again.'); }
    catch (error) { countryPicker.setValue(current.country); throw error; }
  });
});
for (const command of ['back','forward','reload']) $(command).onclick = () => run(() => proxy[command]());
$('stop').onclick = () => run(async () => {
  await proxy.stop(); countryPicker.setValue('us'); browserMode(false);
});
document.querySelectorAll('[data-browser-action]').forEach(button => {
  button.onclick = () => { $('session-menu').open = false; $(button.dataset.browserAction).click(); };
});
$('home').onclick = () => browserMode(false);
$('expired-home').onclick = () => browserMode(false);
$('resume').onclick = () => browserMode(true);
document.addEventListener('click', event => {
  if (!$('session-menu').contains(event.target)) $('session-menu').open = false;
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && $('session-menu').open) {
    $('session-menu').open = false;
    $('session-menu').querySelector('summary').focus();
  }
});
await proxy.init(); configured = true; $('go').disabled = false; countryPicker.setDisabled(false);
window.addEventListener('pagehide', () => { pageLoading.finish(); proxy.destroy().catch(() => {}); }, {once:true});
window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
