import { type FormEvent, useEffect, useState } from "react";
import { Buildings, FloppyDisk, MagnifyingGlass, PencilSimple, Plus, Trash, X } from "@phosphor-icons/react";

import { api } from "../api";
import { Pagination } from "../components/Pagination";
import { formatDate } from "../format";
import type { Company, Page } from "../types";

const pageSize = 12;

export function CompaniesPage() {
  const [data, setData] = useState<Page<Company>>({
    items: [], total: 0, page: 1, page_size: pageSize,
  });
  const [page, setPage] = useState(1);
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Company | null>(null);
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.companies
      .list({ page, page_size: pageSize, q: query })
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
  }, [page, query, revision]);

  function resetForm() {
    setEditing(null);
    setName("");
    setIndustry("");
  }

  function edit(company: Company) {
    setEditing(company);
    setName(company.name);
    setIndustry(company.industry ?? "");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const input = { name: name.trim(), industry: industry.trim() || null };
      if (editing) await api.companies.update(editing.id, input);
      else await api.companies.create(input);
      resetForm();
      setPage(1);
      setRevision((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function remove(company: Company) {
    if (!window.confirm(`删除“${company.name}”？其岗位和投递记录也会一起删除。`)) return;
    setError("");
    try {
      await api.companies.remove(company.id);
      if (editing?.id === company.id) resetForm();
      if (data.items.length === 1 && page > 1) setPage(page - 1);
      else setRevision((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败");
    }
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>公司库</h1>
          <p>先建立目标公司，再把岗位和投递挂到它下面。</p>
        </div>
      </div>
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="split-layout">
        <div>
          <form
            className="search-form standalone"
            onSubmit={(event) => {
              event.preventDefault();
              setPage(1);
              setQuery(draftQuery.trim());
            }}
          >
            <input
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="搜索公司名称"
              aria-label="搜索公司"
            />
            <button type="submit">
              <MagnifyingGlass size={17} aria-hidden="true" />
              搜索
            </button>
          </form>
          <div className="data-list">
            <div className="data-list-head company-columns">
              <span>公司</span><span>行业</span><span>创建时间</span><span>操作</span>
            </div>
            {loading ? (
              <div className="loading-state" aria-label="正在读取公司">
                <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
              </div>
            ) : data.items.length === 0 ? (
              <div className="empty-state">
                <Buildings size={36} weight="duotone" aria-hidden="true" />
                <strong>公司库还是空的</strong><span>从右侧录入第一个目标公司。</span>
              </div>
            ) : data.items.map((company) => (
              <article className="data-row company-columns" key={company.id}>
                <strong>{company.name}</strong>
                <span data-label="行业">{company.industry ?? "未填写"}</span>
                <span data-label="创建时间" className="mono">{formatDate(company.created_at)}</span>
                <div className="row-actions">
                  <button type="button" onClick={() => edit(company)}><PencilSimple size={15} aria-hidden="true" />编辑</button>
                  <button className="danger-action" type="button" onClick={() => remove(company)}><Trash size={15} aria-hidden="true" />删除</button>
                </div>
              </article>
            ))}
          </div>
          <Pagination page={page} pageSize={pageSize} total={data.total} onChange={setPage} />
        </div>

        <form className="panel side-form" onSubmit={save}>
          <div className="form-title">
            <Buildings size={20} weight="duotone" aria-hidden="true" />
            <h2>{editing ? "编辑公司" : "新增公司"}</h2>
          </div>
          <label className="field-block">
            <span>公司名称</span>
            <input required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="field-block">
            <span>所属行业</span>
            <input maxLength={100} value={industry} onChange={(event) => setIndustry(event.target.value)} placeholder="例如：互联网" />
          </label>
          <div className="form-actions">
            {editing && <button className="button ghost" type="button" onClick={resetForm}><X size={16} aria-hidden="true" />取消编辑</button>}
            <button className="button primary" disabled={saving} type="submit">
              {editing ? <FloppyDisk size={17} weight="bold" aria-hidden="true" /> : <Plus size={17} weight="bold" aria-hidden="true" />}
              {saving ? "正在保存…" : editing ? "保存修改" : "新增公司"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
