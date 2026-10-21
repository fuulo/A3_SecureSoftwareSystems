import Link from "next/link";
import Image from "next/image";
import { mainHeader, subHeader } from "../components/styles";
import { Permanent_Marker } from "next/font/google";

const handwriting = Permanent_Marker ({ subsets: ["latin"], weight: "400"});

export default function Home() {
  return (
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
  );
}