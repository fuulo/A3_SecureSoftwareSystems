"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { mainHeader } from "../../components/styles";
import { formatDateTime } from "../../lib/results";
import {
  MOCK_RECEIPTS,
  RECEIPT_ALPHABET,
  RECEIPT_GROUP_LENGTH,
  RECEIPT_LENGTH,
  type ReceiptRecord,
} from "../../lib/receipts";

// Removes anything that is not a valid receipt character
function cleanReceipt(raw: string) {
  const allowed = new RegExp(`[^${RECEIPT_ALPHABET}]`, "g");
  return raw.toUpperCase().replace(allowed, "").slice(0, RECEIPT_LENGTH);
}

// Shows the receipt in groups, e.g. "7KQ2M9XD..." -> "7KQ2-M9XD-..."
function formatReceipt(clean: string) {
  const groups = clean.match(new RegExp(`.{1,${RECEIPT_GROUP_LENGTH}}`, "g"));
  return groups ? groups.join("-") : "";
}

export default function VerifyReceiptPage() {
  const [receipt, setReceipt] = useState("");
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [record, setRecord] = useState<ReceiptRecord | null>(null);
  const [checking, setChecking] = useState(false);

  // Clear the form when the page is shown again by back/forward navigation
  useEffect(() => {
    function clearForm() {
      setReceipt("");
      setError("");
      setWarning("");
      setRecord(null);
    }

    window.addEventListener("pageshow", clearForm);
    return () => window.removeEventListener("pageshow", clearForm);
  }, []);

  // Hide the warning after 3 seconds
  useEffect(() => {
    if (!warning) return;
    const timer = setTimeout(() => setWarning(""), 3000);
    return () => clearTimeout(timer);
  }, [warning]);

  function handleChange(raw: string) {
    const withoutDashes = raw.replace(/[-\s]/g, "").toUpperCase();
    const invalid = new RegExp(`[^${RECEIPT_ALPHABET}]`);
    setReceipt(cleanReceipt(withoutDashes));
    setRecord(null);
    setError("");
    setWarning(
      invalid.test(withoutDashes)
        ? "Receipt codes never contain symbols or the characters 0, 1, I, L or O."
        : ""
    );
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRecord(null);

    if (receipt.length !== RECEIPT_LENGTH) {
      setError(`Please enter all ${RECEIPT_LENGTH} characters of your receipt code.`);
      return;
    }
    setError("");
    setChecking(true);




    // TODO: send the receipt code to the backend to check it.
    // The backend should rate-limit lookups so receipt codes cannot be guessed.
    // Mock lookup until the backend is ready:
    const found = MOCK_RECEIPTS[receipt];




    setChecking(false);
    if (!found) {
      // ONE general message, so the page does not reveal anything extra
      setError("No ballot was found for this receipt code. Check the code and try again.");
      return;
    }
    setRecord(found);
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-lg rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>Verify Your Receipt</h1>
        <p className="mb-1 text-center">
          Enter the receipt code you were given after casting your vote.
        </p>
        <p className="mb-6 text-center text-[13px] text-slate-600">
          For your privacy, this page only confirms your ballot was counted. It never
          shows who you voted for.
        </p>

        <form onSubmit={handleSubmit} noValidate className="space-y-5">
          <div>
            <label htmlFor="receipt" className="mb-1 block font-semibold text-[18px]">
              Receipt code
            </label>
            <input
              id="receipt"
              name="receipt"
              type="text"
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="XXXX-XXXX-XXXX-XXXX"
              value={formatReceipt(receipt)}
              onChange={(e) => handleChange(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby="receipt-help"
              className="w-full rounded border border-slate-400 px-3 py-2 text-center font-mono text-[22px] font-semibold tracking-[0.15em] placeholder:text-slate-300 focus:outline-none focus:ring-2 focus:ring-[#1f538d]"
            />
            <p id="receipt-help" className="mt-1 text-[13px] text-slate-600">
              {RECEIPT_LENGTH} letters and numbers. Dashes are added for you.
            </p>
            {warning && (
              <p
                role="status"
                className="mt-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-[13px] text-amber-800"
              >
                {warning}
              </p>
            )}
          </div>

          {error && (
            <p
              role="alert"
              className="rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
            >
              {error}
            </p>
          )}

          {record && (
            <div
              role="status"
              className="rounded border border-green-300 bg-green-50 px-4 py-3 text-green-800"
            >
              <p className="mb-1 font-bold">&#10004; Your ballot was recorded</p>
              <p className="text-[13px]">
                Received on {formatDateTime(record.recordedAt)}.
              </p>
              <p className="text-[13px]">
                {record.includedInTally
                  ? "It is included in the published results."
                  : "It will be included when the results are published."}
              </p>
            </div>
          )}

          <button
            type="submit"
            disabled={checking}
            className="w-full rounded-lg bg-[#1f538d] px-6 py-3 text-[24px] font-bold text-white shadow-[0_8px_20px_rgba(0,0,0,0.35)] transition duration-200 hover:-translate-y-1 hover:bg-[#1b4779] hover:shadow-[0_14px_28px_rgba(0,0,0,0.4)] active:translate-y-0 active:shadow-[0_4px_10px_rgba(0,0,0,0.3)] disabled:cursor-not-allowed disabled:opacity-70"
          >
            {checking ? "Checking..." : "Verify"}
          </button>
        </form>

        <div className="mt-6 flex items-center justify-between">
          <Link
            href="/results"
            className="text-[13px] capitalize text-[#1b4779] hover:underline"
          >
            View published results
          </Link>
          <Link
            href="/"
            className="text-[13px] capitalize text-[#1b4779] hover:underline"
          >
            Back to start page
          </Link>
        </div>
      </div>
    </div>
  );
}
