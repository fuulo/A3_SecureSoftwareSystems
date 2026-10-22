export type DataColumn<T> = {
  key: keyof T | string;
  label: string;
  render?: (row: T) => React.ReactNode;
};

export function DataTable<T extends { id?: string; voterId?: string; staffId?: string; candidateId?: string }>({
  columns,
  rows,
  emptyMessage = "No records found.",
}: {
  columns: DataColumn<T>[];
  rows: T[];
  emptyMessage?: string;
}) {
  if (!rows.length) return <p className="rounded border border-dashed border-slate-300 p-6 text-center text-slate-600">{emptyMessage}</p>;
  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
        <thead className="bg-slate-50">
          <tr>{columns.map((column) => <th key={String(column.key)} scope="col" className="px-4 py-3 font-semibold">{column.label}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-200">
          {rows.map((row, index) => (
            <tr key={row.id ?? row.voterId ?? row.staffId ?? row.candidateId ?? index}>
              {columns.map((column) => (
                <td key={String(column.key)} className="px-4 py-3 align-top">
                  {column.render ? column.render(row) : String((row as Record<string, unknown>)[String(column.key)] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
