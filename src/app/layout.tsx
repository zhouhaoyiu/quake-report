import type { Metadata } from "next";
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
  title: "地震活动报告生成器",
  description:
    "基于 USGS、EMSC/SeismicPortal、GEM 活动断层、Natural Earth 和天地图的地震活动分析报告生成工具。",
  keywords: ["地震", "USGS", "EMSC", "GEM", "天地图", "活动断层", "地震活动报告"],
  authors: [{ name: "Quake Report" }],
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
