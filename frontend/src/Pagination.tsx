export default function Pagination({ page, pageSize, total, onPage, onPageSize, disabled = false }: {
  page: number; pageSize: number; total: number; onPage: (page: number) => void;
  onPageSize: (size: number) => void; disabled?: boolean
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return <div className="flex flex-wrap items-center justify-between gap-3 py-4 text-sm">
    <label>Rows per page <select aria-label="Rows per page" value={pageSize} disabled={disabled}
      onChange={e => onPageSize(Number(e.target.value))} className="border rounded-lg p-2 ml-2">
      {[20, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}
    </select></label>
    <span>{total} results · Page {page} of {pages}</span>
    <div className="flex gap-2"><button type="button" className="table-button" disabled={disabled || page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <button type="button" className="table-button" disabled={disabled || page >= pages} onClick={() => onPage(page + 1)}>Next</button></div>
  </div>
}
