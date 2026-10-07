"""Deterministic preparation state transitions shared by tasks and timeline."""

from fastapi import HTTPException
from app.models import TimelineNode


def transition_task(db, task, status):
    if task.practice_status in {"answer", "review"}:
        raise HTTPException(409, "练习正在生成，请稍后修改状态")
    if status == "已完成" and not task.feedback_payload:
        raise HTTPException(409, "请先提交自答并完成点评")
    task.status = status
    if status != "待处理":
        task.deferred_until = None
    if task.timeline_node_id is not None:
        node = db.get(TimelineNode, task.timeline_node_id)
        if node is not None:
            node.status = {"待处理": "待处理", "已完成": "已完成", "已跳过": "已取消"}[status]
