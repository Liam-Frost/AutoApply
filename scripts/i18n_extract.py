"""Collect every piece of Chinese interface text, as the units a browser will actually show.

Two kinds of unit:
* plain strings - a label, a button, a message;
* patterns - text with values in it. ``已选 {{ picked.size }} 个`` in a template and `已选 ${n} 个` in script
  both become ``已选 {0} 个``, so the translation can put the value where English wants it.

Sources: the interface (frontend/src) and the server's user-facing wording (it reaches the page through the API).

    uv run python scripts/i18n_extract.py            # writes frontend/src/i18n/zh.json (the list to translate)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[一-鿿]")
SERVER = ["access.py", "sites.py", "sources/pdportal.py", "mail.py", "doctor.py", "remote.py", "transfer.py", "humanize.py", "stages.py", "intake.py", "persona.py", "employers.py", "mailbox.py", "browser.py", "prompts.py", "llm_openai.py", "llm_codex.py", "outlook.py",
          "convert.py", "tailor.py", "handlers.py", "tasks.py", "discover.py", "drafts.py", "auth.py", "api/main.py", "net.py", "messages.py", "scoring.py", "metering.py", "analytics.py",
          "applications.py", "lifecycle.py", "reminders.py", "rules.py", "notify.py", "backup.py", "quota.py", "llm.py", "sources/public.py", "sources/watch.py", "agentbudget.py", "profile_init.py", "agent/work.py", "outbox.py", "chain.py", "facts.py"]
# Server files that hold Chinese text which is NOT shown to anyone as the program's words - with what it is instead.
# Every server file with Chinese text in it is in SERVER or here (tests/test_units.py checks it): a new file whose
# messages would otherwise stay untranslated is noticed when it is written, not when someone reads the English interface.
NOT_INTERFACE = {
    "sitestatus.py": "a separator between what a site says and what it says it about", "i18n.py": "the translator itself",
    "importer.py": "the words of the applicant's own old tracking table", "knowledge.py": "a note in the profile's own history",
    "launcher.py": "the tray, which runs without the server and carries both languages itself",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def with_slots(s: str, opener: str, closer: str) -> str:
    """Replace each {{ expr }} / ${ expr } with {0}, {1}, ... (nested braces inside an expression are handled)."""
    out, i, n = [], 0, 0
    while i < len(s):
        if s.startswith(opener, i):
            depth, j = 1, i + len(opener)
            while j < len(s) and depth:
                if closer == "}}" and s.startswith("}}", j) and depth == 1:
                    depth = 0
                    j += 2
                    break
                if closer == "}":
                    depth += s[j] == "{"
                    depth -= s[j] == "}"
                j += 1
            out.append("{%d}" % n)
            n += 1
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def keep(s: str) -> bool:
    bare = re.sub(r"\{\d+\}", "", s)
    if re.search(r"[A-Za-z0-9_)\]]\||\|[A-Za-z\(]", s) or s.count("|") >= 3:      # a regular expression that matches error text, not wording anyone reads
        return False
    return bool(CJK.search(bare)) and len(s) <= 400


def from_vue(text: str, found: set[str]) -> None:
    tpl = text[text.find("<template>"):] if "<template>" in text else ""
    script = text[: text.find("<template>")] if "<template>" in text else text
    tpl = re.sub(r"<!--.*?-->", "", tpl, flags=re.S)
    # text between tags
    for m in re.finditer(r">([^<>]+)<", tpl):
        s = norm(with_slots(m.group(1), "{{", "}}"))
        if keep(s):
            found.add(s)
    # attribute values: plain ones are text; bound ones (:x, @x, v-x) are script expressions
    for m in re.finditer(r'\s([:@]?[\w.-]+)="([^"]+)"', tpl):
        name, val = m.group(1), m.group(2)
        if name.startswith((":", "@", "v-")):
            from_js(val, found)
        elif name not in ("class", "style", "href", "src", "to", "id", "key", "type", "name", "value", "for", "rel", "target", "accept"):
            s = norm(val)
            if keep(s):
                found.add(s)
    from_js(script, found)
    # expressions inside the template: {{ ... }} and :attr="..."
    for m in re.finditer(r"\{\{(.+?)\}\}", tpl, flags=re.S):
        from_js(m.group(1), found)


def from_js(code: str, found: set[str]) -> None:
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    for m in re.finditer(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"", code):
        s = norm((m.group(1) or m.group(2) or "").replace("\\'", "'").replace('\\"', '"'))
        if keep(s):
            found.add(s)
    for m in re.finditer(r"`((?:[^`\\]|\\.)*)`", code, flags=re.S):
        s = norm(with_slots(m.group(1), "${", "}"))
        if keep(s):
            found.add(s)


def from_py(code: str, found: set[str]) -> None:
    code = re.sub(r"(?m)^\s*#.*$", "", code)
    code = re.sub(r'"""(?:.|\n)*?"""', lambda m: m.group(0) if CJK.search(m.group(0)) and "=" in code[max(0, m.start() - 40): m.start()] else '""', code)
    for m in re.finditer(r"(f?)\"((?:[^\"\\\n]|\\.)*)\"|(f?)'((?:[^'\\\n]|\\.)*)'", code):
        is_f = bool(m.group(1) or m.group(3))
        s = m.group(2) if m.group(2) is not None else m.group(4)
        s = s.replace('\\"', '"').replace("\\'", "'").replace("\\n", " ")
        if is_f:
            s = with_slots(s.replace("{{", "\x00").replace("}}", "\x01"), "{", "}").replace("\x00", "{").replace("\x01", "}")
        s = norm(s)
        if keep(s):
            found.add(s)


def main() -> None:
    found: set[str] = set()
    for p in sorted((ROOT / "frontend" / "src").rglob("*")):
        if p.suffix == ".vue":
            from_vue(p.read_text(encoding="utf-8"), found)
        elif p.suffix == ".js":
            from_js(p.read_text(encoding="utf-8"), found)
    n_ui = len(found)
    for rel in SERVER:
        p = ROOT / "backend" / "autoapply" / rel
        if p.exists():
            from_py(p.read_text(encoding="utf-8"), found)
    out = ROOT / "frontend" / "src" / "i18n"
    out.mkdir(exist_ok=True)
    # a piece that starts or ends with a separator ("，{0} 个高分岗位…") is also needed without it: joined text is
    # translated piece by piece, split at those separators
    for u in list(found):
        t = u.strip("，；、：,;: ")
        if t != u and keep(t):
            found.add(t)
    rows = sorted(found, key=lambda s: (len(s), s))
    (out / "zh.json").write_text(json.dumps(rows, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"{len(rows)} units ({n_ui} from the interface, {len(rows) - n_ui} more from the server); {sum(1 for r in rows if '{0}' in r)} with values; {sum(len(r) for r in rows)} characters")


if __name__ == "__main__":
    main()
