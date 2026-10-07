"""Material-backed source validity shared by chat, history, and insight writes."""

import re

from sqlalchemy import select

from app.models import InterviewIntel


class EvidenceChangedError(ValueError):
    pass


def valid_source_ids(db, source_ids, *, lock=False) -> set[str]:
    identifiers = set(source_ids)
    material_ids = {
        int(match.group(1))
        for identifier in identifiers
        if (match := re.fullmatch(r"material-(\d+):(.+)", identifier))
    }
    valid = {identifier for identifier in identifiers if not identifier.startswith("material-")}
    if not material_ids:
        return valid
    query = select(InterviewIntel).where(InterviewIntel.id.in_(material_ids))
    if lock:
        query = query.with_for_update()
    for material in db.scalars(query).all():
        valid.update(
            f"material-{material.id}:{source['id']}"
            for source in material.sources or []
            if isinstance(source, dict) and source.get("id")
        )
    return valid & identifiers
