from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import TimelineNode
from app.planner_schemas import AvailabilityWindow, PlannerTaskDraft, ScheduledTask

SHANGHAI = ZoneInfo("Asia/Shanghai")
SLOT_MINUTES = 15


def _round_up(value: datetime) -> datetime:
    minute = ((value.minute + SLOT_MINUTES - 1) // SLOT_MINUTES) * SLOT_MINUTES
    return value.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)


def _is_busy(start: datetime, end: datetime, nodes: list[TimelineNode]) -> bool:
    for node in nodes:
        if node.scheduled_at is None:
            continue
        node_start = node.scheduled_at.astimezone(SHANGHAI)
        node_end = node.ends_at.astimezone(SHANGHAI) if node.ends_at else node_start
        if node.ends_at is None:
            if start <= node_start < end:
                return True
        elif start < node_end and node_start < end:
            return True
    return False


def validate_task_intervals(tasks: list[ScheduledTask], busy_nodes: list[TimelineNode]) -> None:
    occupied = list(busy_nodes)
    for task in tasks:
        if _is_busy(task.scheduled_at, task.ends_at, occupied):
            raise ValueError("任务时间与已有安排冲突")
        occupied.append(TimelineNode(scheduled_at=task.scheduled_at, ends_at=task.ends_at, status="待处理", node_type="其他"))


def schedule_tasks(
    tasks: list[PlannerTaskDraft],
    windows: list[AvailabilityWindow],
    busy_nodes: list[TimelineNode],
    now: datetime,
) -> list[ScheduledTask]:
    local_now = _round_up(now.astimezone(SHANGHAI))
    result: list[ScheduledTask] = []
    occupied = list(busy_nodes)
    by_weekday = sorted(windows, key=lambda item: (item.weekday, item.start))
    for task in tasks:
        scheduled = None
        for day_offset in range(31):
            day = (local_now + timedelta(days=day_offset)).date()
            for window in by_weekday:
                if day.weekday() != window.weekday:
                    continue
                start = datetime.combine(day, window.start, SHANGHAI)
                end = datetime.combine(day, window.end, SHANGHAI)
                candidate = _round_up(max(start, local_now))
                while candidate + timedelta(minutes=task.estimated_minutes) <= end:
                    candidate_end = candidate + timedelta(minutes=task.estimated_minutes)
                    if not _is_busy(candidate, candidate_end, occupied):
                        scheduled = (candidate, candidate_end)
                        break
                    candidate += timedelta(minutes=SLOT_MINUTES)
                if scheduled:
                    break
            if scheduled:
                break
        if not scheduled:
            raise ValueError("未来 30 天的可用时间不足以排入全部任务")
        scheduled_at, ends_at = scheduled
        result.append(ScheduledTask(**task.model_dump(), scheduled_at=scheduled_at, ends_at=ends_at))
        occupied.append(TimelineNode(scheduled_at=scheduled_at, ends_at=ends_at, status="待处理", node_type="其他"))
    return result
