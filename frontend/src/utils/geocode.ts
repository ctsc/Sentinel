/**
 * Frontend-side geocoder for events the backend didn't enrich.
 * Small lookup of conflict-relevant locations — keyword matches in the event
 * text resolve to approximate coordinates. Country-center accuracy, not city
 * accuracy; sufficient for visualizing density on a world map.
 */

type Coord = [number, number]; // [lon, lat]

const LOCATIONS: Array<[RegExp, Coord]> = [
  // Middle East
  [/\b(gaza|gaza strip|palestin|hamas|west bank|rafah|khan younis)/i, [34.4, 31.5]],
  [/\b(israel|israeli|tel aviv|jerusalem|idf|netanyahu)/i, [35.0, 31.5]],
  [/\b(lebanon|lebanese|beirut|hezbollah|hizbollah)/i, [35.5, 33.9]],
  [/\b(syria|syrian|damascus|aleppo|idlib|assad)/i, [38.0, 35.0]],
  [/\b(iraq|iraqi|baghdad|mosul|basra|kurdish|kurdistan)/i, [44.4, 33.3]],
  [/\b(iran|iranian|tehran|irgc|persia|persian)/i, [53.7, 32.4]],
  [/\b(yemen|yemeni|sana'a|sanaa|houthi|houthis|aden)/i, [47.5, 15.5]],
  [/\b(saudi|saudi arabia|riyadh|mbs)/i, [45.1, 23.9]],
  [/\b(turkey|turkish|ankara|istanbul|erdogan)/i, [35.2, 39.0]],
  [/\b(jordan|jordanian|amman)/i, [36.2, 31.9]],
  [/\b(qatar|qatari|doha)/i, [51.5, 25.3]],
  [/\b(uae|emirates|dubai|abu dhabi)/i, [54.4, 24.5]],

  // Europe / Ukraine war
  [/\b(ukrain|ukrainian|kyiv|kiev|kharkiv|odessa|odesa|mariupol|donbas|donetsk|luhansk|zelensk)/i, [31.2, 49.0]],
  [/\b(russia|russian|moscow|st\.?\s*petersburg|kremlin|putin|wagner)/i, [37.6, 55.8]],
  [/\b(belarus|minsk)/i, [27.6, 53.9]],
  [/\b(poland|warsaw)/i, [19.1, 52.2]],
  [/\b(germany|berlin)/i, [13.4, 52.5]],
  [/\b(france|paris)/i, [2.3, 48.9]],
  [/\b(united kingdom|britain|london|england|uk\b)/i, [-0.1, 51.5]],
  [/\b(spain|madrid)/i, [-3.7, 40.4]],
  [/\b(italy|rome)/i, [12.5, 41.9]],
  [/\b(greece|athens)/i, [23.7, 37.98]],
  [/\b(serbia|belgrade)/i, [20.5, 44.8]],
  [/\b(kosovo|pristina)/i, [21.2, 42.6]],
  [/\b(moldova|chisinau|transnistria)/i, [28.8, 47.0]],

  // Africa
  [/\b(sudan|khartoum|darfur)/i, [32.5, 15.5]],
  [/\b(south sudan|juba)/i, [31.6, 4.9]],
  [/\b(ethiopia|addis ababa|tigray)/i, [38.7, 9.0]],
  [/\b(somalia|mogadishu|al.shabaab)/i, [45.3, 2.0]],
  [/\b(libya|tripoli|benghazi)/i, [13.2, 32.9]],
  [/\b(egypt|cairo|sinai)/i, [31.2, 30.0]],
  [/\b(nigeria|lagos|abuja|boko haram)/i, [8.7, 9.1]],
  [/\b(mali|bamako|sahel)/i, [-8.0, 17.5]],
  [/\b(burkina faso|ouagadougou)/i, [-1.5, 12.4]],
  [/\b(niger\b|niamey)/i, [2.1, 13.5]],
  [/\b(chad\b|n'djamena)/i, [15.0, 12.1]],
  [/\b(congo|kinshasa|drc|goma)/i, [15.3, -4.3]],
  [/\b(rwanda|kigali)/i, [30.1, -1.9]],
  [/\b(burundi|bujumbura)/i, [29.4, -3.4]],
  [/\b(kenya|nairobi)/i, [36.8, -1.3]],
  [/\b(uganda|kampala)/i, [32.6, 0.3]],
  [/\b(cameroon|yaound)/i, [11.5, 3.9]],
  [/\b(mozambique|maputo)/i, [32.6, -25.9]],
  [/\b(south africa|johannesburg|cape town|pretoria)/i, [28.0, -26.2]],
  [/\b(algeria|algiers)/i, [3.1, 36.8]],
  [/\b(tunisia|tunis)/i, [10.2, 36.8]],
  [/\b(morocco|rabat|casablanca)/i, [-6.8, 34.0]],

  // Asia / Indo-Pacific
  [/\b(china|beijing|shanghai|xinjiang|uyghur|tibet)/i, [116.4, 39.9]],
  [/\b(taiwan|taipei)/i, [121.5, 25.0]],
  [/\b(hong kong)/i, [114.2, 22.3]],
  [/\b(japan|tokyo)/i, [139.7, 35.7]],
  [/\b(korea\b|seoul|pyongyang|north korea|south korea|dprk)/i, [127.0, 37.6]],
  [/\b(vietnam|hanoi)/i, [105.8, 21.0]],
  [/\b(thailand|bangkok)/i, [100.5, 13.8]],
  [/\b(philippines|manila)/i, [121.0, 14.6]],
  [/\b(indonesia|jakarta)/i, [106.8, -6.2]],
  [/\b(malaysia|kuala lumpur)/i, [101.7, 3.1]],
  [/\b(singapore)/i, [103.8, 1.3]],
  [/\b(myanmar|burma|rangoon|yangon|rohingya)/i, [96.1, 16.8]],
  [/\b(india|delhi|mumbai|kashmir)/i, [77.2, 28.6]],
  [/\b(pakistan|islamabad|karachi|lahore)/i, [73.0, 33.7]],
  [/\b(afghanistan|kabul|taliban)/i, [69.2, 34.5]],
  [/\b(bangladesh|dhaka)/i, [90.4, 23.8]],
  [/\b(sri lanka|colombo)/i, [79.9, 6.9]],
  [/\b(nepal|kathmandu)/i, [85.3, 27.7]],

  // Americas
  [/\b(united states|u\.s\.?\b|america|washington|new york|california|texas|florida)/i, [-77.0, 38.9]],
  [/\b(mexico|mexico city|tijuana|cartel)/i, [-99.1, 19.4]],
  [/\b(canada|ottawa|toronto|montreal)/i, [-75.7, 45.4]],
  [/\b(venezuela|caracas|maduro)/i, [-66.9, 10.5]],
  [/\b(colombia|bogota|medellin)/i, [-74.1, 4.7]],
  [/\b(brazil|brasilia|rio de janeiro|sao paulo)/i, [-47.9, -15.8]],
  [/\b(argentina|buenos aires)/i, [-58.4, -34.6]],
  [/\b(chile|santiago)/i, [-70.7, -33.4]],
  [/\b(peru|lima)/i, [-77.0, -12.0]],
  [/\b(haiti|port.au.prince)/i, [-72.3, 18.5]],
  [/\b(cuba|havana)/i, [-82.4, 23.1]],

  // Oceania
  [/\b(australia|sydney|canberra|melbourne)/i, [149.1, -35.3]],
  [/\b(new zealand|wellington)/i, [174.8, -41.3]],
];

// ISO-2 country code → rough center (fallback if regex misses)
const COUNTRY_CENTERS: Record<string, Coord> = {
  US: [-98.6, 39.8], RU: [105.3, 61.5], CN: [104.2, 35.9], IN: [78.9, 20.6],
  BR: [-51.9, -14.2], UA: [31.2, 48.4], IL: [35.0, 31.5], PS: [34.4, 31.5],
  SY: [38.0, 35.0], YE: [47.5, 15.5], IQ: [44.4, 33.3], IR: [53.7, 32.4],
  AF: [69.2, 34.5], PK: [69.3, 30.4], SD: [32.5, 15.5], SO: [45.3, 2.0],
  LY: [18.0, 26.3], ET: [40.5, 9.1], NG: [8.7, 9.1], CD: [21.8, -4.0],
  MM: [96.1, 19.6], VE: [-66.6, 6.4], MX: [-102.6, 23.6], CO: [-74.3, 4.6],
  TR: [35.2, 39.0], LB: [35.5, 33.9], EG: [30.8, 26.8], DZ: [1.7, 28.0],
  MA: [-7.1, 31.8], KR: [127.8, 35.9], JP: [138.3, 36.2], PH: [121.8, 12.9],
  ID: [113.9, -2.5], FR: [2.2, 46.2], DE: [10.5, 51.2], GB: [-3.4, 55.4],
  IT: [12.6, 41.9], ES: [-3.7, 40.5], PL: [19.1, 51.9],
};

/** Augment an event with lat/lon if missing, using text-based lookup. */
export function inferGeo(e: {
  geo?: { lat: number | null; lon: number | null; country_code: string | null; location_name: string | null };
  title?: string | null;
  raw_text?: string;
}): { lat: number | null; lon: number | null } {
  if (e.geo?.lat != null && e.geo?.lon != null) {
    return { lat: e.geo.lat, lon: e.geo.lon };
  }

  const hay = ((e.title ?? "") + " " + (e.raw_text ?? "")).trim();
  if (hay) {
    for (const [pattern, coord] of LOCATIONS) {
      if (pattern.test(hay)) {
        return { lon: coord[0], lat: coord[1] };
      }
    }
  }

  const cc = (e.geo?.country_code ?? "").toUpperCase();
  if (cc && COUNTRY_CENTERS[cc]) {
    const coord = COUNTRY_CENTERS[cc];
    return { lon: coord[0], lat: coord[1] };
  }

  return { lat: null, lon: null };
}
