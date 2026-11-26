/** Designsystem-Tokens von MOSI PLAN – Farben als CSS-Variablen (siehe src/index.css) */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
/** Glasflächen: weiß mit geringer Deckkraft; Modifier (z. B. bg-surface/60) skalieren die Grund-Deckkraft */
const glass = (base, rgb = "255 255 255") => ({ opacityValue }) =>
  `rgb(${rgb} / ${opacityValue !== undefined ? `calc(${opacityValue} * ${base})` : base})`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: glass(0.42, "8 9 12"),
        rail: glass(0.55, "16 15 18"),
        surface: glass(0.075),
        raised: glass(0.12),
        line: glass(0.09),
        "line-strong": glass(0.16),
        ink: v("ink"),
        "ink-2": v("ink-2"),
        "ink-3": v("ink-3"),
        accent: v("accent"),
        "accent-ink": v("accent-ink"),
        ok: v("ok"),
        warn: v("warn"),
        danger: v("danger"),
      },
      fontFamily: { sans: ['"Inter Variable"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
      fontSize: {
        // Skala ~1.2 (Minor Third), Zeilenhöhen nach Bringhurst
        "2xs": ["11px", { lineHeight: "16px" }],
        xs: ["12px", { lineHeight: "16px" }],
        sm: ["13px", { lineHeight: "20px" }],
        base: ["14px", { lineHeight: "22px" }],
        md: ["16px", { lineHeight: "24px" }],
        lg: ["19px", { lineHeight: "28px" }],
        xl: ["23px", { lineHeight: "30px", letterSpacing: "-0.015em" }],
        "2xl": ["28px", { lineHeight: "36px", letterSpacing: "-0.02em" }],
        "3xl": ["34px", { lineHeight: "42px", letterSpacing: "-0.025em" }],
      },
      borderRadius: { sm: "8px", DEFAULT: "12px", md: "22px", lg: "28px" },
      boxShadow: {
        pop: "0 24px 60px -12px rgb(0 0 0 / 0.6), inset 0 1px 0 rgb(255 255 255 / 0.10), 0 0 0 1px rgb(255 255 255 / 0.12)",
        glass: "inset 0 1px 0 rgb(255 255 255 / 0.10), 0 10px 40px -16px rgb(0 0 0 / 0.5)",
        focus: "0 0 0 2px rgb(20 18 18), 0 0 0 4px rgb(var(--accent) / 0.7)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "pop-in": { from: { opacity: 0, transform: "translateY(4px) scale(.98)" }, to: { opacity: 1, transform: "none" } },
        pulse: { "0%,100%": { opacity: 1 }, "50%": { opacity: 0.45 } },
      },
      animation: { "fade-in": "fade-in .15s ease-out", "pop-in": "pop-in .16s ease-out", pulse: "pulse 1.6s ease-in-out infinite" },
    },
  },
  plugins: [],
};
