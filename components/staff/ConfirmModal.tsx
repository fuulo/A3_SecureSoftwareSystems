"use client";

import { FormEvent, KeyboardEvent, ReactNode, useEffect, useRef } from "react";

export function ConfirmModal({
  title,
  children,
  onConfirm,
  onCancel,
  confirmLabel = "Confirm",
  busy = false,
}: {
  title: string;
  children: ReactNode;
  onConfirm: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
  confirmLabel?: string;
  busy?: boolean;
}) {
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    dialog.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus();
  }, []);
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab" || !dialog.current) return;
    const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(
      "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])",
    ));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onCancel();
    }}>
      <section ref={dialog} role="dialog" aria-modal="true" aria-labelledby="confirm-title" onKeyDown={handleKeyDown} className="w-full max-w-lg rounded-lg bg-white p-6 shadow-xl">
        <h2 id="confirm-title" className="text-xl font-semibold text-[#1f538d]">{title}</h2>
        <form onSubmit={onConfirm} className="mt-4 space-y-4">
          <div>{children}</div>
          <div className="flex justify-end gap-3">
            <button type="button" onClick={onCancel} className="rounded border border-slate-300 px-4 py-2">Cancel</button>
            <button type="submit" disabled={busy} className="rounded bg-[#1f538d] px-4 py-2 font-semibold text-white disabled:opacity-50">{busy ? "Working..." : confirmLabel}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
