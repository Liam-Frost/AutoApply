# Rules for coding agents

These apply to any AI agent working in this repository (Claude Code, Codex, Copilot and the like). The project's own
rules for contributors are in [CONTRIBUTING.md](CONTRIBUTING.md); read it first.

## Release notes

- A change a user notices comes with a **change fragment** in the same pull request:
  `python scripts/release.py change --type <type> --scope <scope> --summary-en "..." [--summary-zh "..."] [--summary-fr "..."] [--details "..."]`.
  If your branch already has a pending fragment for the feature, update that file instead of adding another.
  No fragment for refactoring, tests, CI or contributor docs: say "No user-visible change" in the pull request.
- Then run `python scripts/release.py validate` and fix what it reports.
- **Never edit generated files**: `CHANGELOG.md` and `backend/autoapply/releases.json` are made by
  `release.py generate` / `prepare`. A released fragment (one named in `changes/releases/*.json`) is changed only
  together with `release.py correct <version> <id> --reason "..."`; version numbers only by `release.py prepare`.
- **Never create or push a git tag, never run `release.py publish --yes`, never create a GitHub release** without the
  owner's explicit word for that release. `prepare` only on the owner's request; `publish` without `--yes` (a dry run)
  is fine.

## Everything else

- Do not commit secrets or personal data (names, e-mail addresses, application records) - not in code, tests,
  screenshots or logs.
- Run `uv run pytest` (and `cd frontend && npm test` for the interface) before saying a change works, and say what you
  ran it against.
- The interface: `docs/component-guidelines.md` and `docs/ux-writing-glossary.md`; every text is an i18n key.

How fragments and releases work: [docs/release-workflow.md](docs/release-workflow.md) (how to),
[docs/release-architecture.md](docs/release-architecture.md) (design).
