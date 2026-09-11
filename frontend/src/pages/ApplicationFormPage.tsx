import { type FormEvent, useEffect, useState } from "react";
import { ArrowLeft, Briefcase, FloppyDisk } from "@phosphor-icons/react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { StatusRail } from "../components/StatusRail";
import { clearDraft, loadDraft, saveDraft } from "../drafts";
import { toApiDate, toLocalInput } from "../format";
import {
  APPLICATION_STATUSES,
  type ApplicationStatus,
} from "../types";

const applicationDraftKey = "qiuzhao-agent:new-application";

type ApplicationDraft = {
  companyName: string;
  positionTitle: string;
  jdText: string;
  status: ApplicationStatus;
  appliedAt: string;
  note: string;
};

export function ApplicationFormPage() {
  const { id } = useParams();
  const applicationId = id ? Number(id) : null;
  const editing = applicationId !== null;
  const navigate = useNavigate();
  const [draft] = useState<ApplicationDraft>(() => loadDraft(window.localStorage, applicationDraftKey, {
    companyName: "", positionTitle: "", jdText: "", status: "已投递", appliedAt: "", note: "",
  }));
  const [companyName, setCompanyName] = useState(draft.companyName);
  const [positionTitle, setPositionTitle] = useState(draft.positionTitle);
  const [jdText, setJdText] = useState(draft.jdText);
  const [status, setStatus] = useState<ApplicationStatus>(draft.status);
  const [appliedAt, setAppliedAt] = useState(draft.appliedAt);
  const [note, setNote] = useState(draft.note);
  const [loading, setLoading] = useState(editing);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!applicationId) return;
    api.applications
      .get(applicationId)
      .then((application) => {
        setCompanyName(application.position.company.name);
        setPositionTitle(application.position.title);
        setStatus(application.status);
        setAppliedAt(toLocalInput(application.applied_at));
        setNote(application.note ?? "");
        setJdText(application.position.jd_text ?? "");
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [applicationId]);

  useEffect(() => {
    if (!editing) saveDraft(window.localStorage, applicationDraftKey, {
      companyName, positionTitle, jdText, status, appliedAt, note,
    });
  }, [appliedAt, companyName, editing, jdText, note, positionTitle, status]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!companyName.trim() || !positionTitle.trim()) {
      setError("请填写公司和岗位");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (applicationId) {
        await api.applications.update(applicationId, {
          company_name: companyName.trim(),
          position_title: positionTitle.trim(),
          jd_text: jdText.trim() || null,
          status,
          applied_at: toApiDate(appliedAt),
          note: note.trim() || null,
        });
      } else {
        await api.applications.create({
          company_name: companyName.trim(),
          position_title: positionTitle.trim(),
          jd_text: jdText.trim() || null,
          status,
          applied_at: toApiDate(appliedAt),
          note: note.trim() || null,
        });
      }
      clearDraft(window.localStorage, applicationDraftKey);
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
          <p>{editing ? "修正岗位、投递时间或备注。" : "记录一条投递及其当前进度。"}</p>
        </div>
        <Link className="button ghost" to="/applications">
          <ArrowLeft size={17} aria-hidden="true" />
          返回台账
        </Link>
      </div>

      {error && <div className="notice error" role="alert">{error}</div>}

      <div className="form-grid">
        <form className="panel record-form" onSubmit={save}>
          <label className="field-block">
            <span>公司</span>
            <input required value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="例如：携程集团" />
          </label>

          <label className="field-block">
            <span>岗位</span>
            <input required value={positionTitle} onChange={(event) => setPositionTitle(event.target.value)} placeholder="例如：Agent 开发工程师" />
          </label>

          <label className="field-block">
            <span>JD（可选）</span>
            <textarea rows={6} value={jdText} onChange={(event) => setJdText(event.target.value)} placeholder="刚看到岗位时可直接粘贴；以后也能补充。" />
          </label>

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
            <small>{editing ? "如果阶段点错了，可以在这里直接修正为正确的阶段。" : "补录已有投递时，可以直接选择它现在所在的阶段。"}</small>
          </label>

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
            {editing
              ? "在台账里推进阶段只能向后；如果之前点错了，在这里编辑可以直接改回正确的阶段。"
              : "状态保存后只能向后续阶段推进，也可以在任一未结束阶段标记为“挂”。"}
          </p>
        </aside>
      </div>
    </section>
  );
}
