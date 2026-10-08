# Issue tracker: GitHub

Issues and PRDs for this repository live in GitHub Issues. Use the `gh` CLI for tracker operations.

## Conventions

- Check CLI authentication with `gh auth status`; infer the repository from `git remote -v`.
- Create an issue with `gh issue create --title "..." --body "..."`. For multi-line bodies in PowerShell, write the Markdown to a temporary file and pass it with `--body-file`.
- Read an issue and its comments with `gh issue view <number> --comments`.
- List issues with `gh issue list --state open`; add `--label` or `--json` filters when needed.
- Comment with `gh issue comment <number> --body "..."`.
- Add or remove labels with `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close an issue with `gh issue close <number> --comment "..."`.

When a skill says to publish work to the issue tracker, create a GitHub issue. When it asks to fetch a ticket, run `gh issue view <number> --comments`.
