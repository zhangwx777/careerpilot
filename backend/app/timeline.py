from datetime import datetime, timedelta

from app.models import TimelineNode

COLLISION_NODE_TYPES = {"笔试", "一面", "二面", "三面", "HR面"}


def nodes_conflict(left: TimelineNode, right: TimelineNode) -> bool:
    if left.id == right.id:
        return False
    if left.status != "待处理" or right.status != "待处理":
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
    if node.status != "待处理" or node.scheduled_at is None:
        return alerts
    if node.scheduled_at < now:
        alerts.append("逾期")
    elif node.scheduled_at <= now + timedelta(hours=24):
        alerts.append("临期")
    return alerts
