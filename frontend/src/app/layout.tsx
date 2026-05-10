import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import { Suspense } from "react";

export const metadata: Metadata = {
  title: "StockHIFI - Trading Dashboard",
  description: "Stock Trading Automation Dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <div className="flex h-screen overflow-hidden">
            <Suspense fallback={<div className="w-[60px] bg-navy-800" />}>
              <Sidebar />
            </Suspense>
            <div className="flex-1 flex flex-col overflow-hidden">
              <TopBar />
              <main className="flex-1 overflow-y-auto p-3 lg:p-4 bg-gray-50">
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
