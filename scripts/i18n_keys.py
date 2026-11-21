"""Move a page's Chinese text to message keys (plan §3.4, C2): `uv run python scripts/i18n_keys.py <file.vue> <namespace> [--write]`.

Conservative on purpose: it moves what is plainly one piece of text -
  - a text node of the template that is only text (no {{ }} in it),
  - an attribute whose value is only text (placeholder, title, aria-label, sub, what, text, label, ok ...),
  - a string literal of the script that is only text ('...' or "...", not a template literal with ${}),
and lists everything else (text around {{ }}, template literals, text built by joining) for the hand to do.

The English comes from the dictionary the page was translated with until now (frontend/src/i18n/en.json); the
Chinese is the page's own; each key gets a note saying where it is shown. Without --write it only says what it would
do. Run `npm run i18n:status` and the frontend tests afterwards.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src"
CJK = re.compile(r"[一-鿿]")
LOC = ROOT / "locales"


def load(name: str) -> dict:
    return json.loads((LOC / name).read_text(encoding="utf-8"))


def put(tree: dict, key: str, value: str) -> None:
    *path, last = key.split(".")
    for p in path:
        tree = tree.setdefault(p, {})
    tree[last] = value


def leaves(tree: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in tree.items():
        if isinstance(v, dict):
            out.update(leaves(v, prefix + k + "."))
        else:
            out[prefix + k] = v
    return out


def without_comments(text: str) -> str:
    """The text with its HTML comments blanked (line breaks kept, so line numbers stay), cut out by position."""
    out, at = [], 0
    while True:
        start = text.find("<!--", at)
        if start < 0:
            return "".join(out) + text[at:]
        end = text.find("-->", start + 4)
        end = len(text) if end < 0 else end + 3
        out.append(text[at:start] + "\n" * text.count("\n", start, end))
        at = end


def slug(english: str, taken: set[str], ns: str) -> str:
    words = re.findall(r"[A-Za-z]+", english.replace("'", "").replace("’", ""))[:4] or ["text"]
    base = words[0].lower() + "".join(w.capitalize() for w in words[1:])
    key, n = f"{ns}.{base}", 2
    while key in taken:
        key, n = f"{ns}.{base}{n}", n + 1
    taken.add(key)
    return key


def main() -> None:
    path, ns, write = Path(sys.argv[1]), sys.argv[2], "--write" in sys.argv
    src = path.read_text(encoding="utf-8")
    dictionary = json.loads((ROOT / "i18n" / "en.json").read_text(encoding="utf-8"))
    en, zh, notes = load("en.json"), load("zh.json"), load("notes.json")
    taken = set(leaves(en))
    by_text: dict[str, str] = {k: v for k, v in ((v_zh, k) for k, v_zh in leaves(zh).items() if k.startswith(ns + "."))}
    where = {"todos": "the to-do page", "drafts": "a record's page", "jobs": "the postings page", "applications": "the applications page",
             "settings": "the settings", "analytics": "the analytics page", "profile": "the profile page", "welcome": "the first-run guide",
             "runs": "the activity page", "accounts": "the site accounts page", "files": "the material library", "home": "the overview page",
             "sources": "the sources page", "app": "the sidebar and frame of every page", "mail": "the page of a mail to send",
             "contacts": "the contacts page", "remote": "the page of a window that waits for you", "login": "the sign-in page",
             "common": "parts shared by several pages"}.get(ns.split(".")[0], ns)
    missing: list[str] = []
    left: list[str] = []
    added = 0

    def key_for(text: str) -> str | None:
        nonlocal added
        text = re.sub(r"\s+", " ", text.strip())      # (as the dictionary has it: a text over several lines is one line)
        if text in by_text:
            return by_text[text]
        english = dictionary.get(text)
        if not english:
            missing.append(text)
            return None
        k = slug(english, taken, ns)
        put(en, k, english)
        put(zh, k, text)
        notes[k] = f"On {where}."
        by_text[text] = k
        added += 1
        return k

    def pattern_key(texts: list[str]) -> str | None:
        """Text with values in it ("{0} 次调用"): a key whose message names them {p0}, {p1}... - when the dictionary has
        the same sentence with its {0}, {1}."""
        nonlocal added
        zh_pat = re.sub(r"\s+", " ", "".join(x if i % 2 == 0 else "{" + str(i // 2) + "}" for i, x in enumerate(texts))).strip()
        if not CJK.search(zh_pat):
            return None
        named = re.sub(r"\{(\d+)\}", r"{p\1}", zh_pat)
        if named in by_text:
            return by_text[named]
        english = dictionary.get(zh_pat)
        if not english or sorted(re.findall(r"\{\d+\}", english)) != sorted(re.findall(r"\{\d+\}", zh_pat)):
            missing.append(zh_pat)
            return None
        k = slug(re.sub(r"\{\d+\}", "", english), taken, ns)
        put(en, k, re.sub(r"\{(\d+)\}", r"{p\1}", english))
        put(zh, k, named)
        notes[k] = f"On {where}. " + ", ".join(f"{{p{n}}}" for n in range(len(texts) // 2)) + " are values filled in by the page."
        by_text[named] = k
        added += 1
        return k

    def call(fn: str, k: str, exprs: list[str]) -> str:
        return f"{fn}('{k}')" if not exprs else f"{fn}('{k}', {{ " + ", ".join(f"p{n}: {e.strip()}" for n, e in enumerate(exprs)) + " })"

    def in_expression(code: str, fn: str) -> str:
        """Inside a template expression or script code: quoted text -> fn('key'); `text ${value}` -> fn('key', {p0}).
        Not a text something is compared with: that is data."""
        def quoted(m: re.Match) -> str:
            before, value = code[max(0, m.start() - 5):m.start()], m.group(2)
            if not CJK.search(value) or "\\" in value or value != value.strip() or re.search(r"[!=]==?\s*$", before) or re.match(r"\s*[!=]==?", code[m.end():m.end() + 5]):
                return m.group(0)
            k = key_for(value)
            return m.group(0) if k is None else f"{fn}('{k}')"

        def templated(m: re.Match) -> str:
            body = m.group(1)
            if not CJK.search(body) or "`" in body:
                return m.group(0)
            parts = re.split(r"\$\{([^{}]*)\}", body)
            if len(parts) == 1:
                k = key_for(body)
                return m.group(0) if k is None else f"{fn}('{k}')"
            k = pattern_key(parts)
            return m.group(0) if k is None else call(fn, k, parts[1::2])

        code = re.sub(r"`([^`]*)`", templated, code)
        return re.sub(r"(['\"])([^'\"\n]*)\1", quoted, code)

    tpl_start, tpl_end = src.index("<template>"), src.rindex("</template>")
    head, tpl, tail = src[:tpl_start], src[tpl_start:tpl_end], src[tpl_end:]

    # text inside {{ }} and inside bound attributes (:x="...", @x="...", v-for) first: what is left is plain text
    tpl = re.sub(r"\{\{(.*?)\}\}", lambda m: "{{" + in_expression(m.group(1), "$t") + "}}", tpl)
    tpl = re.sub(r"((?:[:@][\w.-]+|v-for|v-bind)=)\"([^\"]*)\"", lambda m: m.group(1) + '"' + in_expression(m.group(2), "$t") + '"' if not m.group(1).startswith((":key", ":class", ":style")) else m.group(0), tpl)

    # template text nodes: only text, or text around {{ values }}. (The values are put aside first: an arrow function in
    # one - `(r) => r.name` - has a ">" that is not the end of a tag.)
    stash: list[str] = []

    def keep(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    tpl = re.sub(r"\{\{.*?\}\}", keep, tpl, flags=re.S)
    back = lambda s: re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], s)  # noqa: E731

    def text_node(m: re.Match) -> str:
        inner = m.group(1)
        if not CJK.search(re.sub(r"\x00\d+\x00", "", inner)):
            return m.group(0)
        lead, trail = re.match(r"^\s*", inner).group(0), re.search(r"\s*$", inner).group(0)
        if "\x00" in inner:
            parts = re.split(r"\{\{(.*?)\}\}", back(inner.strip()), flags=re.S)
            k = pattern_key(parts)
            return m.group(0) if k is None else f">{lead}{{{{ {call('$t', k, parts[1::2])} }}}}{trail}<"
        k = key_for(inner)
        if k is None:
            return m.group(0)
        return f">{lead}{{{{ $t('{k}') }}}}{trail}<"

    tpl = back(re.sub(r">([^<>]+)<", text_node, tpl))

    # attributes whose value is only text
    def attr(m: re.Match) -> str:
        name, value = m.group(1), m.group(2)
        if not CJK.search(value) or "{{" in value or name.startswith("v-"):
            return m.group(0)
        k = key_for(value)
        return m.group(0) if k is None else f":{name}=\"$t('{k}')\""

    tpl = re.sub(r"(?<![:@\w-])([a-z][\w-]*)=\"([^\"]*)\"", attr, tpl)

    # script string literals that are only text
    def literal(m: re.Match) -> str:
        q, value = m.group(1), m.group(2)
        if not CJK.search(value) or "\\" in value:
            return m.group(0)
        k = key_for(value)
        return m.group(0) if k is None else f"T('{k}')"

    def script_part(text: str) -> str:
        out = []
        for line in text.split("\n"):
            code, sep, comment = line.partition("//") if "'//" not in line and '"//' not in line and "://" not in line else (line, "", "")
            if not code.lstrip().startswith("import "):
                code = in_expression(code, "T")
            out.append(code + sep + comment)
        return "\n".join(out)

    head = script_part(head)
    for i, line in enumerate(without_comments(head + tpl).split("\n"), 1):
        code = line.split("//")[0] if not line.lstrip().startswith("<") else line
        if CJK.search(code):
            left.append(f"{i}: {line.strip()[:160]}")
    # (T, not t: a page often calls a row of its list `t`)
    if "import { t as T }" not in head and "T('" in head:
        up = "../" * (len(path.resolve().relative_to(ROOT).parts) - 1) or "./"
        head = head.replace("<script setup>\n", f"<script setup>\nimport {{ t as T }} from '{up}i18n/catalog'\n", 1)

    print(f"{added} keys added; {len(set(missing))} texts without an English translation; {len(left)} lines left for the hand")
    for m in sorted(set(missing))[:60]:
        print("  no English:", m)
    for x in left[:200]:
        print("  left:", x)
    if write:
        path.write_text(head + tpl + tail, encoding="utf-8", newline="\n")
        for name, tree in (("en.json", en), ("zh.json", zh), ("notes.json", notes)):
            (LOC / name).write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
