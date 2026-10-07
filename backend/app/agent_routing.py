"""Deterministic routing policy for the bounded interview Agent."""

from __future__ import annotations


def required_tools_for_question(question: str) -> list[tuple[str, dict]]:
    """Return the minimum baseline reads for a user question.

    The model may still choose additional tools.  The conservative default is
    current JD + current-position intel, because CareerPilot answers are
    position-scoped by default rather than generic chat answers.
    """

    text = (question or "").strip().lower()
    if not text:
        return [("read_current_jd", {}), ("search_current_intel", {})]
    generic_prefixes = (
        "什么是",
        "解释一下",
        "怎么实现",
        "如何实现",
        "请解释",
        "介绍一下",
    )
    if text.startswith(generic_prefixes) and not any(
        token in text for token in ("当前岗位", "这家公司", "面经", "简历", "面试")
    ):
        return []
    if any(token in text for token in ("简历", "经历", "匹配", "优势", "短板")):
        return [("read_resume", {}), ("read_current_jd", {})]
    if any(token in text for token in ("时间线", "日程", "冲突", "安排", "截止", "什么时候", "面试时间")):
        return [("search_timeline", {}), ("read_current_jd", {})]
    return [("read_current_jd", {}), ("search_current_intel", {})]
