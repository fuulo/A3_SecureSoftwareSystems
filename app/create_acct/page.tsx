"use client";

import Link from "next/link";
import { useLayoutEffect, useState } from "react";
import {
  createUserWithEmailAndPassword,
  sendEmailVerification,
  type User,
} from "firebase/auth";
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
const EARLIEST_YEAR = 1900;

const NAME_PATTERN =
  /^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$/;

const GOV_ID_PATTERN =
  /^[A-Za-z0-9]{6,20}$/;

const EMAIL_PATTERN =
  /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const ADDRESS_LETTER_PATTERN =
  /[A-Za-zÀ-ÖØ-öø-ÿ]/;

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

const selectStyle =
  "w-full rounded border border-slate-400 bg-white px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[#1f538d]";

const linkStyle =
  "text-[13px] text-[#1b4779] hover:underline";

const months = [
  { value: "01", label: "January" },
  { value: "02", label: "February" },
  { value: "03", label: "March" },
  { value: "04", label: "April" },
  { value: "05", label: "May" },
  { value: "06", label: "June" },
  { value: "07", label: "July" },
  { value: "08", label: "August" },
  { value: "09", label: "September" },
  { value: "10", label: "October" },
  { value: "11", label: "November" },
  { value: "12", label: "December" },
];

function getDaysInMonth(
  year: number,
  month: number
): number {
  if (!year || !month) {
    return 31;
  }

  return new Date(year, month, 0).getDate();
}

