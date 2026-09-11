import { type FormEvent, useEffect, useRef, useState } from "react";

import type { Page } from "../types";

interface UsePagedListOptions<T> {
  pageSize: number;
  load: (page: number, query: string) => Promise<Page<T>>;
  reloadKey?: unknown;
}

export function usePagedList<T>({ pageSize, load, reloadKey }: UsePagedListOptions<T>) {
  const loadRef = useRef(load);
  const [data, setData] = useState<Page<T>>({ items: [], total: 0, page: 1, page_size: pageSize });
  const [page, setPage] = useState(1);
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    loadRef.current(page, query)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, query, reloadKey, revision]);

  function search(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setQuery(draftQuery.trim());
  }

  function reload() {
    setRevision((value) => value + 1);
  }

  return {
    data,
    page,
    setPage,
    draftQuery,
    setDraftQuery,
    setQuery,
    query,
    loading,
    error,
    setError,
    search,
    reload,
    revision,
  };
}
