import { type FormEvent, useEffect, useState } from "react";
import { ArrowLeft, Briefcase, FloppyDisk, MagnifyingGlass } from "@phosphor-icons/react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { StatusRail } from "../components/StatusRail";
import { toApiDate, toLocalInput } from "../format";
import {
  APPLICATION_STATUSES,
  type ApplicationStatus,
  type Position,
} from "../types";

export function ApplicationFormPage() {
  const { id } = useParams();
  const applicationId = id ? Number(id) : null;
  const editing = applicationId !== null;
  const navigate = useNavigate();
  const [positionId, setPositionId] = useState(0);
  const [positionQuery, setPositionQuery] = useState("");
  const [positions, setPositions] = useState<Position[]>([]);
  const [status, setStatus] = useState<ApplicationStatus>("已投递");
  const [appliedAt, setAppliedAt] = useState("");
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(editing);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.positions
      .list({ page_size: 20 })
      .then((result) => setPositions(result.items))
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!applicationId) return;
    api.applications
      .get(applicationId)
      .then(async (application) => {
        setPositionId(application.position_id);
        setStatus(application.status);
        setAppliedAt(toLocalInput(application.applied_at));
        setNote(application.note ?? "");
        const result = await api.positions.list({
          q: application.position.title,
          page_size: 20,
        });
        setPositions(result.items);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [applicationId]);

  async function findPositions() {
    setError("");
    try {
      const result = await api.positions.list({ q: positionQuery.trim(), page_size: 20 });
      setPositions(result.items);
      if (!result.items.some((position) => position.id === positionId)) setPositionId(0);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "岗位查询失败");
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!positionId) {
      setError("请选择岗位");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (applicationId) {
        await api.applications.update(applicationId, {
          position_id: positionId,
          applied_at: toApiDate(appliedAt),
          note: note.trim() || null,
        });
      } else {
        await api.applications.create({
          position_id: positionId,
          status,
          applied_at: toApiDate(appliedAt),
          note: note.trim() || null,
        });
      }
      navigate("/applications");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return (
    <div className="panel loading-state" aria-label="正在读取投递记录">
      <span className="skeleton" /><span className="skeleton" /><span className="skeleton" />
    </div>
  );

  return (
    <section className="form-page">
      <div className="page-heading">
        <div>
          <h1>{editing ? "编辑投递" : "新增投递"}</h1>
          <p>{editing ? "修正岗位、投递时间或备注。" : "将一条分散的信息收进作战台账。"}</p>
        </div>
        <Link className="button ghost" to="/applications">
          <ArrowLeft size={17} aria-hidden="true" />
          返回台账
        </Link>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      <div className="form-grid">
        <form className="panel record-form" onSubmit={save}>
          <div className="field-block">
            <div className="field-heading">
              <label htmlFor="position">目标岗位</label>
              <Link to="/positions">管理岗位</Link>
            </div>
            <div className="inline-search">
              <input
                value={positionQuery}
                onChange={(event) => setPositionQuery(event.target.value)}
                placeholder="输入公司或岗位关键词"
                aria-label="搜索岗位"
              />
              <button type="button" onClick={findPositions}>
                <MagnifyingGlass size={17} aria-hidden="true" />
                查找
              </button>
            </div>
            <select
              id="position"
              required
              value={positionId || ""}
              onChange={(event) => setPositionId(Number(event.target.value))}
            >
              <option value="" disabled>
                选择一个岗位
              </option>
              {positions.map((position) => (
                <option key={position.id} value={position.id}>
                  {position.company.name} · {position.title}
                </option>
              ))}
            </select>
            {positions.length === 0 && <small>未找到岗位，请先前往岗位库创建。</small>}
          </div>

          {!editing && (
            <label className="field-block">
              <span>当前阶段</span>
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value as ApplicationStatus)}
              >
                {APPLICATION_STATUSES.map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
              <small>补录已有投递时，可以直接选择它现在所在的阶段。</small>
            </label>
          )}

          <label className="field-block">
            <span>投递时间</span>
            <input
              type="datetime-local"
              value={appliedAt}
              onChange={(event) => setAppliedAt(event.target.value)}
            />
          </label>

          <label className="field-block">
            <span>备注</span>
            <textarea
              rows={5}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="例如：内推渠道、联系人、需要跟进的事项"
            />
          </label>

          <div className="form-actions">
            <Link className="button ghost" to="/applications">
              取消
            </Link>
            <button className="button primary" disabled={saving} type="submit">
              <FloppyDisk size={17} weight="bold" aria-hidden="true" />
              {saving ? "正在保存…" : "保存投递"}
            </button>
          </div>
        </form>

        <aside className="panel form-context">
          <div className="context-heading">
            <Briefcase size={20} weight="duotone" aria-hidden="true" />
            <h2>{editing ? "当前进度" : "录入起点"}</h2>
          </div>
          <StatusRail status={status} />
          <p>
            状态保存后只能向后续阶段推进，也可以在任一未结束阶段标记为“挂”。
          </p>
        </aside>
      </div>
    </section>
  );
}
