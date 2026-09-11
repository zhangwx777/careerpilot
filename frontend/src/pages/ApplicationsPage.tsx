import { useState } from "react";
import { PencilSimple, Plus, Trash, Tray } from "@phosphor-icons/react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Pagination } from "../components/Pagination";
import { StatusRail } from "../components/StatusRail";
import { usePagedList } from "../hooks/usePagedList";
import { formatDate } from "../format";
import {
  APPLICATION_STATUSES,
  type Application,
  type ApplicationStatus,
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
  const [statusFilter, setStatusFilter] = useState<ApplicationStatus | "">("");
  const [removalTarget, setRemovalTarget] = useState<Application | null>(null);
  const {
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
    reload,
  } = usePagedList<Application>({
    pageSize,
    reloadKey: statusFilter,
    load: (currentPage, currentQuery) => api.applications.list({
      page: currentPage,
      page_size: pageSize,
      q: currentQuery,
      status: statusFilter || undefined,
    }),
  });

  async function transition(application: Application, status: ApplicationStatus) {
    setError("");
    try {
      await api.applications.transition(application.id, status);
      reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "状态更新失败");
    }
  }

  async function remove(application: Application) {
    setRemovalTarget(null);
    setError("");
    try {
      await api.applications.remove(application.id);
      if (data.items.length === 1 && page > 1) setPage(page - 1);
      else reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除失败");
    }
  }

  return (
    <section>
      <div className="page-heading">
        <div>
          <h1>投递台账</h1>
          <p>集中记录每一条投递及其当前进度。</p>
        </div>
        <Link className="button primary" to="/applications/new">
          <Plus size={18} weight="bold" aria-hidden="true" />
          新增投递
        </Link>
      </div>

      <div className="filter-bar applications-filters">
        <div className="search-form auto-search">
          <label htmlFor="application-search" className="sr-only">
            搜索投递
          </label>
          <input
            id="application-search"
            value={draftQuery}
            onChange={(event) => {
              const value = event.target.value;
              setDraftQuery(value);
              setPage(1);
              setQuery(value.trim());
            }}
            placeholder="搜索公司、岗位或备注"
          />
        </div>
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
          <span>公司 / 岗位</span>
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
            <strong>{query || statusFilter ? "没有匹配的投递" : "还没有投递记录"}</strong>
            <span>{query || statusFilter ? "调整搜索条件后再试。" : "先新增公司和岗位，再记录投递。"}</span>
          </div>
        ) : (
          <div className="ledger-rows">
            {data.items.map((application) => {
              const company = application.position.company;
              const position = application.position;
              const nextStatuses = availableStatuses(application.status);
              return (
                <article className="ledger-row" key={application.id}>
                  <div className="ledger-application-target">
                    <strong>{company.name}</strong>
                    <span className="ledger-position-title">{position.title}</span>
                    <span className="ledger-created">
                      创建于 {formatDate(application.created_at)}
                      {!position.jd_text?.trim() && (
                        <em className="jd-missing" title="备战分析需要 JD，可在编辑投递时补充">缺 JD</em>
                      )}
                    </span>
                  </div>
                  <div className="date-cell" data-label="投递时间">
                    {formatDate(application.applied_at)}
                  </div>
                  <StatusRail status={application.status} />
                  <div className="status-action" data-label="下一步">
                    {nextStatuses.length ? (
                      <select
                        aria-label={`推进 ${company.name} ${position.title} 的状态`}
                        value=""
                        onChange={(event) => transition(application, event.target.value as ApplicationStatus)}
                      >
                        <option value="" disabled>推进至…</option>
                        {nextStatuses.map((status) => <option key={status}>{status}</option>)}
                      </select>
                    ) : <span className="terminal-label">流程已结束</span>}
                  </div>
                  <div className="row-actions">
                    <Link to={`/applications/${application.id}/edit`}>
                      <PencilSimple size={15} aria-hidden="true" />编辑
                    </Link>
                    <button className="danger-action" type="button" onClick={() => setRemovalTarget(application)}>
                      <Trash size={15} aria-hidden="true" />删除
                    </button>
                  </div>
                  {application.note && <p className="row-note">{application.note}</p>}
                </article>
              );
            })}
          </div>
        )}
      </div>
      <Pagination page={page} pageSize={pageSize} total={data.total} onChange={setPage} />
      <ConfirmDialog
        open={Boolean(removalTarget)}
        title="删除这条投递记录？"
        description={removalTarget ? `${removalTarget.position.company.name} · ${removalTarget.position.title} 将从投递台账中删除。` : ""}
        onCancel={() => setRemovalTarget(null)}
        onConfirm={() => { if (removalTarget) void remove(removalTarget); }}
      />
    </section>
  );
}
