// Official primary colors for all 30 NBA teams, keyed by tricode.
const TEAM_COLORS = {
  ATL: '#E03A3E', // Hawks red
  BOS: '#007A33', // Celtics green
  BKN: '#FFFFFF', // Nets white
  CHA: '#1D1160', // Hornets purple
  CHI: '#CE1141', // Bulls red
  CLE: '#860038', // Cavaliers wine
  DAL: '#00538C', // Mavericks blue
  DEN: '#0E2240', // Nuggets navy
  DET: '#C8102E', // Pistons red
  GSW: '#FFC72C', // Warriors gold
  HOU: '#CE1141', // Rockets red
  IND: '#002D62', // Pacers navy
  LAC: '#C8102E', // Clippers red
  LAL: '#552583', // Lakers purple
  MEM: '#5D76A9', // Grizzlies blue
  MIA: '#98002E', // Heat red
  MIL: '#00471B', // Bucks green
  MIN: '#0C2340', // Timberwolves navy
  NOP: '#0C2340', // Pelicans navy
  NYK: '#F58426', // Knicks orange
  OKC: '#007AC1', // Thunder blue
  ORL: '#0077C0', // Magic blue
  PHI: '#006BB6', // 76ers blue
  PHX: '#1D1160', // Suns purple
  POR: '#E03A3E', // Blazers red
  SAC: '#5A2D81', // Kings purple
  SAS: '#C4CED4', // Spurs silver
  TOR: '#CE1141', // Raptors red
  UTA: '#002B5C', // Jazz navy
  WAS: '#002B5C', // Wizards navy
};

// Perceived brightness via standard luminance formula (0 = black, 255 = white).
function brightness(hex) {
  const clean = hex.replace('#', '');
  const r = parseInt(clean.slice(0, 2), 16);
  const g = parseInt(clean.slice(2, 4), 16);
  const b = parseInt(clean.slice(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

const FALLBACK_DARK = '#4B5563';
const FALLBACK_LIGHT = '#9CA3AF';

/**
 * Given two team tricodes, return { awayColor, homeColor } such that
 * the brighter color goes to the away team and the darker to home
 * (or vice-versa if home is brighter), always guaranteeing contrast.
 *
 * On a dark background, very dark colors are hard to read, so we clamp
 * anything with brightness < 40 to a lighter fallback.
 */
export function getMatchupColors(awayTricode, homeTricode) {
  const awayHex = TEAM_COLORS[awayTricode] ?? FALLBACK_LIGHT;
  const homeHex = TEAM_COLORS[homeTricode] ?? FALLBACK_DARK;

  const awayB = brightness(awayHex);
  const homeB = brightness(homeHex);

  // If both are very dark (navy vs navy etc.), use fallbacks
  if (awayB < 40 && homeB < 40) {
    return { awayColor: '#60A5FA', homeColor: '#34D399' };
  }

  // Assign brighter to away, darker to home — swapping if needed
  if (awayB >= homeB) {
    return {
      awayColor: awayB < 40 ? FALLBACK_LIGHT : awayHex,
      homeColor: homeB < 40 ? FALLBACK_DARK : homeHex,
    };
  } else {
    return {
      awayColor: homeB < 40 ? FALLBACK_LIGHT : homeHex,
      homeColor: awayB < 40 ? FALLBACK_DARK : awayHex,
    };
  }
}
