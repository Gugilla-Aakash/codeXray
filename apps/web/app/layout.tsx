import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

/* Variable fonts are vendored in app/fonts (see LICENSES.md) so builds are
   offline-safe: no next/font/google fetch, no Turbopack font-replacer bug. */

const display = localFont({
  src: "./fonts/sora.woff2",
  weight: "100 800",
  variable: "--font-display",
  display: "swap",
});

const body = localFont({
  src: "./fonts/inter.woff2",
  weight: "100 900",
  variable: "--font-body",
  display: "swap",
});

const mono = localFont({
  src: "./fonts/jetbrains-mono.woff2",
  weight: "100 800",
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CodeXRay — Real-Time Visual Debugging & Observability",
  description:
    "Stop reading logs. Watch your software think. CodeXRay turns live telemetry into an interactive system graph.",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${mono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
