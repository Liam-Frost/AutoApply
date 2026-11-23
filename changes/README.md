# changes/

The release data of AutoApply - the one source of its release notes.

- `fragments/` - one file per user-visible change, written with the change (`python scripts/release.py change`).
  A fragment no release names is pending.
- `releases/` - one manifest per release: its fragments, in order, with their hashes (`release.py prepare`).
- `schema/` - the JSON Schemas of both, and the one list of types and scopes.
- `legacy/` - the hand-written changelog before fragments, frozen.

`CHANGELOG.md` and `backend/autoapply/releases.json` are generated from this folder; do not edit them.
How to: [docs/release-workflow.md](../docs/release-workflow.md). Design: [docs/release-architecture.md](../docs/release-architecture.md).
