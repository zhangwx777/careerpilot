# Domain docs

This repository uses one shared domain context across `backend/`, `frontend/`, and `desktop/`.

## Before exploring

- Read root `CONTEXT.md` if it exists.
- Read relevant decisions in `docs/adr/` if that directory exists.
- If these files are absent, proceed without flagging their absence or proposing that they be created upfront.

## Use domain language

Use terms as defined in `CONTEXT.md` when naming domain concepts in issues, hypotheses, refactor proposals, and tests. If a needed term is missing, note the gap rather than inventing a synonym.

## Respect decisions

If proposed work conflicts with an existing ADR, call out the conflict explicitly before proceeding.
