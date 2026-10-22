"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { createUserWithEmailAndPassword } from "firebase/auth";
import { doc, serverTimestamp, setDoc } from "firebase/firestore";
import { auth, db } from "@/lib/firebase";
import { mainHeader, buttonStyle } from "../../components/styles";

const MIN_AGE = 18;
const MIN_PASSWORD_LENGTH = 6;
const MIN_ADDRESS_LENGTH = 10;

const NAME_PATTERN = /^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$/;
const GOV_ID_PATTERN = /^[A-Za-z0-9]{6,20}$/;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const ADDRESS_LETTER_PATTERN = /[A-Za-zÀ-ÖØ-öø-ÿ]/;

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

type FormErrors = Partial<Record<keyof typeof emptyForm, string>>;

const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

const linkStyle = "text-[13px] capitalize text-[#1b4779] hover:underline";

function getAge(dob: string): number | null {
  const [year, month, day] = dob.split("-").map(Number);

  if (!year || !month || !day || year < 1900) {
    return null;
  }

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

  if (beforeBirthday) {
    age -= 1;
  }

  return age;
}

function getLatestDob(): string {
  const date = new Date();
  date.setFullYear(date.getFullYear() - MIN_AGE);

  const pad = (number: number) => String(number).padStart(2, "0");

  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate()
  )}`;
}

export default function CreateAccountPage() {
  const [step, setStep] = useState<Step>("form");
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const dobRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (dobRef.current) {
      dobRef.current.max = getLatestDob();
    }
  }, []);

  function handleChange(
    event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) {
    const { name, value } = event.target;

    setForm((previous) => ({
      ...previous,
      [name]: value,
    }));

    setFieldErrors((previous) => ({
      ...previous,
      [name as keyof typeof emptyForm]: "",
    }));

    setError("");
  }


  function fieldClass(field: keyof typeof emptyForm) {
    return `${inputStyle} ${
      fieldErrors[field] ? "border-red-500" : ""
    }`;
  }

  function validate(): FormErrors {
    const errors: FormErrors = {};

    if (!form.givenName.trim()) {
      errors.givenName = "Please enter your given name.";
    } else if (!NAME_PATTERN.test(form.givenName.trim())) {
      errors.givenName =
        "Given name can contain letters, spaces, apostrophes and hyphens only.";
    }

    if (!form.surname.trim()) {
      errors.surname = "Please enter your surname.";
    } else if (!NAME_PATTERN.test(form.surname.trim())) {
      errors.surname =
        "Surname can contain letters, spaces, apostrophes and hyphens only.";
    }

    if (!form.dob) {
      errors.dob = "Please select your date of birth.";
    } else {
      const age = getAge(form.dob);

      if (age === null || age < 0 || age > 120) {
        errors.dob = "Please enter a valid date of birth.";
      } else if (age < MIN_AGE) {
        errors.dob = `You must be at least ${MIN_AGE} years old.`;
      }
    }

    if (!form.govId.trim()) {
      errors.govId = "Please enter your GovID.";
    } else if (!GOV_ID_PATTERN.test(form.govId.replace(/\s/g, ""))) {
      errors.govId =
        "GovID must contain only letters and numbers, between 6 and 20 characters.";
    }

    if (!form.address.trim()) {
      errors.address = "Please enter your residential address.";
    } else if (form.address.trim().length < MIN_ADDRESS_LENGTH) {
      errors.address = "Please enter your full residential address.";
    } else if (!ADDRESS_LETTER_PATTERN.test(form.address.trim())) {
      errors.address = "Please enter a valid residential address.";
    }

    if (!form.email.trim()) {
      errors.email = "Please enter your email address.";
    } else if (!EMAIL_PATTERN.test(form.email.trim())) {
      errors.email = "Please enter a valid email address.";
    }

    if (!form.password) {
      errors.password = "Please enter a password.";
    } else if (form.password.length < MIN_PASSWORD_LENGTH) {
      errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
    }

    if (!form.confirmPassword) {
      errors.confirmPassword = "Please confirm your password.";
    } else if (form.password !== form.confirmPassword) {
      errors.confirmPassword = "The passwords do not match.";
    }

    return errors;
  }

  function getFirebaseErrorMessage(firebaseError: unknown): string {
    if (
      typeof firebaseError === "object" &&
      firebaseError !== null &&
      "code" in firebaseError
    ) {
      const code = String(firebaseError.code);

      if (code === "auth/email-already-in-use") {
        return "This email address is already registered.";
      }

      if (code === "auth/invalid-email") {
        return "Please enter a valid email address.";
      }

      if (code === "auth/weak-password") {
        return "Please choose a stronger password.";
      }

      if (code === "auth/operation-not-allowed") {
        return "Email and password registration is not enabled.";
      }

      if (code === "permission-denied") {
        return "The account was created, but the user profile could not be saved.";
      }
    }

    return "Unable to create the account. Please try again.";
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const errors = validate();

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setError("Please correct the highlighted fields.");
      return;
    }

    setFieldErrors({});
    setError("");
    setIsSubmitting(true);

    try {
      const credential = await createUserWithEmailAndPassword(
        auth,
        form.email.trim(),
        form.password
      );

      await setDoc(doc(db, "users", credential.user.uid), {
        givenName: form.givenName.trim(),
        surname: form.surname.trim(),
        dob: form.dob,
        govId: form.govId.trim(),
        address: form.address.trim(),
        email: form.email.trim(),
        role: "voter",
        hasVoted: false,
        enrolmentStatus: "not-enrolled",
        eligibilityStatus: "pending",
        createdAt: serverTimestamp(),
      });

      setForm(emptyForm);
      setStep("done");
    } catch (firebaseError) {
      console.error(firebaseError);
      setError(getFirebaseErrorMessage(firebaseError));
    } finally {
      setIsSubmitting(false);
    }
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
                    pattern="[A-Za-zÀ-ÖØ-öø-ÿ' -]+"
                    title="Use letters, spaces, apostrophes and hyphens only."
                    value={form.givenName}
                    onChange={handleChange}
                    aria-invalid={Boolean(fieldErrors.givenName)}
                    aria-describedby="givenName-error"
                    className={fieldClass("givenName")}
                  />

                  {fieldErrors.givenName && (
                    <p
                      id="givenName-error"
                      className="mt-1 text-[13px] text-red-700"
                      role="alert"
                    >
                      {fieldErrors.givenName}
                    </p>
                  )}
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
                    pattern="[A-Za-zÀ-ÖØ-öø-ÿ' -]+"
                    title="Use letters, spaces, apostrophes and hyphens only."
                    value={form.surname}
                    onChange={handleChange}
                    aria-invalid={Boolean(fieldErrors.surname)}
                    aria-describedby="surname-error"
                    className={fieldClass("surname")}
                  />

                  {fieldErrors.surname && (
                    <p
                      id="surname-error"
                      className="mt-1 text-[13px] text-red-700"
                      role="alert"
                    >
                      {fieldErrors.surname}
                    </p>
                  )}
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
                  aria-invalid={Boolean(fieldErrors.dob)}
                  aria-describedby="dob-error"
                  className={`${fieldClass("dob")} [color-scheme:light]`}
                />

                {fieldErrors.dob && (
                  <p
                    id="dob-error"
                    className="mt-1 text-[13px] text-red-700"
                    role="alert"
                  >
                    {fieldErrors.dob}
                  </p>
                )}

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
                  value={form.govId}
                  onChange={handleChange}
                  aria-invalid={Boolean(fieldErrors.govId)}
                  aria-describedby="govId-error"
                  className={fieldClass("govId")}
                />

                {fieldErrors.govId && (
                  <p
                    id="govId-error"
                    className="mt-1 text-[13px] text-red-700"
                    role="alert"
                  >
                    {fieldErrors.govId}
                  </p>
                )}

                <p className="mt-1 text-[13px] text-slate-600">
                  Use letters and numbers only.
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
                  aria-invalid={Boolean(fieldErrors.address)}
                  aria-describedby="address-error"
                  className={`${fieldClass("address")} resize-none`}
                />

                {fieldErrors.address && (
                  <p
                    id="address-error"
                    className="mt-1 text-[13px] text-red-700"
                    role="alert"
                  >
                    {fieldErrors.address}
                  </p>
                )}
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
                  value={form.email}
                  onChange={handleChange}
                  aria-invalid={Boolean(fieldErrors.email)}
                  aria-describedby="email-error"
                  className={fieldClass("email")}
                />

                {fieldErrors.email && (
                  <p
                    id="email-error"
                    className="mt-1 text-[13px] text-red-700"
                    role="alert"
                  >
                    {fieldErrors.email}
                  </p>
                )}

                <p className="mt-1 text-[13px] text-slate-600">
                  Verification and password-reset instructions may be sent to
                  this address.
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
                  aria-invalid={Boolean(fieldErrors.password)}
                  aria-describedby="password-error"
                  className={fieldClass("password")}
                />

                {fieldErrors.password && (
                  <p
                    id="password-error"
                    className="mt-1 text-[13px] text-red-700"
                    role="alert"
                  >
                    {fieldErrors.password}
                  </p>
                )}

                <p className="mt-1 text-[13px] text-slate-600">
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
                  aria-invalid={Boolean(fieldErrors.confirmPassword)}
                  aria-describedby="confirmPassword-error"
                  className={fieldClass("confirmPassword")}
                />

                {fieldErrors.confirmPassword && (
                  <p
                    id="confirmPassword-error"
                    className="mt-1 text-[13px] text-red-700"
                    role="alert"
                  >
                    {fieldErrors.confirmPassword}
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

              <button
                type="submit"
                disabled={isSubmitting}
                className={`${buttonStyle} ${
                  isSubmitting ? "cursor-not-allowed opacity-60" : ""
                }`}
              >
                {isSubmitting ? "Creating account..." : "Create account"}
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
              Account Created
            </h1>

            <p className="mb-6 text-center">
              Your voter account has been created successfully.
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