---
id: 2026-11-23-one-record-per-change-ca3b
type: changed
scope: release
summary:
  en: "One record per change: the changelog, the program’s release history and the release notes are generated from it"
  zh: "每项改动只记录一次：更新日志、程序内的版本历史和发布说明都由它生成"
  fr: "Un seul enregistrement par changement : le journal, l’historique des versions du programme et les notes de version en sont tirés"
pr: 129
---

Every change a user notices is written once, as a change fragment in `changes/fragments/` (`python scripts/release.py change`);
a release is a manifest in `changes/releases/` that names its fragments. `CHANGELOG.md`, the history the about page shows
(`backend/autoapply/releases.json`, shipped with the program, read offline) and the notes of a GitHub release are generated
from them (`release.py generate`, `release.py notes`), and CI checks that they agree. Released text cannot change by
accident: a correction is recorded with its reason. The hand-written history up to 2.0.2 was carried over word for word.
