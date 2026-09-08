interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onChange }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;

  return (
    <div className="pagination" aria-label="分页">
      <span>
        第 {page} / {pages} 页 · 共 {total} 条
      </span>
      <div>
        <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          <ArrowLeft size={16} aria-hidden="true" />
          上一页
        </button>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          下一页
          <ArrowRight size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
