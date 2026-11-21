"""Move the program's own sentences in a server module to message keys (plan §3.4, C3):
`uv run python scripts/i18n_server.py backend/autoapply/<module>.py [--write]`.

Every Chinese string the module shows - a literal, or an f-string with values in it - becomes `T("server.<module>.<key>",
p0=...)` (say.py's say): a string with the same Chinese as before (so nothing that compares, stores or logs it changes) that
carries its key, rendered in the page's or the notification's language where it leaves the program. The English is the
dictionary's (frontend/src/i18n/en.json, the same sentence with {0}, {1}); each key gets a note.

Left as they are: docstrings, text compared with something (it is data), text in logs, dictionary keys, text inside
regular expressions, and anything without an English translation (listed, for the hand).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend" / "autoapply"
CAT = ROOT / "frontend" / "src" / "locales" / "server"
CJK = re.compile(r"[一-鿿]")
LOGS = {"debug", "info", "warning", "error", "exception", "critical", "log"}


def slug(english: str, taken: set[str], ns: str) -> str:
    words = re.findall(r"[A-Za-z]+", re.sub(r"\{\d+\}", "", english).replace("'", ""))[:4] or ["text"]
    base = words[0].lower() + "".join(w.capitalize() for w in words[1:])
    key, n = f"{ns}.{base}", 2
    while key in taken:
        key, n = f"{ns}.{base}{n}", n + 1
    taken.add(key)
    return key


def load(name: str) -> dict:
    try:
        return json.loads((CAT / name).read_text(encoding="utf-8"))
    except OSError:
        return {}


def main() -> None:
    path, write = Path(sys.argv[1]).resolve(), "--write" in sys.argv
    rel = path.relative_to(BACKEND)
    ns = "server." + ".".join(rel.with_suffix("").parts)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    dictionary = json.loads((ROOT / "frontend" / "src" / "i18n" / "en.json").read_text(encoding="utf-8"))
    en, zh, notes = load("en.json"), load("zh.json"), load("notes.json")
    taken = set(en)
    by_text = {v: k for k, v in zh.items() if k.startswith(ns + ".")}
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    lines = src.split("\n")
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln) + 1)

    def pos(lineno: int, col: int) -> int:      # (col_offset is in UTF-8 bytes)
        line = lines[lineno - 1]
        return offsets[lineno - 1] + len(line.encode("utf-8")[:col].decode("utf-8"))

    def excluded(node: ast.AST) -> bool:
        p = parents.get(id(node))
        child = node
        while p is not None:
            if isinstance(p, ast.Expr) and isinstance(child, (ast.Constant, ast.JoinedStr)):
                return True                                   # a docstring, a bare string
            if isinstance(p, ast.Compare):
                return True                                   # compared: data
            if isinstance(p, ast.Dict) and any(k is child for k in p.keys):
                return True                                   # a dictionary key
            if isinstance(p, ast.Call):
                f = p.func
                name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
                owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
                if name in LOGS and owner in ("log", "logging", "logger") or owner == "re" or name in ("compile", "search", "match", "sub", "fullmatch", "findall", "split",
                                                                                                   "startswith", "endswith", "say", "T"):
                    return True
            if isinstance(p, ast.Subscript) and child is p.slice:
                return True                                   # a key looked up: data
            if isinstance(p, ast.JoinedStr):
                return True                                   # inside an f-string: the f-string is the unit
            child, p = p, parents.get(id(p))
        return False

    edits: list[tuple[int, int, str]] = []
    missing: list[str] = []
    added = 0

    def key_for(zh_text: str, english: str, n_params: int) -> str:
        nonlocal added
        named = re.sub(r"\{(\d+)\}", r"{p\1}", zh_text)
        if named in by_text:
            return by_text[named]
        k = slug(english, taken, ns)
        en[k] = re.sub(r"\{(\d+)\}", r"{p\1}", english)
        zh[k] = named
        notes[k] = f"Said by the program ({rel.as_posix()})." + (" " + ", ".join(f"{{p{i}}}" for i in range(n_params)) + " are values it fills in." if n_params else "")
        by_text[named] = k
        added += 1
        return k

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK.search(node.value):
            if excluded(node) or "{" in node.value:
                continue
            text = node.value
            english = dictionary.get(re.sub(r"\s+", " ", text.strip()))
            if not english or text != text.strip():
                missing.append(text[:80])
                continue
            k = key_for(text, english, 0)
            edits.append((pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset), f'T("{k}")'))
        elif isinstance(node, ast.JoinedStr):
            texts, exprs = [], []
            ok = True
            for part in node.values:
                if isinstance(part, ast.Constant):
                    texts.append(str(part.value))
                elif isinstance(part, ast.FormattedValue):
                    seg = ast.get_source_segment(src, part.value)
                    if seg is None:
                        ok = False
                        break
                    if part.format_spec is not None:
                        spec = ast.get_source_segment(src, part.format_spec) or ""
                        spec_text = "".join(str(v.value) for v in part.format_spec.values if isinstance(v, ast.Constant)) if isinstance(part.format_spec, ast.JoinedStr) else ""
                        if not spec_text or any(not isinstance(v, ast.Constant) for v in part.format_spec.values):
                            ok = False
                            break
                        seg = f"format({seg}, {spec_text!r})"
                    elif part.conversion == ord("r"):
                        seg = f"repr({seg})"
                    texts.append("{" + str(len(exprs)) + "}")
                    exprs.append(seg)
            whole = "".join(texts)
            if not ok or not CJK.search(whole) or excluded(node):
                continue
            english = dictionary.get(re.sub(r"\s+", " ", whole.strip()))
            if not english or whole != whole.strip() or sorted(re.findall(r"\{\d+\}", english)) != sorted(re.findall(r"\{\d+\}", whole)):
                missing.append(whole[:80])
                continue
            k = key_for(whole, english, len(exprs))
            args = ", ".join(f"p{i}={e}" for i, e in enumerate(exprs))
            edits.append((pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset), f'T("{k}", {args})'))

    out = src
    for start, end, text in sorted(edits, reverse=True):
        out = out[:start] + text + out[end:]
    if edits and not re.search(r"^from \.+say import say as T$", out, re.M):
        dots = "." * len(rel.parts)
        line = f"from {dots}say import say as T"      # (T: "say" is a name some modules have for something else)
        m = re.search(r"^from __future__ import annotations\n", out, re.M)
        at = m.end() if m else 0
        out = out[:at] + ("\n" if m else "") + line + "\n" + out[at:]
    print(f"{rel}: {len(edits)} sentences to keys ({added} new); {len(missing)} left as they were")
    for x in sorted(set(missing))[:80]:
        print("  left:", x)
    if write:
        compile(out, str(path), "exec")
        path.write_text(out, encoding="utf-8", newline="\n")
        CAT.mkdir(parents=True, exist_ok=True)
        for name, d in (("en.json", en), ("zh.json", zh), ("notes.json", notes)):
            (CAT / name).write_text(json.dumps(dict(sorted(d.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
