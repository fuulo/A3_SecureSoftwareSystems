import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import DisclaimerBar from "../components/disclaimer";
import Header from "../components/header";
import Footer from "../components/footer";
import SignOutOnLeave from "../components/signoutonleave";

// Page font
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Online Voting System",
  description: "A mock online voting system for Secure Software Systems",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={null}>
          <SignOutOnLeave />
        </Suspense>
        <div
          className={`${inter.className} relative min-h-screen bg-[#EAF3FC] text-[15px] text-[#222]`}
        >
          {/* Logo as background (faint, fixed in the centre of the window) */}
          <div
            aria-hidden="true"
            className="pointer-events-none fixed inset-0 z-0 bg-[url('/logo.png')] bg-[length:720px] bg-right-bottom bg-no-repeat opacity-10"
          />

          {/* Page content, above the background */}
          <div className="relative z-10 flex min-h-screen flex-col">
            <DisclaimerBar />
            <Header />
            <div className="flex-1">
              <Suspense fallback={<div className="min-h-[40vh]" />}>
                {children}
              </Suspense>
            </div>
            <Footer />
          </div>
        </div>
      </body>
    </html>
  );
}