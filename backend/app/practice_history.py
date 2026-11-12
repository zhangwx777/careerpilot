"""Position-scoped reviews independent of mutable application assignments."""
from copy import deepcopy
from itertools import islice

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Application, PlannerSession, PreparationTask
from app.planner_schemas import PreparationFeedback


def has_feedback(task: PreparationTask) -> bool:
    # A new review can retain the previous payload while awaiting completion.
    # Never pair that old review with the newly submitted answer.
    original_inputs = task.feedback_answer_snapshot is not None and task.feedback_question_snapshot is not None
    if not original_inputs and (task.practice_status != "idle" or task.practice_error):
        return False
    question = feedback_question(task)
    if not isinstance(question, str) or not question.strip() or not (feedback_answer(task) or "").strip():
        return False
    try:
        PreparationFeedback.model_validate(task.feedback_payload)
        return True
    except (ValidationError, TypeError):
        return False


def feedback_question(task: PreparationTask) -> str | None:
    return task.feedback_question_snapshot if task.feedback_question_snapshot is not None else (task.answer_payload or {}).get("question")


def feedback_answer(task: PreparationTask) -> str | None:
    return task.feedback_answer_snapshot if task.feedback_answer_snapshot is not None else task.user_answer


def practice_record(task: PreparationTask) -> dict:
    return {
        "source_id": f"practice-{task.id}",
        "task_id": task.id,
        "planner_session_id": task.planner_session_id,
        "application_id": task.application_id,
        "title": task.title,
        "question": feedback_question(task),
        "user_answer": feedback_answer(task),
        "feedback_payload": deepcopy(task.feedback_payload),
        "feedback_completed_at": task.feedback_completed_at.isoformat() if task.feedback_completed_at else None,
    }


def position_tasks(db: Session, position_id: int, *, include_unconfirmed: bool = False) -> list[PreparationTask]:
    scope = PlannerSession.position_id_snapshot == position_id
    if include_unconfirmed:
        scope = or_(
            scope,
            and_(PlannerSession.position_id_snapshot.is_(None), Application.position_id == position_id),
        )
    return list(db.scalars(
        select(PreparationTask)
        .join(PlannerSession, PreparationTask.planner_session_id == PlannerSession.id)
        .join(Application, PlannerSession.application_id == Application.id)
        .options(joinedload(PreparationTask.planner_session))
        .where(scope)
        .order_by(PreparationTask.feedback_completed_at.desc().nulls_last(), PreparationTask.id.desc())
    ).all())


def feedback_snapshot(db: Session, position_id: int) -> list[dict]:
    valid = (practice_record(task) for task in position_tasks(db, position_id) if has_feedback(task))
    return list(islice(valid, 20))
