import { ArrowLeft, CheckCircle, Sparkle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api";
import type { PlannerSession, PreparationTask } from "../types";

export function PracticePage() {
  const { taskId } = useParams();
  const id = Number(taskId);
  const [task, setTask] = useState<PreparationTask | null>(null);
  const [session, setSession] = useState<PlannerSession | null>(null);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [answerLoading, setAnswerLoading] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!Number.isInteger(id) || id <= 0) {
      setError("行动不存在");
      setLoading(false);
      return;
    }
    let cancelled = false;
    api.planner.task(id).then((taskValue) => api.planner.session(taskValue.planner_session_id).then((sessionValue) => [taskValue, sessionValue] as const))
      .then(([taskValue, sessionValue]) => {
        if (cancelled) return;
        setTask(taskValue);
        setSession(sessionValue);
        setAnswer(taskValue.user_answer ?? "");
      })
      .catch((reason: Error) => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [id]);

  async function generateAnswer() {
    if (!task) return;
    setAnswerLoading(true); setError("");
    try { setTask(await api.planner.generateAnswer(task.id)); window.dispatchEvent(new Event("preparation-task-updated")); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "答案生成失败"); }
    finally { setAnswerLoading(false); }
  }

  async function reviewAnswer() {
    if (!task || !answer.trim()) { setError("请先写下自己的回答"); return; }
    setReviewLoading(true); setError("");
    try { setTask(await api.planner.reviewAnswer(task.id, answer.trim())); window.dispatchEvent(new Event("preparation-task-updated")); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "自答点评失败"); }
    finally { setReviewLoading(false); }
  }

  async function updateStatus(status: PreparationTask["status"]) {
    if (!task) return;
    setError("");
    try { setTask(await api.planner.updateTask(task.id, { status })); window.dispatchEvent(new Event("preparation-task-updated")); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "行动状态更新失败"); }
  }

  if (loading) return <section className="panel practice-page loading-state"><span className="skeleton" /><span className="skeleton" /><span className="skeleton" /></section>;
  if (!task) return <section><div className="notice error" role="alert">{error || "行动不存在"}</div><Link className="button ghost" to="/dashboard">返回求职总览</Link></section>;

  const application = session?.application;
  const priorityLabel = task.priority <= 1 ? "高" : task.priority === 2 ? "中" : "低";

  return (
    <section className="practice-page">
      <div className="page-heading">
        <div>
          <Link className="back-link" to="/dashboard"><ArrowLeft size={16} />返回求职总览</Link>
          <span className="eyebrow">行动练习</span>
          <h1>{task.title}</h1>
          <p>{application ? `${application.position.company.name} · ${application.position.title}` : "岗位备战行动"}</p>
        </div>
        <Link className="button ghost" to={`/planner/${task.planner_session_id}#planner-task-${task.id}`}>返回备战分析</Link>
      </div>
      {error && <div className="notice error" role="alert">{error}</div>}

      <div className="practice-layout">
        <main className="panel practice-content">
          <div className="practice-meta">
            <span className="planner-category">{task.category}</span>
            <span className={`planner-priority planner-priority-${Math.min(Math.max(task.priority, 1), 3)}`}>{priorityLabel}</span>
            <span className={`task-status task-status-${task.status}`}>{task.status}</span>
          </div>
          {task.detail && <p className="practice-detail">{task.detail}</p>}
          {task.gap && <p className="practice-gap">关联差距：{task.gap}</p>}

          {!task.answer_payload && task.status === "待处理" && (
            <div className="practice-empty-answer">
              <Sparkle size={32} weight="duotone" />
              <strong>先生成这道行动的参考答案</strong>
              <span>答案会结合当前岗位、简历和已确认的面经资料生成。</span>
              <button className="button primary" type="button" disabled={answerLoading} onClick={() => void generateAnswer()}>{answerLoading ? "生成中…" : "生成参考答案"}</button>
            </div>
          )}

          {task.answer_payload && (
            <>
              <section className="practice-answer" aria-label="参考答案">
                <div className="practice-answer-block"><span>题目</span><strong>{task.answer_payload.question}</strong></div>
                <div className="practice-answer-block"><span>核心答案</span><p>{task.answer_payload.core_answer}</p></div>
                <div className="practice-answer-block"><span>岗位定制回答</span><p>{task.answer_payload.personalized_answer}</p></div>
                {task.answer_payload.follow_ups.length > 0 && <div className="practice-answer-block"><span>可能追问</span><ul>{task.answer_payload.follow_ups.map((followUp) => <li key={followUp}>{followUp}</li>)}</ul></div>}
              </section>

              {task.status === "待处理" && (
                <section className="practice-review">
                  <label>写下自己的回答<textarea rows={8} value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder="先用自己的话回答，再提交给 AI 点评" /></label>
                  <div className="practice-actions">
                    <button className="button primary" type="button" disabled={reviewLoading} onClick={() => void reviewAnswer()}>{reviewLoading ? "点评中…" : "提交自答并完成"}</button>
                    <button className="button ghost" type="button" onClick={() => void updateStatus("已跳过")}>跳过</button>
                  </div>
                </section>
              )}

              {task.user_answer && task.feedback_payload && (
                <section className="practice-feedback">
                  <div><span>我的原回答</span><p>{task.user_answer}</p></div>
                  <div><span>AI 点评</span><p>{task.feedback_payload.strengths.join("；") || "暂无明显优点"}</p><p>{task.feedback_payload.gaps.join("；") || "没有发现明显遗漏"}</p></div>
                  <div><span>岗位定制改写</span><p>{task.feedback_payload.rewrite}</p></div>
                </section>
              )}
            </>
          )}

          {task.status === "已跳过" && <div className="practice-skipped"><span>这个行动已跳过</span><button className="button ghost" type="button" onClick={() => void updateStatus("待处理")}>恢复练习</button></div>}
          {task.status === "已完成" && <div className="practice-complete"><CheckCircle size={20} weight="duotone" />已完成这次自答练习</div>}
        </main>
      </div>
    </section>
  );
}
