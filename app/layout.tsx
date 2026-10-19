import type { Metadata } from "next";
import { Google_Sans } from "next/font/google";
import "./globals.css";
import DisclaimerBar from "../components/disclaimer";
import Header from "../components/header";
import Footer from "../components/footer";

// Page font
const googleSans = Google_Sans({ subsets: ["latin"] });

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
        <div
          className={`${googleSans.className} flex min-h-screen flex-col bg-white text-[15px] text-[#222]`}
        >
          <DisclaimerBar />
          <Header />
          <div className="flex-1">{children}</div>
          <Footer />
        </div>
      </body>
    </html>
  );
}