/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
    "./*.{js,ts,jsx,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          dark: '#1F3864',
          light: '#2E5597',
        },
        background: '#f0fdf4', // Light green
        'light-green': '#f0fdf4',
      },
      backgroundColor: {
        DEFAULT: '#f0fdf4',
      }
    },
  },
  plugins: [],
}
