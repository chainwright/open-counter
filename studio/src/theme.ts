import { studioTheme } from 'ag-studio';

// Lena's workshop (design B v2, judged 8.7): warm paper, ink, thin brass rules, enamel red only for "sold via an
// outside AI". Serif titles live inside our two custom widgets; Studio's own chrome stays a plain sans.
export const INK = '#2B2620';
export const PAPER = '#F2F0EA';
export const BRASS = '#A8873F';
export const ENAMEL_RED = '#A3262B';
export const PENCIL_GREEN = '#2F7A47';
export const CHATS_GREY = '#CFC8BA';

export const workshopTheme = studioTheme.withParams({
  backgroundColor: PAPER,
  foregroundColor: INK,
  textColor: INK,
  subtleTextColor: '#7A7062',
  accentColor: BRASS,
  borderColor: '#D8CDB4',
  borderWidth: 1,
  borderRadius: 4,
  fontFamily: '"Geist", system-ui, sans-serif',
  menuBackgroundColor: '#FAF8F3',
  rowHoverColor: '#ECE6D8',
  tooltipBackgroundColor: INK,
  tooltipTextColor: PAPER,
  browserColorScheme: 'light',
  // chart series: chats in warm grey, orders in brass (no car paint colours on this page)
  chartPaletteFills1Color: CHATS_GREY,
  chartPaletteFills2Color: BRASS,
  chartPaletteFills3Color: '#6E6457',
  chartPaletteFills4Color: '#D9B96A',
} as any);
