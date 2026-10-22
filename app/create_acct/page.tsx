"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createUserWithEmailAndPassword } from "firebase/auth";
import {
  doc,
  serverTimestamp,
  setDoc,
} from "firebase/firestore";
import { useRouter } from "next/navigation";
import { auth, db } from "@/lib/firebase";
import {
  mainHeader,
  buttonStyle,
} from "@/components/styles";

const MIN_AGE = 18;
const MIN_PASSWORD_LENGTH = 6;
const MIN_ADDRESS_LENGTH = 10;

const NAME_PATTERN =
  /^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$/;

const GOV_ID_PATTERN =
  /^[A-Za-z0-9]{6,20}$/;

const EMAIL_PATTERN =
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const ADDRESS_LETTER_PATTERN =
  /[A-Za-zÀ-ÖØ-öø-ÿ]/;

type Step = "form" | "done";

type FormData = {
  givenName: string;
  surname: string;
  dob: string;
  govId: string;
  address: string;
  email: string;
  password: string;
  confirmPassword: string;
};

type FormErrors = Partial<
  Record<keyof FormData, string>
>;

const emptyForm: FormData = {
  givenName: "",
  surname: "",
  dob: "",
  govId: "",
  address: "",
  email: "",
  password: "",
  confirmPassword: "",
};

const inputStyle =
  "w-full rounded border border-slate-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

const linkStyle =
  "text-[13px] text-[#1b4779] hover:underline";

function getAge(dob: string): number | null {
  const [year, month, day] = dob
    .split("-")
    .map(Number);

  if (!year || !month || !day || year < 1900) {
    return null;
  }

  const date = new Date(
    year,
    month - 1,
    day
  );

  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null;
  }

  const today = new Date();

  let age =
    today.getFullYear() - year;

  const beforeBirthday =
    today.getMonth() + 1 < month ||
    (today.getMonth() + 1 === month &&
      today.getDate() < day);

  if (beforeBirthday) {
    age -= 1;
  }

  return age;
}

function getLatestDob(): string {
  const date = new Date();

  date.setFullYear(
    date.getFullYear() - MIN_AGE
  );

  const pad = (number: number) =>
    String(number).padStart(2, "0");

  return `${date.getFullYear()}-${pad(
    date.getMonth() + 1
  )}-${pad(date.getDate())}`;
}

function getFirebaseErrorMessage(
  firebaseError: unknown
): string {
  if (
    typeof firebaseError === "object" &&
    firebaseError !== null &&
    "code" in firebaseError
  ) {
    const code = String(
      (firebaseError as { code?: unknown }).code ??
        ""
    );

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
      return "Email and password registration is not enabled in Firebase.";
    }

    if (code === "permission-denied") {
      return "The account was created, but the user profile could not be saved.";
    }
  }

  return "Unable to create the account. Please try again.";
}

