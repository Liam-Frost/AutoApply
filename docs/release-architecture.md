# Release architecture

How AutoApply records its changes and makes releases from them. The how-to is
[release-workflow.md](release-workflow.md); this page is the design: the data, the rules, what is generated and who
reads it.

## One source

Every user-visible change is one **change fragment**: a small file written with the change, in the same pull request,
and reviewed with it. A **release manifest** says which fragments a release contains. Everything else - `CHANGELOG.md`,
the app's release history, the GitHub release notes - is generated from those two and is never edited by hand.

```
changes/
  README.md
  schema/fragment.schema.json      the front matter of a fragment; the one list of types and scopes
  schema/manifest.schema.json      a release manifest
  fragments/<id>.md                every fragment, released or pending; never moved or deleted once written
  releases/<version>.json          one manifest per release
  legacy/CHANGELOG-2.0.2.md        the hand-written changelog before fragments (frozen; read by nothing)
backend/autoapply/release/         the model: read, validate, version, render (package autoapply.release)
backend/autoapply/releases.json    GENERATED: released versions, read by the program at run time (shipped)
CHANGELOG.md                       GENERATED: released versions
scripts/release.py                 the command line (thin; the logic is in autoapply.release)
```

**Released and pending.** A fragment named by a manifest is released; every other fragment is pending. The generated
files hold released versions only, so a pull request that adds a fragment touches no shared file: parallel branches
(people or agents) never conflict over the changelog. The release that consumes the fragments regenerates the files
once.

## Fragment

`changes/fragments/<id>.md`: YAML front matter, then the details in Markdown.

```markdown
---
id: 2026-11-23-about-overview-b7e2
type: changed
scope: updates
summary:
  en: "About: the update status first, in a page of reading width"
  zh: "关于页：更新状态放在最前，页面宽度适合阅读"
  fr: "À propos : l’état des mises à jour d’abord, sur une page de largeur de lecture"
highlight: true
bump: patch
pr: 129
---

What a user notices, as long as needed: lists, links, code. English.
```

| Field | | |
|---|---|---|
| `id` | required | The file name without `.md`: the date it was written, a slug of 1-5 words, 4 random hex digits (`^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{4}$`). Made by `release.py change`; the random part keeps two fragments written at the same moment apart. |
| `type` | required | `added`, `changed`, `deprecated`, `removed`, `fixed`, `security` - what kind of change. One section per type in the notes, in this order. |
| `scope` | required | Which part of the product - the controlled list in `fragment.schema.json`. Independent of the type. |
| `summary` | required | `en` required: one line, at most 120 characters, no Markdown block syntax, no bold. `zh` (Simplified Chinese) and `fr` optional; a missing language falls back to English, marked as English in the interface. Written by a person or an agent with the change, never generated, never a cut of the details. |
| `highlight` | optional | One of the release's main changes (default false): shown first when a release is opened, at most 6. |
| `bump` | optional | `major`, `minor`, `patch`: the version impact when it is more than the default patch. Separate from `type` on purpose. |
| `pr` | optional | An integer or a list of integers. |
| body | optional | The details (Markdown, English, LF). Links are http(s) or relative. Headings of level 1-3 are a warning (the notes use them for sections). |

The front matter is read with PyYAML's safe loader; a key given twice is an error, and every problem is reported with
its file and line. The **content hash** of a fragment is the sha256 of its bytes with CRLF read as LF (a Windows
checkout is the same text).

## Manifest

`changes/releases/<version>.json`, written by `release.py prepare`:

```json
{
  "version": "2.0.3",
  "date": "2026-11-24",
  "title": { "en": "...", "zh": "...", "fr": "..." },
  "intro": "Optional Markdown, English: what the release is about.",
  "known_limits": ["Optional Markdown, English, one item each"],
  "fragments": [ { "id": "2026-11-23-about-overview-b7e2", "sha256": "..." } ],
  "corrections": [ { "id": "...", "date": "2026-12-01", "reason": "why the released text was changed", "sha256": "new hash" } ]
}
```

- `version` equals the file name: `X.Y.Z`, or a pre-release `X.Y.Z-rc.N`, `X.Y.ZaN`, `X.Y.ZbN` (the forms the release
  workflow marks as pre-releases; prefer `-rc.N`, which npm also accepts).
