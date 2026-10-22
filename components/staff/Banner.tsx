export function Banner({ children, kind = "info" }: {
  children: React.ReactNode;
  kind?: "info" | "success" | "error";
}) {
  const styles = {
    info: "border-blue-200 bg-blue-50 text-blue-900",
    success: "border-green-200 bg-green-50 text-green-900",
    error: "border-red-300 bg-red-50 text-red-800",
  };
  return <p role={kind === "error" ? "alert" : "status"} className={`rounded border p-3 text-sm ${styles[kind]}`}>{children}</p>;
}