export default function CreateAccountPage() {
  const router = useRouter();
  const dobRef = useRef<HTMLInputElement>(null);

  const [step, setStep] =
    useState<Step>("form");

  const [form, setForm] =
    useState<FormData>(emptyForm);

  const [fieldErrors, setFieldErrors] =
    useState<FormErrors>({});

  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] =
    useState(false);

  useEffect(() => {
    if (dobRef.current) {
      dobRef.current.max = getLatestDob();
    }
  }, []);

  function handleChange(
    event: React.ChangeEvent<
      HTMLInputElement | HTMLTextAreaElement
    >
  ) {
    const { name, value } = event.target;

    setForm((previous) => ({
      ...previous,
      [name]: value,
    }));

    setFieldErrors((previous) => ({
      ...previous,
      [name as keyof FormData]: "",
    }));

    setError("");
  }

  function validate(): FormErrors {
    const errors: FormErrors = {};

    if (!form.givenName.trim()) {
      errors.givenName =
        "Please enter your given name.";
    } else if (
      !NAME_PATTERN.test(form.givenName.trim())
    ) {
      errors.givenName =
        "Given name can contain letters, spaces, apostrophes and hyphens only.";
    }

    if (!form.surname.trim()) {
      errors.surname =
        "Please enter your surname.";
    } else if (
      !NAME_PATTERN.test(form.surname.trim())
    ) {
      errors.surname =
        "Surname can contain letters, spaces, apostrophes and hyphens only.";
    }

    if (!form.dob) {
      errors.dob =
        "Please select your date of birth.";
    } else {
      const age = getAge(form.dob);

      if (
        age === null ||
        age < 0 ||
        age > 120
      ) {
        errors.dob =
          "Please enter a valid date of birth.";
      } else if (age < MIN_AGE) {
        errors.dob = `You must be at least ${MIN_AGE} years old.`;
      }
    }

    const cleanedGovId = form.govId
      .replace(/\s/g, "")
      .trim();

    if (!cleanedGovId) {
      errors.govId =
        "Please enter your GovID.";
    } else if (
      !GOV_ID_PATTERN.test(cleanedGovId)
    ) {
      errors.govId =
        "GovID must contain only letters and numbers, between 6 and 20 characters.";
    }

    const trimmedAddress = form.address.trim();

    if (!trimmedAddress) {
      errors.address =
        "Please enter your residential address.";
    } else if (
      trimmedAddress.length <
      MIN_ADDRESS_LENGTH
    ) {
      errors.address =
        "Please enter your full residential address.";
    } else if (
      !ADDRESS_LETTER_PATTERN.test(
        trimmedAddress
      )
    ) {
      errors.address =
        "Please enter a valid residential address.";
    }

    if (!form.email.trim()) {
      errors.email =
        "Please enter your email address.";
    } else if (
      !EMAIL_PATTERN.test(form.email.trim())
    ) {
      errors.email =
        "Please enter a valid email address.";
    }

    if (!form.password) {
      errors.password =
        "Please enter a password.";
    } else if (
      form.password.length <
      MIN_PASSWORD_LENGTH
    ) {
      errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
    }

    if (!form.confirmPassword) {
      errors.confirmPassword =
        "Please confirm your password.";
    } else if (
      form.password !== form.confirmPassword
    ) {
      errors.confirmPassword =
        "The passwords do not match.";
    }

    return errors;
  }

  async function handleSubmit(
    event: React.FormEvent<HTMLFormElement>
  ) {
    event.preventDefault();

    const errors = validate();

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setError(
        "Please correct the highlighted fields."
      );
      return;
    }

    setFieldErrors({});
    setError("");
    setIsSubmitting(true);

    try {
      const email = form.email
        .trim()
        .toLowerCase();

      const credential =
        await createUserWithEmailAndPassword(
          auth,
          email,
          form.password
        );

      await setDoc(
        doc(db, "users", credential.user.uid),
        {
          givenName: form.givenName.trim(),
          surname: form.surname.trim(),
          dob: form.dob,
          govId: form.govId
            .replace(/\s/g, "")
            .trim(),
          address: form.address.trim(),
          email,
          role: "voter",
          hasVoted: false,
          enrolmentStatus: "not-enrolled",
          eligibilityStatus: "pending",
          createdAt: serverTimestamp(),
        }
      );

      setForm(emptyForm);
      setStep("done");
    } catch (firebaseError) {
      console.error(firebaseError);
      setError(
        getFirebaseErrorMessage(firebaseError)
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  if (step === "done") {
    return (
      <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
        <section className="w-full max-w-md rounded-lg border border-slate-300 bg-white p-8 text-center shadow-lg">
          <h1 className={`${mainHeader} mb-4`}>
            Account Created
          </h1>

          <p className="mb-6 text-slate-700">
            Your voter account has been created
            successfully.
          </p>

          <Link
            href="/login"
            className={`${buttonStyle} inline-block`}
          >
            Go to login
          </Link>
        </section>
      </main>
    );
  }

  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <section className="w-full max-w-2xl rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1 className={`${mainHeader} mb-2 text-center`}>
          Create Voter Account
        </h1>

        <p className="mb-8 text-center text-slate-600">
          Enter your details below to create your
          voter account.
        </p>

        <form
          onSubmit={handleSubmit}
          noValidate
          className="space-y-5"
        >
          <div className="grid gap-5 md:grid-cols-2">
            <div>
              <label
                htmlFor="givenName"
                className="mb-1 block font-semibold"
              >
                First name
              </label>

              <input
                id="givenName"
                name="givenName"
                type="text"
                autoComplete="given-name"
                required
                value={form.givenName}
                onChange={handleChange}
                className={`${inputStyle} ${
                  fieldErrors.givenName
                    ? "border-red-500"
                    : ""
                }`}
              />

              {fieldErrors.givenName && (
                <p className="mt-1 text-xs text-red-700">
                  {fieldErrors.givenName}
                </p>
              )}
            </div>

            <div>
              <label
                htmlFor="surname"
                className="mb-1 block font-semibold"
              >
                Last name
              </label>

              <input
                id="surname"
                name="surname"
                type="text"
                autoComplete="family-name"
                required
                value={form.surname}
                onChange={handleChange}
                className={`${inputStyle} ${
                  fieldErrors.surname
                    ? "border-red-500"
                    : ""
                }`}
              />

              {fieldErrors.surname && (
                <p className="mt-1 text-xs text-red-700">
                  {fieldErrors.surname}
                </p>
              )}
            </div>
          </div>

          <div>
            <label
              htmlFor="dob"
              className="mb-1 block font-semibold"
            >
              Date of birth
            </label>

            <input
              ref={dobRef}
              id="dob"
              name="dob"
              type="date"
              required
              value={form.dob}
              onChange={handleChange}
              className={`${inputStyle} ${
                fieldErrors.dob
                  ? "border-red-500"
                  : ""
              }`}
            />

            {fieldErrors.dob && (
              <p className="mt-1 text-xs text-red-700">
                {fieldErrors.dob}
              </p>
            )}

            <p className="mt-1 text-xs text-slate-500">
              You must be at least {MIN_AGE} years old.
            </p>
          </div>

          <div>
            <label
              htmlFor="govId"
              className="mb-1 block font-semibold"
            >
              GovID
            </label>

            <input
              id="govId"
              name="govId"
              type="text"
              autoComplete="off"
              required
              value={form.govId}
              onChange={handleChange}
              className={`${inputStyle} ${
                fieldErrors.govId
                  ? "border-red-500"
                  : ""
              }`}
            />

            {fieldErrors.govId && (
              <p className="mt-1 text-xs text-red-700">
                {fieldErrors.govId}
              </p>
            )}

            <p className="mt-1 text-xs text-slate-500">
              Use letters and numbers only.
            </p>
          </div>

          <div>
            <label
              htmlFor="address"
              className="mb-1 block font-semibold"
            >
              Residential address
            </label>

            <textarea
              id="address"
              name="address"
              autoComplete="street-address"
              required
              rows={3}
              value={form.address}
              onChange={handleChange}
              className={`${inputStyle} ${
                fieldErrors.address
                  ? "border-red-500"
                  : ""
              }`}
            />

            {fieldErrors.address && (
              <p className="mt-1 text-xs text-red-700">
                {fieldErrors.address}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="email"
              className="mb-1 block font-semibold"
            >
              Email address
            </label>

            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={form.email}
              onChange={handleChange}
              className={`${inputStyle} ${
                fieldErrors.email
                  ? "border-red-500"
                  : ""
              }`}
            />

            {fieldErrors.email && (
              <p className="mt-1 text-xs text-red-700">
                {fieldErrors.email}
              </p>
            )}

            <p className="mt-1 text-xs text-slate-500">
              Verification and password-reset instructions
              may be sent to this address.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <div>
              <label
                htmlFor="password"
                className="mb-1 block font-semibold"
              >
                Password
              </label>

              <input
                id="password"
                name="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={MIN_PASSWORD_LENGTH}
                value={form.password}
                onChange={handleChange}
                className={`${inputStyle} ${
                  fieldErrors.password
                    ? "border-red-500"
                    : ""
                }`}
              />

              {fieldErrors.password && (
                <p className="mt-1 text-xs text-red-700">
                  {fieldErrors.password}
                </p>
              )}

              <p className="mt-1 text-xs text-slate-500">
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
                required
                minLength={MIN_PASSWORD_LENGTH}
                value={form.confirmPassword}
                onChange={handleChange}
                className={`${inputStyle} ${
                  fieldErrors.confirmPassword
                    ? "border-red-500"
                    : ""
                }`}
              />

              {fieldErrors.confirmPassword && (
                <p className="mt-1 text-xs text-red-700">
                  {fieldErrors.confirmPassword}
                </p>
              )}
            </div>
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
            className={`${buttonStyle} w-full disabled:cursor-not-allowed disabled:opacity-60`}
          >
            {isSubmitting
              ? "Creating account..."
              : "Create account"}
          </button>
        </form>

        <div className="mt-6 flex flex-wrap justify-between gap-3">
          <Link
            href="/login"
            className={linkStyle}
          >
            Back to login
          </Link>

          <Link
            href="/"
            className={linkStyle}
          >
            Back to home page
          </Link>
        </div>
      </section>
    </main>
  );
}