function getAge(dob: string): number | null {
  const [year, month, day] = dob
    .split("-")
    .map(Number);

  if (
    !year ||
    !month ||
    !day ||
    year < EARLIEST_YEAR
  ) {
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

function getFirebaseErrorMessage(
  firebaseError: unknown
): string {
  if (
    typeof firebaseError === "object" &&
    firebaseError !== null &&
    "code" in firebaseError
  ) {
    const code = String(
      (firebaseError as { code?: unknown })
        .code ?? ""
    );

    if (
      code === "auth/email-already-in-use"
    ) {
      return "This email address is already registered.";
    }

    if (code === "auth/invalid-email") {
      return "Please enter a valid email address.";
    }

    if (code === "auth/weak-password") {
      return "Please choose a stronger password.";
    }

    if (
      code === "auth/operation-not-allowed"
    ) {
      return "Email and password registration is not enabled in Firebase.";
    }

    if (code === "permission-denied") {
      return "The account was created, but the user profile could not be saved.";
    }

    if (
      code === "auth/too-many-requests"
    ) {
      return "Too many attempts. Please wait and try again.";
    }
  }

  return "Unable to create the account. Please try again.";
}

export default function CreateAccountPage() {
  const router = useRouter();

  const [form, setForm] =
    useState<FormData>(emptyForm);

  const [selectedDay, setSelectedDay] =
    useState("");

  const [selectedMonth, setSelectedMonth] =
    useState("");

  const [selectedYear, setSelectedYear] =
    useState("");

  const [fieldErrors, setFieldErrors] =
    useState<FormErrors>({});

  const [error, setError] =
    useState("");

  const [isSubmitting, setIsSubmitting] =
    useState(false);

  // Next.js keeps this page mounted but hidden after navigating away
  // (cacheComponents), so clear the passwords and personal details
  useLayoutEffect(() => {
    return () => {
      setForm(emptyForm);
      setSelectedDay("");
      setSelectedMonth("");
      setSelectedYear("");
      setFieldErrors({});
      setError("");
      setIsSubmitting(false);
    };
  }, []);

  const latestAllowedYear =
    new Date().getFullYear() - MIN_AGE;

  const selectedYearNumber =
    Number(selectedYear);

  const selectedMonthNumber =
    Number(selectedMonth);

  const daysInSelectedMonth =
    getDaysInMonth(
      selectedYearNumber,
      selectedMonthNumber
    );

  const days = Array.from(
    {
      length: daysInSelectedMonth,
    },
    (_, index) =>
      String(index + 1).padStart(2, "0")
  );

  const years = Array.from(
    {
      length:
        latestAllowedYear -
        EARLIEST_YEAR +
        1,
    },
    (_, index) =>
      latestAllowedYear - index
  );

  function updateDateOfBirth(
    day: string,
    month: string,
    year: string
  ) {
    let validDay = day;

    if (month && year && day) {
      const numberOfDays =
        getDaysInMonth(
          Number(year),
          Number(month)
        );

      if (Number(day) > numberOfDays) {
        validDay = "";
      }
    }

    setSelectedDay(validDay);
    setSelectedMonth(month);
    setSelectedYear(year);

    if (
      validDay &&
      month &&
      year
    ) {
      setForm((previous) => ({
        ...previous,
        dob: `${year}-${month}-${validDay}`,
      }));
    } else {
      setForm((previous) => ({
        ...previous,
        dob: "",
      }));
    }

    setFieldErrors((previous) => ({
      ...previous,
      dob: "",
    }));

    setError("");
  }

  function handleDateChange(
    field: "day" | "month" | "year",
    value: string
  ) {
    const nextDay =
      field === "day"
        ? value
        : selectedDay;

    const nextMonth =
      field === "month"
        ? value
        : selectedMonth;

    const nextYear =
      field === "year"
        ? value
        : selectedYear;

    updateDateOfBirth(
      nextDay,
      nextMonth,
      nextYear
    );
  }

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

  function fieldClass(
    field: keyof FormData
  ) {
    return `${inputStyle} ${
      fieldErrors[field]
        ? "border-red-500"
        : ""
    }`;
  }

  function selectClass(
    field: keyof FormData
  ) {
    return `${selectStyle} ${
      fieldErrors[field]
        ? "border-red-500"
        : ""
    }`;
  }

  // Step 2 of the account journey: save the profile, then send the
  // verification email. The phone number is added later, on /mfa_setup,
  // because Firebase only allows it after the email is verified.
  async function finishAccountSetup(user: User) {
    const email = form.email.trim().toLowerCase();

    await setDoc(
      doc(db, "users", user.uid),
      {
        givenName: form.givenName.trim(),
        surname: form.surname.trim(),
        dob: form.dob,
        govId: form.govId.replace(/\s/g, "").trim(),
        address: form.address.trim(),
        email,
        role: "voter",
        hasVoted: false,
        enrolmentStatus: "not-enrolled",
        eligibilityStatus: "pending",
        emailVerified: false,
        createdAt: serverTimestamp(),
      }
    );

    await sendEmailVerification(user);
    router.replace("/email_verification");
  }

  function validate(): FormErrors {
    const errors: FormErrors = {};

    const givenName =
      form.givenName.trim();

    const surname =
      form.surname.trim();

    const govId = form.govId
      .replace(/\s/g, "")
      .trim();

    const address =
      form.address.trim();

    const email =
      form.email.trim().toLowerCase();

    if (!givenName) {
      errors.givenName =
        "Please enter your first name.";
    } else if (
      !NAME_PATTERN.test(givenName)
    ) {
      errors.givenName =
        "First name can contain letters, spaces, apostrophes and hyphens only.";
    }

    if (!surname) {
      errors.surname =
        "Please enter your last name.";
    } else if (
      !NAME_PATTERN.test(surname)
    ) {
      errors.surname =
        "Last name can contain letters, spaces, apostrophes and hyphens only.";
    }

    if (
      !selectedDay ||
      !selectedMonth ||
      !selectedYear ||
      !form.dob
    ) {
      errors.dob =
        "Please select your complete date of birth.";
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
        errors.dob =
          `You must be at least ${MIN_AGE} years old.`;
      }
    }

    if (!govId) {
      errors.govId =
        "Please enter your GovID.";
    } else if (
      !GOV_ID_PATTERN.test(govId)
    ) {
      errors.govId =
        "GovID must contain only letters and numbers, between 6 and 20 characters.";
    }

    if (!address) {
      errors.address =
        "Please enter your residential address.";
    } else if (
      address.length < MIN_ADDRESS_LENGTH
    ) {
      errors.address =
        "Please enter your full residential address.";
    } else if (
      !ADDRESS_LETTER_PATTERN.test(address)
    ) {
      errors.address =
        "Please enter a valid residential address.";
    }

    if (!email) {
      errors.email =
        "Please enter your email address.";
    } else if (
      !EMAIL_PATTERN.test(email)
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
      errors.password =
        `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
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

    if (
      Object.keys(errors).length > 0
    ) {
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

      // Step 1: create the account
      const credential =
        await createUserWithEmailAndPassword(
          auth,
          email,
          form.password
        );

      // Step 2: save the profile and send the verification email
      await finishAccountSetup(credential.user);
    } catch (firebaseError) {
      console.error(firebaseError);

      setError(
        getFirebaseErrorMessage(
          firebaseError
        )
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6 py-12">
      <section className="w-full max-w-2xl rounded-lg border border-slate-300 bg-white p-8 shadow-lg">
        <h1
          className={`${mainHeader} mb-2 text-center`}
        >
          Create A Voter Account
        </h1>

        <p className="mb-8 text-[18px] text-center text-slate-600">
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
                maxLength={100}
                value={form.givenName}
                onChange={handleChange}
                className={fieldClass(
                  "givenName"
                )}
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
                maxLength={100}
                value={form.surname}
                onChange={handleChange}
                className={fieldClass(
                  "surname"
                )}
              />

              {fieldErrors.surname && (
                <p className="mt-1 text-xs text-red-700">
                  {fieldErrors.surname}
                </p>
              )}
            </div>
          </div>

          <div>
            <p className="mb-1 block font-semibold">
              Date of birth
            </p>

            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label
                  htmlFor="dobDay"
                  className="mb-1 block text-sm text-slate-600"
                >
                  Day
                </label>

                <select
                  id="dobDay"
                  value={selectedDay}
                  onChange={(event) =>
                    handleDateChange(
                      "day",
                      event.target.value
                    )
                  }
                  className={selectClass("dob")}
                  required
                >
                  <option value="">
                    Day
                  </option>

                  {days.map((day) => (
                    <option
                      key={day}
                      value={day}
                    >
                      {Number(day)}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="dobMonth"
                  className="mb-1 block text-sm text-slate-600"
                >
                  Month
                </label>

                <select
                  id="dobMonth"
                  value={selectedMonth}
                  onChange={(event) =>
                    handleDateChange(
                      "month",
                      event.target.value
                    )
                  }
                  className={selectClass("dob")}
                  required
                >
                  <option value="">
                    Month
                  </option>

                  {months.map((month) => (
                    <option
                      key={month.value}
                      value={month.value}
                    >
                      {month.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  htmlFor="dobYear"
                  className="mb-1 block text-sm text-slate-600"
                >
                  Year
                </label>

                <select
                  id="dobYear"
                  value={selectedYear}
                  onChange={(event) =>
                    handleDateChange(
                      "year",
                      event.target.value
                    )
                  }
                  className={selectClass("dob")}
                  required
                >
                  <option value="">
                    Year
                  </option>

                  {years.map((year) => (
                    <option
                      key={year}
                      value={year}
                    >
                      {year}
                    </option>
                  ))}
                </select>
              </div>
            </div>

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
              className={fieldClass("govId")}
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
              maxLength={200}
              rows={3}
              value={form.address}
              onChange={handleChange}
              className={fieldClass("address")}
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
              className={fieldClass("email")}
            />

            {fieldErrors.email && (
              <p className="mt-1 text-xs text-red-700">
                {fieldErrors.email}
              </p>
            )}

            <p className="mt-1 text-xs text-slate-500">
              A verification email will be sent to this
              address.
            </p>
            <p className="mt-1 text-xs text-slate-500">
              After you verify your email, you will add a
              phone number for 2-step verification.
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
                className={fieldClass(
                  "password"
                )}
              />

              {fieldErrors.password && (
                <p className="mt-1 text-xs text-red-700">
                  {fieldErrors.password}
                </p>
              )}

              <p className="mt-1 text-xs text-slate-500">
                Your password should be at least <strong>{MIN_PASSWORD_LENGTH} characters long</strong>.
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
                className={fieldClass(
                  "confirmPassword"
                )}
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
            {isSubmitting ? "Creating account..." : "Create account"}
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
