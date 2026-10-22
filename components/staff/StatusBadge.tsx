export function StatusBadge({ value }: { value: string }) {
  const style = value === "success" || value === "enrolled" || value === "active"
    ? "border-green-300 bg-green-50 text-green-900"
    : value === "denied" || value === "pending"
      ? "border-amber-300 bg-amber-50 text-amber-900"
      : value === "failed" || value === "removed" || value === "inactive"
        ? "border-red-300 bg-red-50 text-red-900"
        : "border-slate-300 bg-slate-50 text-slate-800";
  return <span className={`inline-flex rounded-full border px-2 py-1 text-xs font-semibold ${style}`}>{value}</span>;
}
