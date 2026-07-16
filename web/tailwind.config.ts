import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['var(--font-display)', 'Georgia', 'serif'],
        sans: ['var(--font-sans)', 'PingFang SC', 'Noto Sans CJK SC', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        ivory: '#f4efe6',
        paper: '#faf6ee',
        ink: '#1a1714',
        claret: '#8c2f2a',
        ember: '#b8533b',
        sage: '#5a6b52',
        gold: '#b08534',
      },
      boxShadow: {
        sheet: '0 30px 70px -30px rgba(26,23,20,.30), 0 2px 8px rgba(26,23,20,.05)',
        lift: '0 18px 44px -20px rgba(26,23,20,.28)',
      },
    },
  },
  plugins: [],
};
export default config;
