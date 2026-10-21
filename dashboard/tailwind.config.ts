import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/features/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/shared/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    fontFamily: {
      sans: ["Segoe UI Variable Text", "Segoe UI", "Inter", "system-ui", "-apple-system", "BlinkMacSystemFont", "Helvetica Neue", "sans-serif"],
      mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
    },
    extend: {
      colors: {
        border:     "hsl(var(--border))",
        input:      "hsl(var(--input))",
        ring:       "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card:    { DEFAULT: "hsl(var(--card))",    foreground: "hsl(var(--card-foreground))"    },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        primary: {
          DEFAULT:    "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
          hover:      "hsl(var(--primary-hover))",
          soft:       "hsl(var(--primary-soft))",
          muted:      "hsl(var(--primary-muted))",
        },
        secondary:   { DEFAULT: "hsl(var(--secondary))",   foreground: "hsl(var(--secondary-foreground))"   },
        muted:       { DEFAULT: "hsl(var(--muted))",       foreground: "hsl(var(--muted-foreground))"       },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        success: { DEFAULT: "#12B76A", soft: "#ECFDF3", text: "#067647", border: "#ABEFC6" },
        warning: { DEFAULT: "#F79009", soft: "#FFFAEB", text: "#B54708", border: "#FEDF89" },
        danger:  { DEFAULT: "#F04438", soft: "#FEF3F2", text: "#B42318", border: "#FECDCA" },
        surface: {
          DEFAULT: "#FFFFFF",
          page:    "#F5F6F8",
          raised:  "#FFFFFF",
          muted:   "#F9FAFB",
          subtle:  "#F2F4F7",
          line:    "#E4E7EC",
        },
        ink: {
          heading: "#101828",
          body:    "#344054",
          muted:   "#667085",
          subtle:  "#98A2B3",
        },
        chart: {
          predicted: "#1F4B8E",
          actual:    "#0E8F72",
          target:    "#B54708",
        },
      },
      borderRadius: {
        lg:   "var(--radius)",
        md:   "calc(var(--radius) - 4px)",
        sm:   "calc(var(--radius) - 8px)",
        pill: "9999px",
      },
      fontSize: {
        "tiny":    ["0.65rem",   { lineHeight: "1rem"    }],
        "label":   ["0.75rem",   { lineHeight: "1rem"    }],
        "caption": ["0.8125rem", { lineHeight: "1.25rem" }],
        "body-sm": ["0.875rem",  { lineHeight: "1.25rem" }],
        "body":    ["0.95rem",   { lineHeight: "1.5rem"  }],
        "h4":      ["1em",       { lineHeight: "1.5rem",  fontWeight: "700" }],
        "h3":      ["1.25em",    { lineHeight: "1.75rem", fontWeight: "700" }],
        "h2":      ["1.5em",     { lineHeight: "2rem",    fontWeight: "700" }],
        "h1":      ["1.75em",    { lineHeight: "2.25rem", fontWeight: "700" }],
      },
      height: {
        "comp-sm": "2rem",
        "comp-md": "2.5rem",
        "comp-lg": "3rem",
      },
      spacing: {
        "section": "4rem",
        "element": "1.5rem",
      },
      boxShadow: {
        card:     "0 1px 2px rgba(16, 24, 40, 0.04)",
        panel:    "0 1px 2px rgba(16, 24, 40, 0.05), 0 8px 24px rgba(16, 24, 40, 0.04)",
        elevated: "0 12px 32px rgba(16, 24, 40, 0.12)",
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up":   { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "shimmer":        { "0%": { backgroundPosition: "200% 0" }, "100%": { backgroundPosition: "-200% 0" } },
        "diagonal-move":  { "0%, 100%": { transform: "translate(0, 0) scale(1)" }, "10%": { transform: "translate(8px, -8px) scale(1.1)" }, "20%": { transform: "translate(0, 0) scale(1)" } },
        "slide-in-right": { from: { transform: "translateX(100%)" }, to: { transform: "translateX(0)" } },
        "slide-out-left": { from: { transform: "translateX(0)" }, to: { transform: "translateX(-100%)" } },
        "slide-out-right":{ from: { transform: "translateX(0)" }, to: { transform: "translateX(100%)" } },
      },
      animation: {
        "accordion-down":  "accordion-down 0.2s ease-out",
        "accordion-up":    "accordion-up 0.2s ease-out",
        "shimmer":         "shimmer 1.5s infinite",
        "diagonal":        "diagonal-move 3s ease-in-out infinite",
        "slide-in-right":  "slide-in-right 0.5s ease-in-out",
        "slide-out-left":  "slide-out-left 0.5s ease-in-out",
        "slide-out-right": "slide-out-right 0.5s ease-in-out",
      },
    },
  },
  plugins: [
    require("tailwindcss-animate"),
    require("tailwind-scrollbar"),
  ],
};

export default config;
