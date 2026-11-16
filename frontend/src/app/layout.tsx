import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TripSage | Joint Multi-Modal Travel Arbitrage & Itinerary Engine",
  description:
    "Conversational multi-phase travel planner & spatio-temporal arbitrage engine across Flights, Road Trips, Hotels, Airbnb, and The Blue Kite.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

const themeInitScript = `{
  try {
    const saved = localStorage.getItem("color-scheme");
    if (saved === "light" || saved === "dark") {
      const meta = document.querySelector('meta[name="color-scheme"]');
      if (meta) meta.setAttribute("content", saved);
      document.documentElement.dataset.theme = saved;
    }
    const seed = localStorage.getItem("m3-seed");
    if (seed === "amber" || seed === "sapphire" || seed === "violet") {
      document.documentElement.dataset.m3Seed = seed;
    }
  } catch (_) {}
}`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <meta name="color-scheme" content="light dark" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Geist:wght@300..700&family=Instrument+Serif:ital@0;1&display=swap"
          rel="stylesheet"
        />
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
