/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#090A0F',
        surface: {
          DEFAULT: '#111420',
          elevated: '#171B2B',
          hover: '#1D2236',
        },
        border: {
          DEFAULT: '#1E2436',
          subtle: '#161B2B',
          focus: '#3B82F6',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
