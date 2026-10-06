import {rankCountries} from './country-order.js';

export function renderCountryOrbits(countries) {
  const topCountries = rankCountries(countries).slice(0, 12);
  const artwork = document.getElementById('country-orbits');
  artwork.setAttribute('aria-label', `Shifter connects you to ${topCountries.map(c => c.name).join(', ')}. Three rings of country flags orbit the Shifter logo.`);
  const counts = [3, 4, 5];
  let offset = 0;
  document.getElementById('orbit-rings').replaceChildren(...counts.map((count, ringIndex) => {
    const ring = document.createElement('div');
    ring.className = `orbit-ring orbit-ring-${ringIndex + 1}`;
    const track = document.createElement('div');
    track.className = 'orbit-track';
    const members = topCountries.slice(offset, offset + count);
    offset += count;
    members.forEach((country, index) => {
      const node = document.createElement('div');
      node.className = 'orbit-node';
      node.style.setProperty('--angle', `${index * 360 / members.length + [0, 30, 12][ringIndex]}deg`);
      const badge = document.createElement('div');
      badge.className = 'orbit-flag';
      const flag = document.createElement('img');
      flag.src = flagAsset(country.code);
      flag.alt = ''; flag.width = 24; flag.height = 24;
      badge.append(flag); node.append(badge); track.append(node);
    });
    ring.append(track);
    return ring;
  }));
}
