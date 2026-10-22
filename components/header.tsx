import Link from "next/link";
import Image from "next/image";

const headerBrandStyle = "text-[28px] font-semibold text-white";
const headerTitleStyle = "text-[22px] font-semibold text-white";

export default function Header() {
  return (
    <header className="bg-[#0E1531]">
      <div className="mx-auto max-w-6xl px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link
            href="/"
            className="flex items-end gap-3 transition-opacity hover:opacity-80"
          >
            <Image
              src="/logo.png"
              alt="Mock voting system logo"
              width={72}
              height={72}
            />
            <span className={`${headerBrandStyle} leading-none`}>AUSTRALIA</span>
          </Link>
          <p className={`${headerTitleStyle} mt-3`}>
            Welcome to the Federal Election Online Voting System
          </p>
        </div>
      </div>
    </header>
  );
}