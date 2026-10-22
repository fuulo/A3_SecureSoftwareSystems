"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { mainHeader, buttonStyle } from "../../components/styles";

// Settings (change them here)
const MIN_AGE = 18;
const MIN_PASSWORD_LENGTH = 6;
const GOV_ID_PATTERN = /^[A-Za-z0-9]{6,20}$/; // letters and numbers, 6 to 20 characters
const MIN_ADDRESS_LENGTH = 10;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/; // something@something.something

type Step = "form" | "done";

const emptyForm = {
  givenName: "",
  surname: "",
  dob: "",
  govId: "",
  address: "",
  email: "",
  password: "",
  confirmPassword: "",
};

// Reusable styles
const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";
const linkStyle = "text-[13px] capitalize text-[#1b4779] hover:underline";

// Work out age in years from a date of birth written as "YYYY-MM-DD"
function getAge(dob: string): number | null {
  const [year, month, day] = dob.split("-").map(Number);
  if (!year || !month || !day || year < 1900) return null;

  const date = new Date(year, month - 1, day);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  const today = new Date();
  let age = today.getFullYear() - year;
  const beforeBirthday =
    today.getMonth() + 1 < month ||
    (today.getMonth() + 1 === month && today.getDate() < day);
  if (beforeBirthday) age -= 1;
  return age;
}

