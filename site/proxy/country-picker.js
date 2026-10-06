import {rankCountries} from './country-order.js';

// Accessible, searchable country picker using the same circular SVG assets as Shifter.
export class CountryPicker {
  constructor() {
    this.value = document.getElementById('country');
    this.trigger = document.getElementById('country-trigger');
    this.popup = document.getElementById('country-popup');
    this.search = document.getElementById('country-search');
    this.list = document.getElementById('country-options');
    this.countries = [];
    this.filtered = [];
    this.index = -1;
    this.trigger.onclick = () => this.popup.hidden ? this.open() : this.close();
    this.search.oninput = () => this.render();
    this.popup.addEventListener('keydown', event => {
      if (['ArrowDown','ArrowUp','Home','End'].includes(event.key) && (event.target === this.list || event.key.startsWith('Arrow'))) {
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? this.filtered.length - 1 : this.index + (event.key === 'ArrowDown' ? 1 : -1);
        this.highlight(Math.max(0, Math.min(this.filtered.length - 1, next)));
        this.list.focus();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (this.filtered.length) this.choose(this.filtered[Math.max(0,this.index)].code);
      } else if (event.key === 'Escape') {
        event.preventDefault(); event.stopPropagation(); this.close(true);
      }
    });
    this.trigger.addEventListener('keydown', event => {
      if (['ArrowDown','ArrowUp'].includes(event.key)) { event.preventDefault(); this.open(); }
    });
    document.addEventListener('pointerdown', event => {
      if (!document.getElementById('country-picker').contains(event.target)) this.close();
    });
    document.getElementById('country-picker').addEventListener('focusout', () => {
      setTimeout(() => {
        if (!document.getElementById('country-picker').contains(document.activeElement)) this.close();
      },0);
    });
  }
  setCountries(countries) {
    this.countries = rankCountries(countries);
    this.setValue(countries.some(c => c.code === 'us') ? 'us' : countries[0]?.code);
  }
  setValue(code) {
    const country = this.countries.find(c => c.code === code);
    if (!country) return; // A saved session can refer to a country removed from the allowlist.
    this.value.value = code;
    document.getElementById('country-name').textContent = country.name;
    document.getElementById('country-flag').src = flagAsset(code);
    this.render();
  }
  setDisabled(disabled) {
    this.trigger.disabled = disabled;
    if (disabled) this.close();
  }
  open() {
    if (this.trigger.disabled) return;
    this.search.value = '';
    this.popup.hidden = false;
    this.trigger.setAttribute('aria-expanded','true');
    this.render();
    // Keep the popup usable when opened near the bottom of a small viewport.
    const available = window.innerHeight - this.popup.getBoundingClientRect().top - 16;
    this.popup.style.maxHeight = `${Math.max(140, Math.min(350, available))}px`;
    this.search.focus({preventScroll:true});
  }
  close(focus = false) {
    this.popup.hidden = true;
    this.trigger.setAttribute('aria-expanded','false');
    if (focus) this.trigger.focus({preventScroll:true});
  }
  render() {
    const query = this.search.value.trim().toLocaleLowerCase('en');
    this.filtered = this.countries.filter(c => c.name.toLocaleLowerCase('en').includes(query) || c.code.includes(query));
    const groups = [];
    let currentGroup, currentTier;
    for (const country of this.filtered) {
      if (country.tier !== currentTier) {
        currentTier = country.tier;
        currentGroup = document.createElement('div');
        currentGroup.setAttribute('role', 'group');
        currentGroup.setAttribute('aria-labelledby', `country-tier-${currentTier}`);
        const heading = document.createElement('div');
        heading.id = `country-tier-${currentTier}`;
        heading.className = 'country-tier-heading';
        heading.textContent = `Tier ${currentTier}`;
        currentGroup.append(heading);
        groups.push(currentGroup);
      }
      const option = document.createElement('div');
      option.id = `country-option-${country.code}`;
      option.className = 'country-option';
      option.setAttribute('role','option');
      option.setAttribute('aria-selected', String(country.code === this.value.value));
      const flag = document.createElement('img');
      flag.src = flagAsset(country.code); flag.alt = ''; flag.width = 18; flag.height = 18;
      const label = document.createElement('span'); label.textContent = country.name;
      const check = document.createElement('span'); check.className = 'country-check'; check.textContent = '✓'; check.setAttribute('aria-hidden','true');
      option.append(flag,label,check);
      option.onclick = () => this.choose(country.code);
      currentGroup.append(option);
    }
    this.list.replaceChildren(...groups);
    document.getElementById('country-empty').hidden = this.filtered.length !== 0;
    this.index = -1;
    this.list.removeAttribute('aria-activedescendant');
  }
  highlight(index) {
    this.index = index;
    const country = this.filtered[index];
    for (const option of this.list.querySelectorAll('[role=option]')) option.classList.toggle('highlighted', option.id === `country-option-${country?.code}`);
    if (!country) { this.list.removeAttribute('aria-activedescendant'); return; }
    const id = `country-option-${country.code}`;
    this.list.setAttribute('aria-activedescendant',id);
    document.getElementById(id).scrollIntoView({block:'nearest'});
  }
  choose(code) {
    const changed = code !== this.value.value;
    this.setValue(code);
    this.close(true);
    if (changed) this.value.dispatchEvent(new Event('change',{bubbles:true}));
  }
}
