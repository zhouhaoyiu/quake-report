import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  applicationName: "地震活动报告生成器",
  title: "地震活动报告生成器",
  description:
    "基于 USGS、EMSC/SeismicPortal、GEM 活动断层、Natural Earth 和天地图的地震活动分析报告生成工具。",
  keywords: ["地震", "USGS", "EMSC", "GEM", "天地图", "活动断层", "地震活动报告"],
  authors: [{ name: "Quake Report" }],
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    shortcut: "/favicon.svg",
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  appleWebApp: {
    capable: true,
    title: "地震活动报告生成器",
    statusBarStyle: "default",
  },
  openGraph: {
    title: "地震活动报告生成器",
    description:
      "基于多源地震目录和活动断层资料生成 Word、PDF 与图件。",
    siteName: "Quake Report",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "地震活动报告生成器",
    description: "基于多源地震资料生成 Word、PDF 与图件。",
  },
};

export const viewport: Viewport = {
  themeColor: "#2d241c",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