- `date` is ISO; `title.en` is required (the release's short name in the collapsed timeline).
- `fragments` is the display order inside each type. Every id exists, appears once, and in no other manifest.
- Written with a 2-space indent, UTF-8, LF, the fields in this order.

## Lifecycle

| State | What it is | How it is reached |
|---|---|---|
| Draft | a fragment on a branch | `release.py change`; `validate` may complain |
| Pending | merged, valid, in no manifest | the pull request is merged (CI ran `validate`) |
| Release candidate | a manifest whose tag does not exist yet | `release.py prepare` on a branch, merged as the "Release X" pull request |
| Validated | `validate --release X` and `generate --check` pass | CI, and the first job of `release.yml` |
| Published | the tag `vX` exists and `release.yml` published it | `release.py publish X --yes` by the owner |

**Published is derived from the tag, never written into a file**, so a failed publish leaves nothing marked as
published: fix it and push the tag again (or delete the failed tag first).

## Versions

- `pyproject.toml` `[project] version` is the authority (the program reads it as `backup.version()`). The copies that
  must agree: `frontend/package.json` `version`, `frontend/package-lock.json` `version` and `packages[""].version`,
  and `uv.lock`'s entry for the project itself - the in-program update installs a release with `uv sync --locked`,
  which refuses a lock whose project version differs. `validate` fails when they disagree. Only `prepare` changes
  them: exactly those fields, the rest of each file byte for byte, checked by reading the files back.
- The project's practice: every release bumps the patch number, features included; minor and major only when a
  fragment declares `bump`. **Suggested version** = the newer of pyproject's version and the newest manifest, bumped
  by the largest `bump` among the pending fragments (patch when none declares one). A pre-release's next patch is its
  own release (`2.1.0-rc.1` -> `2.1.0`).
- `prepare --version X` overrides the suggestion. X must be a valid version, newer than every manifest and every
  local tag, not older than pyproject's version, not existing - versions never go back and never repeat - and at
  least the declared bump (a release whose fragments declare `minor` cannot go out as a patch without
  `--force-bump "<reason>"`, and the reason is printed).

## Immutability and corrections

A released fragment is fixed: its current hash must equal the hash its manifest recorded - or the hash of its latest
correction. Anything else is an error, so a released note cannot change silently (an edit, a reformat, a
search-and-replace across the folder). To change released text on purpose:

```bash
# edit the fragment, then
python scripts/release.py correct 2.0.2 2026-11-22-calendar-reminders-1a2b --reason "The reminder window was wrong"
```

`correct` appends `{id, date, reason, sha256}` to that release's `corrections` and regenerates the artifacts; the
reason stays in the manifest. A fragment that is released is never deleted or renamed, and a manifest is never
deleted or renamed once its tag exists.

## Generated artifacts

`python scripts/release.py generate` writes two files; `generate --check` exits 1 and names the file when a committed
one is not what the data gives (CI runs it). Same inputs and the same generator give the same bytes: no clock, no
randomness; releases newest first by version, changes in manifest order, JSON keys sorted.

1. **`CHANGELOG.md`** - `# Changelog`, a "generated, do not edit" comment, one intro line, then per release, newest
   first: `## [X] - date`, the intro, `### Added` / `### Changed` / `### Deprecated` / `### Removed` / `### Fixed` /
   `### Security` (empty ones left out), each change `- **<summary.en>**` with its details indented two spaces below
   it (so lists in the details nest), then `### Known limits`; link references
   `[X]: https://github.com/<repo>/releases/tag/vX` at the bottom. Pending fragments are not in it.
2. **`backend/autoapply/releases.json`** - what the program reads (released versions only):
   ```
   { "_generated": "...do not edit...", "schema": 1, "repo": "Liam-Frost/AutoApply", "releases": [ ReleaseEntry ] }
   ReleaseEntry = { version, date, title: {en, zh?, fr?}, intro, known_limits: [str], url, changes: [ChangeEntry] }
   ChangeEntry  = { id, type, scope, summary: {en, zh?, fr?}, details, highlight }
   ```
   Newest first, `changes` in manifest order, keys sorted, UTF-8, 1-space indent, a final newline. `repo` comes from
   `[project.urls] Releases` in pyproject.toml.
3. **GitHub release notes** - `release.py notes X` prints a release's section of CHANGELOG.md without its heading and
   link references. `release.yml` publishes it with the downloads table appended.

## The program

The about page's history comes from `GET /api/about/changelog` (`backend/autoapply/changelog.py`): `releases.json`,
read again when the file changes, and - first, when there is one - the "Unreleased" entry from
`autoapply.release.pending_entry()`, which reads the pending fragments with the same parser (a source checkout). A
package normally has no pending fragments: the Docker image carries no `changes/`, and a release's zip is made from
the tag, where `prepare` released every fragment (`validate --release X` warns when some came in after it). Nothing
about the history is fetched from GitHub.

`pending_entry()` returns an entry shaped like a release (`version: "Unreleased"`, empty date, title, intro, known
limits and url; `changes` sorted by id), or `None` when there is no `changes/` folder, nothing pending, PyYAML is
missing, or a manifest cannot be read (what is released would not be known). A pending fragment that is not valid is
left out and logged. It never raises and caches by the files' times and sizes. The package imports nothing heavy;
PyYAML only when a fragment is read.

```python
from autoapply import release
release.TYPES, release.TYPE_ORDER          # the types, in the order of the sections
release.scopes(root)                       # from changes/schema/fragment.schema.json
release.load(root) -> Repo                 # .fragments {id: Fragment}, .manifests (newest first), .pending, .problems
release.validate(root, release=None, strict=False) -> [Problem(level, path, message, line)]
release.app_data(root) -> dict             # exactly what releases.json holds
release.pending_entry(root) -> dict | None
release.changelog_md(root) -> str
release.release_notes(version, root) -> str
release.suggest_version(root) -> (version, why)
```

`root` defaults to the program's root (`config.ROOT`); the command line passes it explicitly.

## What validate checks

Errors (exit 1):

- a file in `changes/fragments/` or `changes/releases/` that is not a fragment / manifest, or cannot be read (YAML or
  JSON syntax, a key given twice, not UTF-8, a byte order mark, no front matter) - with the line;
- a fragment against its schema (required fields, unknown fields, types and scopes from the schema, summary length
  and form, `bump`, `pr`); its id not its file name, or not a real date; a summary with Markdown block syntax, bold,
  or spaces around it; a link in the details that is neither http(s) nor relative;
- a manifest against its schema; its version not its file name; a date that is not a date; a fragment listed twice,
  missing, or in two manifests; a correction for a fragment not in the release, or dated before it;
- a released fragment whose hash is neither the recorded one nor its latest correction's;
- two manifests with one version; the copies of the version disagreeing; pyproject's version older than the newest
  release; the schema's types not the sections the notes have;
- with `--release X`: no manifest for X, or pyproject's version is not X;
- with `--strict`: a highlight without `summary.zh` or without details.

Warnings (said, not failing): the same two highlight rules without `--strict`; a level 1-3 heading in details; more
than 6 highlights in a release or pending; release dates going backwards as versions go up; pyproject's version
newer than the newest release without a manifest; corrections out of date order; with `--release X`, fragments still
pending (the package would show them as not released).

## CI

- `ci.yml`, job *Release data*: `validate` and `generate --check` on every push and pull request; on a pull request a
  non-blocking `::warning::` when `backend/autoapply` or `frontend/src` changed and no fragment was added or changed,
  unless the description says `no-changelog` or ticks "No user-visible change". The rehearsal job (*collect*) makes
  the notes of the current version with `release.py notes`.
- `release.yml`, first job: the tag equals pyproject's version, `changes/releases/X.json` exists,
  `validate --release X` and `generate --check` pass. The publish job builds the notes with `release.py notes X` and
  appends the downloads table.
- The tool needs only PyYAML: CI runs it as `uv run --no-project --python 3.12 --with pyyaml==6.0.3 python scripts/release.py ...`
  (no project install). PyYAML is also a dependency of the program (through `uvicorn[standard]`), so
  `uv run python scripts/release.py` works in a checkout.
