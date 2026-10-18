// Pure white page, frosted glass in soft greys, yellow and orange accents, black for the main action.
// M PLUS 1 (Light) for titles and names, Quicksand for the small details.
export const C = {
  skyTop: '#c3d4de',
  skyMid: '#a3bbc9',
  skyLow: '#8ea9b9',
  ink: '#16222b',
  muted: '#43545f',
  faint: '#6a7c87',
  glass: 'rgba(240,243,246,0.82)',
  glassStrong: 'rgba(244,246,248,0.94)',
  rim: '#c3cbd3',
  black: '#111417',
  yellow: '#f3d55b',
  yellowDeep: '#e8b923',
  orange: '#f7941d',
  orangeDeep: '#e2701a',
  live: '#1f9d63',
  danger: '#c8412f',
  // kept for older screens
  page: '#ffffff',
  hairline: 'rgba(255,255,255,0.6)',
  sunken: 'rgba(255,255,255,0.3)',
  orangeWash: 'rgba(255,255,255,0.4)',
  help: '#f3d55b',
  helpWash: 'rgba(243,213,91,0.35)',
  orangePale: '#ffc062',
}

export const F = {
  light: 'MPLUS1_200ExtraLight',
  regular: 'MPLUS1_300Light',
  medium: 'MPLUS1_400Regular',
  semibold: 'MPLUS1_500Medium',
  round: 'Quicksand_500Medium',
  logo: 'MPLUS1_300Light',
}

export const glow = [C.orange, C.orangeDeep, '#cf5a12'] as const

// The blocky orange and white look: square corners, chunky edges and hard shadows, like toy bricks.
export const B = {
  orange: '#f28a1e',
  orangeDark: '#d9650f', // item blocks
  shadow: '#9c4207', // the hard shadow under orange blocks
  cream: '#fff3e0',
  creamDeep: '#f6e2c4',
  line: '#f5c28a', // blueprint grid
  ink: '#2b1a0c',
  depth: 6, // how far blocks stand off the page
}

// The orange glass look: one warm orange page, a glowing aura, and frosted glass on top.
export const O = {
  page: '#e2870b',
  peach: '#ffe3b8',
  coral: '#ff8a6e',
  glass: 'rgba(255,226,190,0.14)',
  rim: 'rgba(255,236,210,0.5)',
  text: '#fff8ee',
  soft: 'rgba(255,248,238,0.78)',
  sheet: '#ffffff',
  row: '#e6e6e6',
  ink: '#151515',
  inkSoft: '#6e6e6e',
}

// The blueprint look: deep blueprint-blue paper with a fine white grid, everything drawn in thin
// white lines with square corners, and a white bar at the bottom for their things.
export const P = {
  paper: '#1656ad',
  paperDeep: '#124a96', // the edges of the sheet
  line: '#ffffff',
  soft: 'rgba(255,255,255,0.72)',
  faint: 'rgba(255,255,255,0.4)',
  sheet: '#ffffff',
  ink: '#123c78', // dark blueprint ink on the white bar
  muted: '#6b7d93',
  rule: '#c7d6ea', // thin outlines on the white bar
  radius: 4,
}
