/** Design tokens from docs/style_guide.md §B.3-B.5 — components read Tailwind
 * classes (`bg-surface`, `text-muted`, `rounded-tile`…), never raw hex.
 * Values live once, in src/styles/tokens.css; this file only maps names.
 */
export default {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        'surface-raised': 'var(--surface-raised)',
        rule: 'var(--rule)',
        text: 'var(--text)',
        'text-muted': 'var(--text-muted)',
        accent: 'var(--accent)',
        'accent-ink': 'var(--accent-ink)',
        'sev-low': 'var(--sev-low)',
        'sev-medium': 'var(--sev-medium)',
        'sev-high': 'var(--sev-high)',
        'sev-critical': 'var(--sev-critical)',
        ok: 'var(--ok)',
        'video-bg': 'var(--video-bg)',
      },
      fontFamily: {
        sans: ['Barlow', 'system-ui', 'sans-serif'],
        condensed: ['"Barlow Semi Condensed"', 'system-ui', 'sans-serif'],
        serif: ['"Source Serif 4"', 'serif'],
      },
      fontSize: {
        xs: '11.7px',
        sm: '14px',
        base: '16.8px',
        lg: '20.2px',
        xl: '24.2px',
        '2xl': '29px',
      },
      spacing: {
        1: '4px',
        2: '8px',
        3: '12px',
        4: '16px',
        6: '24px',
        8: '32px',
        12: '48px',
      },
      borderRadius: {
        tile: '2px',
        panel: '6px',
        pill: '9999px',
      },
      width: {
        'nav-rail': '56px',
        'alert-tray': '320px',
      },
    },
  },
  plugins: [],
};