// Latest allowed date of birth (today minus MIN_AGE years), as "YYYY-MM-DD"
function getLatestDob(): string {
  const date = new Date();
  date.setFullYear(date.getFullYear() - MIN_AGE);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export default function CreateAccountPage() {
  const [step, setStep] = useState<Step>("form");
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const dobRef = useRef<HTMLInputElement>(null);

// Set the latest allowed date of birth in the browser, after the page loads
useEffect(() => {
  if (dobRef.current) dobRef.current.max = getLatestDob();
}, []);

  // Clear the page when it is shown again by back/forward navigation,
  // so no personal details stay on screen
  useEffect(() => {
    function resetPage() {
      setStep("form");
      setForm(emptyForm);
      setError("");
    }

    window.addEventListener("pageshow", resetPage);
    return () => window.removeEventListener("pageshow", resetPage);
  }, []);

  function handleChange(
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) {
    const { name, value } = event.target;
    setForm((previous) => ({ ...previous, [name]: value }));
  }

  // Returns an error message, or an empty string if everything is fine
  function validate(): string {
    if (
      !form.givenName.trim() ||
      !form.surname.trim() ||
      !form.dob ||
      !form.govId.trim() ||
      !form.address.trim() ||
      !form.email.trim() ||
      !form.password ||
      !form.confirmPassword
    ) {
      return "Please fill in all the fields.";
    }

    const age = getAge(form.dob);
    if (age === null || age < 0 || age > 120) {
      return "Please enter a valid date of birth.";
    }
    if (age < MIN_AGE) {
      return `You must be at least ${MIN_AGE} years old to create a voter account.`;
    }

    if (!GOV_ID_PATTERN.test(form.govId.replace(/\s/g, ""))) {
      return "Please enter a valid GovID (letters and numbers only).";
    }

    if (form.address.trim().length < MIN_ADDRESS_LENGTH) {
      return "Please enter your full residential address.";
    }

    if (!EMAIL_PATTERN.test(form.email.trim())) {
      return "Please enter a valid email address.";
    }

    if (form.password.length < MIN_PASSWORD_LENGTH) {
      return `Your password must have at least ${MIN_PASSWORD_LENGTH} characters.`;
    }
    if (form.password !== form.confirmPassword) {
      return "The two passwords do not match.";
    }

    return "";
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setError("");

    setForm(emptyForm);
    setStep("done");
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <div className="w-full max-w-xl rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        {step === "form" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Create Voter Account
            </h1>
            <p className="mb-4 text-center">
              Enter your details below to create your voter account.
            </p>

            <form onSubmit={handleSubmit} noValidate className="space-y-5">
              <div className="grid gap-5 sm:grid-cols-2">
                <div>
                  <label
                    htmlFor="givenName"
                    className="mb-1 block font-semibold"
                  >
                    Given name
                  </label>
                  <input
                    id="givenName"
                    name="givenName"
                    type="text"
                    autoComplete="given-name"
                    maxLength={50}
                    placeholder="e.g. Alex"
                    required
                    value={form.givenName}
                    onChange={handleChange}
                    className={inputStyle}
                  />
                </div>

                <div>
                  <label htmlFor="surname" className="mb-1 block font-semibold">
                    Surname
                  </label>
                  <input
                    id="surname"
                    name="surname"
                    type="text"
                    autoComplete="family-name"
                    maxLength={50}
                    placeholder="e.g. Smith"
                    required
                    value={form.surname}
                    onChange={handleChange}
                    className={inputStyle}
                  />
                </div>
              </div>

              <div>
                <label htmlFor="dob" className="mb-1 block font-semibold">
                  Date of birth
                </label>
                    <input
                    id="dob"
                    name="dob"
                    type="date"
                    autoComplete="bday"
                    min="1900-01-01"
                    required
                    ref={dobRef}
                    value={form.dob}
                    onChange={handleChange}
                    className={`${inputStyle} [color-scheme:light]`}
                    />
                <p className="mt-1 text-[13px] text-slate-600">
                  Select your date of birth using the date picker.
                </p>
              </div>

              <div>
                <label htmlFor="govId" className="mb-1 block font-semibold">
                  GovID
                </label>
                <input
                  id="govId"
                  name="govId"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  maxLength={20}
                  placeholder="e.g. A1234567"
                  required
                  aria-describedby="govId-help"
                  value={form.govId}
                  onChange={handleChange}
                  className={inputStyle}
                />
                <p id="govId-help" className="mt-1 text-[13px] text-slate-600">
                  For example, a driver licence or passport number. Letters and
                  numbers only.
                </p>
              </div>

              <div>
                <label htmlFor="address" className="mb-1 block font-semibold">
                  Residential address
                </label>
                <textarea
                  id="address"
                  name="address"
                  rows={3}
                  autoComplete="street-address"
                  maxLength={200}
                  placeholder="e.g. 10 Example Street, Sampletown"
                  required
                  value={form.address}
                  onChange={handleChange}
                  className={`${inputStyle} resize-none`}
                />
              </div>

              <div>
                <label htmlFor="email" className="mb-1 block font-semibold">
                    Email address
                </label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  inputMode="email"
                  maxLength={254}
                  placeholder="e.g. alex@example.com"
                  required
                  aria-describedby="email-help"
                  value={form.email}
                  onChange={handleChange}
                  className={inputStyle}
                />
                <p id="email-help" className="mt-1 text-[13px] text-slate-600">
                  In a live service, verification and password reset codes
                  would be sent to this address.
                </p>
              </div>

              <div>
                <label htmlFor="password" className="mb-1 block font-semibold">
                  Password
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
                  required
                  value={form.password}
                  onChange={handleChange}
                  aria-describedby="password-help"
                  className={inputStyle}
                />
                <p id="password-help" className="mt-1 text-[13px] text-slate-600">
                  Use at least {MIN_PASSWORD_LENGTH} characters.
                </p>
              </div>

              <div>
                <label
                  htmlFor="confirmPassword"
                  className="mb-1 block font-semibold"
                >
                  Confirm password
                </label>
                <input
                  id="confirmPassword"
                  name="confirmPassword"
                  type="password"
                  autoComplete="new-password"
                  placeholder="Re-enter your password"
                  required
                  value={form.confirmPassword}
                  onChange={handleChange}
                  className={inputStyle}
                />
              </div>

              {error && (
                <p
                  role="alert"
                  className="rounded border border-red-300 bg-red-50 px-3 py-2 text-[13px] text-red-700"
                >
                  {error}
                </p>
              )}

              <button type="submit" className={buttonStyle}>
                Create account
              </button>
            </form>

            <div className="mt-6 text-center">
              <Link href="/login" className={linkStyle}>
                Back to login
              </Link>
            </div>
          </>
        )}

        {step === "done" && (
          <>
            <h1 className={`${mainHeader} mb-2 text-center`}>
              Demo Submission Complete
            </h1>
            <p className="mb-6 text-center">
              This is a demonstration only. Your details were not sent or saved,
              and no account was created.
            </p>
            <Link href="/login" className={`${buttonStyle} block text-center`}>
              Go to login
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
