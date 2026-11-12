from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import APPLICATION_STATUS, Application, TimelineNode
from app.application_progress import change_stage

COLLISION_NODE_TYPES = {"笔试", "AI面", "一面", "二面", "三面", "HR面"}


def update_timeline_node(node: TimelineNode, **changes) -> None:
    """Track persisted node edits, including cancel/restore round trips."""
    changed = {key: value for key, value in changes.items() if getattr(node, key) != value}
    if changed:
        for key, value in changed.items():
            setattr(node, key, value)
        node.revision = (node.revision or 0) + 1


def sync_application_stage(db: Session, node: TimelineNode, source: str = "日程更新") -> None:
    if node.status not in {"待处理", "已完成"} or node.node_type not in APPLICATION_STATUS:
        return
    application = db.scalar(
        select(Application).where(Application.id == node.application_id).with_for_update().execution_options(populate_existing=True)
    )
    if application is None or application.status in {"offer", "挂"}:
        return
    # 补录较早通知不能覆盖较后阶段；完成安排也不代表通过下一轮。
    if APPLICATION_STATUS.index(node.node_type) > APPLICATION_STATUS.index(application.status):
        change_stage(db, application, node.node_type, source, node.id)


def nodes_conflict(left: TimelineNode, right: TimelineNode) -> bool:
    if left.id == right.id:
        return False
    if left.status != "待处理" or right.status != "待处理":
        return False
    if left.time_mode != "固定时间" or right.time_mode != "固定时间":
        return False
    if (
        left.node_type not in COLLISION_NODE_TYPES
        or right.node_type not in COLLISION_NODE_TYPES
    ):
        return False
    if left.scheduled_at is None or right.scheduled_at is None:
        return False

    if left.ends_at is not None and right.ends_at is not None:
        return (
            left.scheduled_at < right.ends_at
            and right.scheduled_at < left.ends_at
        )
    if left.ends_at is None and right.ends_at is None:
        return left.scheduled_at == right.scheduled_at
    if left.ends_at is None:
        return right.scheduled_at <= left.scheduled_at < right.ends_at
    return left.scheduled_at <= right.scheduled_at < left.ends_at


def conflict_map(
    target_nodes: list[TimelineNode], candidate_nodes: list[TimelineNode]
) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for target in target_nodes:
        conflicts = sorted(
            candidate.id
            for candidate in candidate_nodes
            if candidate.id is not None and nodes_conflict(target, candidate)
        )
        result[target.id] = conflicts
    return result


def alert_types(
    node: TimelineNode, conflict_node_ids: list[int], now: datetime
) -> list[str]:
    alerts: list[str] = []
    if conflict_node_ids:
        alerts.append("冲突")
    due_at = (
        node.ends_at
        if node.time_mode == "截止窗口" and node.ends_at is not None
        else node.scheduled_at
    )
    if node.status != "待处理" or due_at is None:
        return alerts
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if due_at < now:
        alerts.append("逾期")
    elif due_at <= now + timedelta(hours=24):
        alerts.append("临期")
    return alerts
