# Repository Guidelines

## Project Structure & Module Organization

- `backend/app/` contains the FastAPI application and domain services; `backend/tests/` contains Python tests.
- `frontend/src/` contains the React and TypeScript UI. Frontend tests live in `frontend/*.test.ts`.
- `desktop/` contains the Electron main process and preload code. `packaging/` contains Windows installer and runtime build scripts; `docker/` contains database initialization assets.
- Root `docker-compose*.yml` files define local and isolated CI environments. Read `CLAUDE.md` before changing agent behavior, persisted workflows, data schemas, or desktop packaging; it records project-specific invariants.

## Build, Test, and Development Commands

- `docker compose up --build` starts the local frontend, API, worker, PostgreSQL, and Redis stack.
- Run CI verification from the repository root, in order:

  ```powershell
  docker compose -f docker-compose.ci.yml build
  docker compose -f docker-compose.ci.yml run --rm frontend
  docker compose -f docker-compose.ci.yml run --rm backend
  node --test docker-compose.test.mjs desktop/port-selection.test.mjs desktop/startup.test.mjs
  docker compose -f docker-compose.ci.yml down --volumes --remove-orphans
  ```

  The frontend step runs `pnpm test` and the production build; the backend step runs pytest and PostgreSQL integration tests. The final cleanup is for the isolated CI stack only.
- `.\packaging\build.ps1` builds Windows release artifacts; `-AppOnly` reuses an existing `build/installer/payload`.

## Coding Style & Testing Guidelines

Follow nearby code: Python uses four-space indentation; TypeScript uses two spaces, explicit types, and double-quoted imports. No separate lint or formatter command is configured. Name Python tests `test_*.py` and TypeScript tests `*.test.ts`. Keep provider, network, and model calls mocked in ordinary tests; use the isolated CI stack for PostgreSQL-dependent coverage. No repository-wide coverage threshold is configured.

## Commits, Pull Requests & Security

Recent commits use concise subjects, often with prefixes such as `fix:`, `docs:`, `test:`, and `chore:`. Keep changes focused. A pull request should explain the user-facing change, list validation performed, and include screenshots for UI changes; call out migrations or packaging changes. Keep `.env`, `.llm_config_secret`, credentials, backups, and real user/job-search data out of commits; use `.env.example` for safe configuration examples.
