// Product display priorities, independent of provider weights and availability.
// Entries absent from the API are never added to the picker.
export const COUNTRY_TIERS = [
  {label: 'Tier 1', codes: [
    'us', 'gb', 'ca', 'de', 'it', 'fr', 'nl', 'es', 'pt',
    'ie', 'ch', 'at', 'be', 'dk', 'se', 'no', 'fi', 'lu', 'is',
    'au', 'nz', 'jp', 'kr', 'sg',
  ]},
  {label: 'Tier 2', codes: [
    'pl', 'cz', 'gr', 'hu', 'ro', 'hr', 'si', 'bg', 'rs', 'ua',
    'ru', 'tr', 'ae', 'sa', 'il', 'tw', 'br', 'mx', 'ar', 'cl',
    'co', 'pe', 'za', 'my', 'th', 'cn', 'kz',
  ]},
  {label: 'Tier 3', codes: []},
];

export function rankCountries(countries) {
  const priorities = new Map(COUNTRY_TIERS.flatMap((group, tier) =>
    group.codes.map((code, order) => [code, {tier: tier + 1, order}])));
  return countries.map(country => ({
    ...country,
    tier: priorities.get(country.code)?.tier ?? 3,
  })).sort((a, b) => a.tier - b.tier ||
    (priorities.get(a.code)?.order ?? 0) - (priorities.get(b.code)?.order ?? 0) ||
    a.name.localeCompare(b.name, 'en'));
}
