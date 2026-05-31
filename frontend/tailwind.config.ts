import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Professional forensic palette — inspired by CrowdStrike / VirusTotal / SentinelOne
        bg: {
          primary:   '#080c15',
          secondary: '#0f1623',
          tertiary:  '#141c2a',
          elevated:  '#1a2436',
        },
        border: {
          subtle:  '#1e2d42',
          default: '#253348',
          strong:  '#2e4060',
          focus:   '#1e63d4',
        },
        fg: {
          primary:   '#cdd5e0',
          secondary: '#7a8899',
          muted:     '#3d4f62',
          link:      '#2e7cf6',
        },
        accent: {
          blue:       '#1e63d4',
          'blue-h':   '#2e7cf6',
          cyan:       '#0b7f8c',
          'cyan-h':   '#0e9dac',
        },
        risk: {
          critical:  '#c42b2b',
          'critical-bg': 'rgba(196,43,43,0.08)',
          'critical-border': 'rgba(196,43,43,0.25)',
          high:      '#b86a1a',
          'high-bg': 'rgba(184,106,26,0.08)',
          'high-border': 'rgba(184,106,26,0.25)',
          medium:    '#9a7c12',
          'medium-bg': 'rgba(154,124,18,0.08)',
          'medium-border': 'rgba(154,124,18,0.25)',
          low:       '#1d7a45',
          'low-bg':  'rgba(29,122,69,0.08)',
          'low-border': 'rgba(29,122,69,0.25)',
          minimal:   '#0e6b6b',
          'minimal-bg': 'rgba(14,107,107,0.08)',
          'minimal-border': 'rgba(14,107,107,0.25)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.65rem', { lineHeight: '1rem' }],
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-down': 'slideDown 0.2s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideDown: {
          '0%':   { opacity: '0', transform: 'translateY(-4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
};

export default config;
