import typography from '@tailwindcss/typography'

/** Tokens mirror docs/design.md §3. */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0b0c0e',
        surface: '#111316',
        'surface-2': '#171a1e',
        line: '#24282e',
        text: '#e6e6e3',
        dim: '#8a8f98',
        mute: '#555b63',
        accent: '#d4ff3a',
        ok: '#3ddc84',
        warn: '#ffb020',
        err: '#ff4d4d',
        run: '#5ab0ff',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      borderRadius: { none: '0', DEFAULT: '0', sm: '2px' },
      keyframes: {
        blink: { '0%, 49%': { opacity: '1' }, '50%, 100%': { opacity: '0' } },
        progress: { '0%': { transform: 'translateX(-100%)' }, '100%': { transform: 'translateX(300%)' } },
      },
      animation: {
        blink: 'blink 1.1s steps(1) infinite',
        progress: 'progress 1.2s ease-in-out infinite',
      },
    },
  },
  plugins: [typography],
}
