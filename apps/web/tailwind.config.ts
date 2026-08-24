import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}", "../../packages/shared/src/**/*.{ts,tsx}"],
  theme: {
    borderRadius: {
      none: "0",
      sm: "8px",
      DEFAULT: "12px",
      md: "16px",
      lg: "20px",
      xl: "20px",
      "2xl": "24px",
      "3xl": "28px",
      full: "999px",
    },
    extend: {
      colors: {
        background: "#fff8f1",
        foreground: "#1d1e1c",
        muted: "#615f5c",
        border: "#d9d9d9",
        panel: "#ffffff",
        accent: "#fa5d00",
        success: "#fa5d00",
      },
      boxShadow: {
        panel: "6px 4px 24px rgba(250,166,0,0.25)",
        glow: "0 10px 30px rgba(250,93,0,0.2)",
      },
      fontFamily: {
        sans: ["Inter", "Sohne", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Georgia", "Times New Roman", "ui-serif", "serif"],
      },
    },
  },
  plugins: [],
};

export default config;
