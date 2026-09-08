import { type FormEvent, useEffect, useState } from "react";
import { Briefcase, FloppyDisk, MagnifyingGlass, PencilSimple, Plus, Trash, X } from "@phosphor-icons/react";

import { api } from "../api";
import { Pagination } from "../components/Pagination";
import { formatDate } from "../format";
import type { Company, Page, Position } from "../types";

const pageSize = 12;

export function PositionsPage() {
  const [data, setData] = useState<Page<Position>>({
    items: [], total: 0, page: 1, page_size: pageSize,
  });
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyQuery, setCompanyQuery] = useState("");
  const [page, setPage] = useState(1);
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [companyFilter, setCompanyFilter] = useState(0);
  const [editing, setEditing] = useState<Position | null>(null);
  const [companyId, setCompanyId] = useState(0);
  const [title, setTitle] = useState("");
  const [jdText, setJdText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    api.companies
      .list({ page_size: 100 })
      .then((result) => setCompanies(result.items))
      .catch((reason: Error) => setError(reason.message));
  }, [revision]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.positions
      .list({
        page,
        page_size: pageSize,
        q: query,
        company_id: companyFilter || undefined,
      })
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
  }, [companyFilter, page, query, revision]);

  function resetForm() {
    setEditing(null);
    setCompanyId(0);
    setTitle("");
    setJdText("");
  }

  async function findCompanies() {
    setError("");
    try {
      const result = await api.companies.list({
        q: companyQuery.trim(),
        page_size: 100,
      });
      setCompanies(result.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "公司查询失败");
    }
  }

  async function edit(position: Position) {
    setEditing(position);
    setCompanyId(position.company_id);
    setTitle(position.title);
    setJdText(position.jd_text ?? "");
    if (!companies.some((company) => company.id === position.company_id)) {
      try {
        const company = await api.companies.get(position.company_id);
        setCompanies((current) => [company, ...current]);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "公司读取失败");
      }
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!companyId) {
      setError("请选择公司");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const input = {
        company_id: companyId,
        title: title.trim(),
        jd_text: jdText.trim() || null,
      };
      if (editing) await api.positions.update(editing.id, input);
      else await api.positions.create(input);
      resetForm();
      setPage(1);
      setRevision((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function remove(position: Position) {
    if (!window.confirm(`删除“${position.company.name} · ${position.title}”？相关投递也会一起删除。`)) return;
    setError("");
    try {
      await api.positions.remove(position.id);
      if (editing?.id === position.id) resetForm();
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
          <h1>岗位库</h1>
          <p>保留完整 JD，让后续情报与备战有准确目标。</p>
        </div>
      </div>
      {error && <div className="notice error" role="alert">{error}</div>}
      <div className="split-layout">
        <div>
          <div className="filter-bar compact-filter">
            <form className="search-form" onSubmit={(event) => {
              event.preventDefault(); setPage(1); setQuery(draftQuery.trim());
            }}>
              <input value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} placeholder="搜索公司或岗位" aria-label="搜索岗位" />
              <button type="submit">
                <MagnifyingGlass size={17} aria-hidden="true" />
                搜索
              </button>
            </form>
            <select aria-label="按公司筛选" value={companyFilter || ""} onChange={(event) => {
              setCompanyFilter(Number(event.target.value)); setPage(1);
            }}>
              <option value="">全部公司</option>
              {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
          </div>
          <div className="data-list">
            <div className="data-list-head position-columns">
              <span>岗位</span><span>公司</span><span>创建时间</span><span>操作</span>
            </div>
            {loading ? (
              <div className="loading-state" aria-label="正在读取岗位">
                <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
              </div>
            ) : data.items.length === 0 ? (
              <div className="empty-state">
                <Briefcase size={36} weight="duotone" aria-hidden="true" />
                <strong>没有找到岗位</strong><span>先建立公司，再从右侧新增目标岗位。</span>
              </div>
            ) : data.items.map((position) => (
              <article className="data-row position-columns" key={position.id}>
                <div><strong>{position.title}</strong>{position.jd_text && <span className="line-clamp">{position.jd_text}</span>}</div>
                <span data-label="公司">{position.company.name}</span>
                <span data-label="创建时间" className="mono">{formatDate(position.created_at)}</span>
                <div className="row-actions">
                  <button type="button" onClick={() => edit(position)}><PencilSimple size={15} aria-hidden="true" />编辑</button>
                  <button className="danger-action" type="button" onClick={() => remove(position)}><Trash size={15} aria-hidden="true" />删除</button>
                </div>
              </article>
            ))}
          </div>
          <Pagination page={page} pageSize={pageSize} total={data.total} onChange={setPage} />
        </div>

        <form className="panel side-form" onSubmit={save}>
          <div className="form-title">
            <Briefcase size={20} weight="duotone" aria-hidden="true" />
            <h2>{editing ? "编辑岗位" : "新增岗位"}</h2>
          </div>
          <label className="field-block">
            <span>所属公司</span>
            <div className="inline-search company-search">
              <input
                value={companyQuery}
                onChange={(event) => setCompanyQuery(event.target.value)}
                placeholder="按名称查找公司"
                aria-label="查找公司"
              />
              <button type="button" onClick={findCompanies}>
                <MagnifyingGlass size={17} aria-hidden="true" />
                查找
              </button>
            </div>
            <select required value={companyId || ""} onChange={(event) => setCompanyId(Number(event.target.value))}>
              <option value="" disabled>选择公司</option>
              {companies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
            {companies.length === 0 && <small>请先在公司库新增公司。</small>}
          </label>
          <label className="field-block">
            <span>岗位名称</span>
            <input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label className="field-block">
            <span>JD 原文</span>
            <textarea rows={8} value={jdText} onChange={(event) => setJdText(event.target.value)} placeholder="粘贴岗位职责与任职要求" />
          </label>
          <div className="form-actions">
            {editing && <button className="button ghost" type="button" onClick={resetForm}><X size={16} aria-hidden="true" />取消编辑</button>}
            <button className="button primary" disabled={saving || companies.length === 0} type="submit">
              {editing ? <FloppyDisk size={17} weight="bold" aria-hidden="true" /> : <Plus size={17} weight="bold" aria-hidden="true" />}
              {saving ? "正在保存…" : editing ? "保存修改" : "新增岗位"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
