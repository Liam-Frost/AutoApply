<!-- Thank you. A few lines are enough; delete what does not apply. -->

## What this changes

<!-- What a user will notice, or what gets easier to maintain. -->

## Release note

<!-- Tick one. A fragment: python scripts/release.py change ... (docs/release-workflow.md). Never edit CHANGELOG.md. -->

- [ ] A change fragment in `changes/fragments/` is added or updated, and `python scripts/release.py validate` passes
- [ ] No user-visible change (refactoring, tests, CI, contributor docs)

## How it was checked

<!-- Say what you ran it against. "Unit tests" and "a real Greenhouse form, not submitted" are both fine answers; they are different answers. -->

- [ ] `uv run pytest` passes
- [ ] If the interface changed: `cd frontend && npm test && npm run build`; it uses the shared components (`docs/component-guidelines.md`), new text is written with keys in the glossary's terms, and it was looked at in light and dark, at 1440 and 1024 wide, in two languages
- [ ] If behaviour that `docs/STATUS.md` describes changed: that page is updated
- [ ] Nothing personal in the diff, the screenshots or the test data (names, e-mail addresses, application records)

## Not open to change

The program does not invent facts about the applicant, does not send an application other than the way the user chose, and does not get
around a site's protections. A change must leave those as they are.
