import type { Config } from "tailwindcss";

/**
 * Dispatch Planner.
 *
 * Built for people who read this screen all day beside a warehouse floor, so it is dense, quiet and
 * instrument-like: small type with real tabular figures, hairline rules instead of floating cards,
 * and a short radius. IBM Plex Sans carries the interface; IBM Plex Mono is used only where a string
 * is an identifier someone will read out or type back (order ids, SKU codes, references).
 */
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
      sans: ["'IBM Plex Sans Variable'", "'IBM Plex Sans'", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
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
          DEFAULT:    "hsl(var(--accent))",
          foreground: "hsl(var(--primary-foreground))",
          hover:      "hsl(var(--accent-hi))",
          soft:       "hsl(var(--accent-soft))",
          muted:      "hsl(var(--primary-muted))",
        },
        secondary:   { DEFAULT: "hsl(var(--secondary))",   foreground: "hsl(var(--secondary-foreground))"   },
        muted:       { DEFAULT: "hsl(var(--muted))",       foreground: "hsl(var(--muted-foreground))"       },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },

        /* the dark navigation rail */
        chrome: {
          DEFAULT: "hsl(var(--chrome))",
          raised:  "hsl(var(--chrome-raised))",
          line:    "hsl(var(--chrome-line))",
          text:    "hsl(var(--chrome-text))",
        },

        /* status. Each has a line colour for rails and marks, and a wash for the rare filled area. */
        success: { DEFAULT: "#0E7C5A", soft: "#E7F4EF", text: "#0B5F46", border: "#B3DECB" },
        warning: { DEFAULT: "#B4690E", soft: "#FCF2E3", text: "#8A500A", border: "#EBCB97" },
        danger:  { DEFAULT: "#C13A2E", soft: "#FBECEA", text: "#96281F", border: "#EFB7B0" },

        surface: {
          DEFAULT: "hsl(var(--paper))",
          page:    "hsl(var(--field))",
          raised:  "hsl(var(--paper))",
          muted:   "hsl(var(--field))",
          subtle:  "hsl(216 20% 95%)",
          line:    "hsl(var(--rule))",
          rule:    "hsl(var(--rule-strong))",
        },
        ink: {
          heading: "hsl(var(--ink-900))",
          body:    "hsl(var(--ink-700))",
          muted:   "hsl(var(--ink-500))",
          subtle:  "hsl(var(--ink-400))",
        },
        chart: {
          predicted: "#1F4B8E",
          actual:    "#0E7C5A",
          target:    "#B4690E",
          grid:      "#E2E6ED",
          axis:      "#5A6782",
        },
      },

      /* Short, consistent corners. Only what genuinely floats gets a larger one. */
      borderRadius: {
        sm:   "0.1875rem",
        md:   "0.3125rem",
        lg:   "0.3125rem",
        xl:   "0.5rem",
        pill: "9999px",
      },

      /* A 14px base, because this screen is read as a table all day. */
      fontSize: {
        "micro":   ["0.6875rem", { lineHeight: "0.875rem", letterSpacing: "0.01em" }],
        "tiny":    ["0.6875rem", { lineHeight: "0.875rem" }],
        "label":   ["0.75rem",   { lineHeight: "1rem"     }],
        "caption": ["0.8125rem", { lineHeight: "1.125rem" }],
        "body-sm": ["0.8125rem", { lineHeight: "1.25rem"  }],
        "body":    ["0.875rem",  { lineHeight: "1.375rem" }],
        "lead":    ["1rem",      { lineHeight: "1.5rem"   }],
        "h4":      ["0.875rem",  { lineHeight: "1.25rem", fontWeight: "600", letterSpacing: "-0.003em" }],
        "h3":      ["1rem",      { lineHeight: "1.375rem", fontWeight: "600", letterSpacing: "-0.006em" }],
        "h2":      ["1.25rem",   { lineHeight: "1.625rem", fontWeight: "600", letterSpacing: "-0.012em" }],
        "h1":      ["1.5rem",    { lineHeight: "1.875rem", fontWeight: "600", letterSpacing: "-0.018em" }],
        "metric":  ["1.75rem",   { lineHeight: "2rem",     fontWeight: "600", letterSpacing: "-0.022em" }],
        "metric-lg": ["2.25rem", { lineHeight: "2.5rem",   fontWeight: "600", letterSpacing: "-0.026em" }],
      },

      height: {
        "comp-sm": "1.75rem",
        "comp-md": "2.125rem",
        "comp-lg": "2.5rem",
        "row":     "2.25rem",
        "topbar":  "3.25rem",
      },
      width: {
        "rail":     "13.5rem",
        "rail-sm":  "3.5rem",
        "panel":    "26rem",
      },
      spacing: {
        "rail":    "13.5rem",
        "rail-sm": "3.5rem",
        "topbar":  "3.25rem",
        "gutter":  "1.25rem",
      },

      boxShadow: {
        card:     "none",
        panel:    "0 1px 1px rgba(11, 18, 32, 0.03), 0 10px 28px -12px rgba(11, 18, 32, 0.22)",
        pop:      "0 2px 4px rgba(11, 18, 32, 0.06), 0 16px 32px -12px rgba(11, 18, 32, 0.28)",
        elevated: "0 2px 4px rgba(11, 18, 32, 0.06), 0 16px 32px -12px rgba(11, 18, 32, 0.28)",
      },

      keyframes: {
        "panel-in":  { from: { opacity: "0", transform: "translateX(12px)" }, to: { opacity: "1", transform: "translateX(0)" } },
        "fade-in":   { from: { opacity: "0" }, to: { opacity: "1" } },
        "shimmer":   { "0%": { backgroundPosition: "200% 0" }, "100%": { backgroundPosition: "-200% 0" } },
      },
      animation: {
        "panel-in": "panel-in 0.16s cubic-bezier(0.2, 0, 0, 1)",
        "fade-in":  "fade-in 0.12s linear",
        "shimmer":  "shimmer 1.4s infinite",
      },
    },
  },
  plugins: [
    require("tailwindcss-animate"),
    require("tailwind-scrollbar"),
  ],
};

export default config;
