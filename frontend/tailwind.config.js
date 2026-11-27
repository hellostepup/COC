/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        gold: "#f2c14e",
        elixir: "#d65ce6",
        dark: "#9b8ac4",
        panel: "#161b26",
        panel2: "#1e2433",
        line: "#2a3142",
        ink: "#e6e9f0",
        muted: "#8a93a6",
      },
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"] },
    },
  },
  plugins: [],
};
