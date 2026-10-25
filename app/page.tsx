import Link from "next/link";
import Image from "next/image";
import { mainHeader, subHeader } from "../components/styles";
import { Permanent_Marker } from "next/font/google";

const handwriting = Permanent_Marker ({ subsets: ["latin"], weight: "400"});

const iconStyle = "h-7 w-7";

// Public pages anyone can use without logging in
const publicPages = [
  {
    href: "/results",
    title: "Published Results",
    description:
      "See the official results for each House division and Senate state, including turnout and the published fingerprint.",
    action: "View results",
    icon: (
      <svg className={iconStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M3 3v18h18" />
        <path d="M7 16v-4M12 16V8M17 16v-7" />
      </svg>
    ),
  },
  {
    href: "/verify-receipt",
    title: "Verify Your Receipt",
    description:
      "Enter the receipt code you were given after voting to confirm your ballot was recorded. Your vote stays secret.",
    action: "Verify receipt",
    icon: (
      <svg className={iconStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M6 2h12v20l-3-2-3 2-3-2-3 2z" />
        <path d="M9 11l2 2 4-4" />
      </svg>
    ),
  },
  {
    href: "/verify-package",
    title: "Verify Result Package",
    description:
      "Check that a downloaded result package is genuine and that its totals add up. The check runs in your browser.",
    action: "Verify package",
    icon: (
      <svg className={iconStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    ),
  },
];

export default function Home() {
  return (
    <>
      <div className="mx-auto grid max-w-6xl gap-8 px-6 pb-4 pt-8 min-[600px]:grid-cols-[1fr_minmax(240px,320px)]">
        <main>
          <h1 className={`${mainHeader} mb-4`}>How to Vote?</h1>

          <section id="authenticate-yourself" className="mb-8">
            <h2 className={`${subHeader} mb-2`}>1. Authenticate Yourself</h2>
            <p className="mb-3 pl-4">&#9654; Have your ID and password ready</p>
            <p className="mb-3 pl-4">
              &#9654; Click “Log In” in the box to the right
            </p>
            <p className="mb-3 pl-4">
              &#9654; Verify your identity with your ID and password
            </p>
            <p className="mb-3 pl-4">
              &#9654; When prompted, enter the MFA verification code sent to you 
            </p>
          </section>

          <section id="cast-your-vote" className="mb-8">
            <h2 className={`${subHeader} mb-2`}>2. Cast Your Votes</h2>
            <p className="mb-3 pl-4">
              &#9654; System will check your enrolment status and eligibility to
              vote
            </p>
            <p className="mb-3 pl-4">
              &#9654; If you are not enrolled, you will be guided to do so
            </p>
            <p className="mb-3 pl-4">
              &#9654; Candidate details will be displayed
            </p>
            <p className="mb-3 pl-4">
              &#9654; Check the box of your selected candidate(s)
            </p>
            <p className="mb-3 pl-4">
              &#9654; Check your selection, and click “Vote” to cast your vote
            </p>
          </section>

          <section id="questions" className="mb-0">
            <h2 className={`${subHeader} mb-2`}>3. Questions or Difficulties?</h2>
            <p className="mb-3 pl-4">
              &#9654; If you are unsure, on-site AEC staff are ready to help 
            </p>
          </section>
        </main>

        {/* Call to action on the right */}
        <aside>
          <div className="rounded-lg bg-[#1f538d] p-8 text-center shadow-lg">
            <Image
              src="/tickbox.png"
              alt="Ballot tick box"
              width={96}
              height={96}
              className="mx-auto mb-4"
            />
            <h2 className="mb-3 text-[28px] font-bold text-white">
              Ready to vote?
            </h2>
            <p className="mb-6 text-white">Click here to log in:</p>
            <Link
              href="/login"
                className="inline-block rounded-lg bg-white px-8 py-3 text-[28px] font-bold capitalize text-[#1f538d] shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-slate-100 hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)]"
            >
              LOG IN
            </Link>
            <p className={`${handwriting.className} mt-6 text-[24px] text-white`}>
              “Vote Today for A Better Tomorrow!”
            </p>
          </div>
        </aside>
      </div>

      {/* Results and verification, open to everyone */}
      <section
        aria-labelledby="results-and-verification"
        className="mx-auto max-w-6xl px-6 pb-12 pt-6"
      >
        <h2 id="results-and-verification" className={`${mainHeader} mb-1`}>
          Election Results and Verification
        </h2>
        <p className="mb-6">
          Anyone can view the results and check them. No log in is needed.
        </p>

        <div className="grid gap-6 md:grid-cols-3">
          {publicPages.map((page) => (
            <article
              key={page.href}
              className="flex flex-col rounded-lg border border-slate-300 bg-white p-6 shadow-lg"
            >
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[#EAF3FC] text-[#1f538d]">
                {page.icon}
              </div>
              <h3 className={`${subHeader} mb-2`}>{page.title}</h3>
              <p className="mb-6 flex-1 text-slate-700">{page.description}</p>
              <Link
                href={page.href}
                className="block rounded-lg bg-[#1f538d] px-6 py-3 text-center text-[18px] font-bold text-white shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-[#1b4779] hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#1f538d] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)]"
              >
                {page.action}
              </Link>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}