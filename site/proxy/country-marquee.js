import {rankCountries} from './country-order.js';

export function renderCountryMarquee(countries) {
  const rows = document.getElementById('country-rows');
  const ranked = rankCountries(countries);
  rows.replaceChildren(...Array.from({length:3}, (_, rowIndex) => {
    const row = document.createElement('div');
    row.className = `country-row country-row-${rowIndex + 1}`;
    const track = document.createElement('div');
    track.className = 'country-track';
    const group = document.createElement('div');
    group.className = 'country-track-group';
    group.setAttribute('role','list');
    group.setAttribute('aria-label',`Available countries, row ${rowIndex + 1}`);
    ranked.filter((_, index) => index % 3 === rowIndex).forEach(country => {
      const chip = document.createElement('span');
      chip.className = 'country-chip';
      chip.setAttribute('role','listitem');
      const flag = document.createElement('img');
      flag.src = flagAsset(country.code);
      flag.alt = ''; flag.width = 18; flag.height = 18;
      const name = document.createElement('span'); name.textContent = country.name;
      const code = document.createElement('span'); code.className = 'country-chip-code';
      code.textContent = country.code.toUpperCase(); code.setAttribute('aria-hidden','true');
      chip.append(flag,name,code); group.append(chip);
    });
    const duplicate = group.cloneNode(true);
    duplicate.setAttribute('aria-hidden','true');
    track.append(group,duplicate); row.append(track);
    return row;
  }));
}
