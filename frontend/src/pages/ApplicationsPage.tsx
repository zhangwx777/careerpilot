import { type FormEvent, useEffect, useState } from "react";
import { MagnifyingGlass, PencilSimple, Plus, Trash, Tray } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { Pagination } from "../components/Pagination";
import { StatusRail } from "../components/StatusRail";
import { formatDate } from "../format";
import {
  APPLICATION_STATUSES,
  type Application,
  type ApplicationStatus,
  type Page,
} from "../types";

const pageSize = 12;

function availableStatuses(status: ApplicationStatus): ApplicationStatus[] {
  if (status === "offer" || status === "挂") return [];
  const forward = APPLICATION_STATUSES.slice(
    APPLICATION_STATUSES.indexOf(status) + 1,
    -1,
  );
  return [...forward, "挂"];
}

export function ApplicationsPage() {
  const [data, setData] = useState<Page<Application>>({
    items: [],
    total: 0,
    page: 1,
    page_size: pageSize,
  });
  const [page, setPage] = useState(1);
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api.applications
      .list({
        page,
        page_size: pageSize,
        q: query,
        status: statusFilter || undefined,
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
  }, [page, query, revision, statusFilter]);

  function search(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setQuery(draftQuery.trim());
  }

  async function transition(application: Application, status: ApplicationStatus) {
    setError("");
    try {
      await api.applications.transition(application.id, status);
      setRevision((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "状态更新失败");
    }
  }

  async function remove(application: Application) {
    if (!window.confirm(`删除 ${application.position.company.name}的${application.position.title} 投递？`)) {
      return;
    }
    setError("");
    try {
      await api.applications.remove(application.id);
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
          <h1>投递台账</h1>
          <p>把每一条投递放回同一条进度线上。</p>
        </div>
        <Link className="button primary" to="/applications/new">
          <Plus size={18} weight="bold" aria-hidden="true" />
          新增投递
        </Link>
      </div>

      <div className="filter-bar">
        <form className="search-form" onSubmit={search}>
          <label htmlFor="application-search" className="sr-only">
            搜索投递
          </label>
          <input
            id="application-search"
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="搜索公司、岗位或备注"
          />
          <button type="submit">
            <MagnifyingGlass size={17} aria-hidden="true" />
            搜索
          </button>
        </form>
        <label className="select-control">
          <span>状态</span>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as ApplicationStatus | "");
              setPage(1);
            }}
          >
            <option value="">全部阶段</option>
            {APPLICATION_STATUSES.map((status) => (
              <option key={status}>{status}</option>
            ))}
          </select>
        </label>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      <div className="ledger">
        <div className="ledger-head">
          <span>目标</span>
          <span>投递时间</span>
          <span>阶段轨道</span>
          <span>下一步</span>
          <span>操作</span>
        </div>
        {loading ? (
          <div className="loading-state" aria-label="正在读取投递记录">
            <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
          </div>
        ) : data.items.length === 0 ? (
          <div className="empty-state">
            <Tray size={36} weight="duotone" aria-hidden="true" />
            <strong>{query || statusFilter ? "没有匹配的投递" : "第一条投递，从这里开始"}</strong>
            <span>{query || statusFilter ? "调整搜索条件后再试。" : "先建立公司和岗位，再记录当前进度。"}</span>
          </div>
        ) : (
          data.items.map((application) => {
            const nextStatuses = availableStatuses(application.status);
            return (
              <article className="ledger-row" key={application.id}>
                <div className="target-cell">
                  <span className="company-monogram">
                    {application.position.company.name.slice(0, 1)}
                  </span>
                  <div>
                    <strong>{application.position.company.name}</strong>
                    <span>{application.position.title}</span>
                  </div>
                </div>
                <div className="date-cell" data-label="投递时间">
                  {formatDate(application.applied_at)}
                </div>
                <StatusRail status={application.status} />
                <div className="status-action" data-label="下一步">
                  {nextStatuses.length ? (
                    <select
                      aria-label={`推进 ${application.position.company.name} 的状态`}
                      value=""
                      onChange={(event) =>
                        transition(application, event.target.value as ApplicationStatus)
                      }
                    >
                      <option value="" disabled>
                        推进至…
                      </option>
                      {nextStatuses.map((status) => (
                        <option key={status}>{status}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="terminal-label">流程已结束</span>
                  )}
                </div>
                <div className="row-actions">
                  <Link to={`/applications/${application.id}/edit`}>
                    <PencilSimple size={15} aria-hidden="true" />编辑
                  </Link>
                  <button className="danger-action" type="button" onClick={() => remove(application)}>
                    <Trash size={15} aria-hidden="true" />
                    删除
                  </button>
                </div>
                {application.note && <p className="row-note">{application.note}</p>}
              </article>
            );
          })
        )}
      </div>
      <Pagination page={page} pageSize={pageSize} total={data.total} onChange={setPage} />
    </section>
  );
}
