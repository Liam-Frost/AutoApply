"""The JSON Schemas of changes/schema/ and a small validator for the part of JSON Schema they use.

The schemas are the one source of the lists of types and scopes; this module reads them from there. A full JSON Schema
library is not a dependency of the program (the app imports this package at run time), so the keywords the two schemas
use are checked here: $ref (inside the document), type, enum, const, pattern, minLength, maxLength, minimum, maximum,
required, properties, additionalProperties, items, minItems, maxItems, uniqueItems, anyOf, oneOf. Words for people
(description, title, default, format, $comment) are not checked. A test compares the result with the `jsonschema`
package where it is installed.
"""
from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

FRAGMENT = "fragment.schema.json"
MANIFEST = "manifest.schema.json"

At = tuple  # a place in a document: ("summary", "en"), ("fragments", 3, "id")


class SchemaError(Exception):
    """A schema file is missing or not a schema this module can use."""


def schema_dir(root: Path) -> Path:
    return Path(root) / "changes" / "schema"


@lru_cache(maxsize=16)
def _load(path: str, stamp: tuple[int, int]) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise SchemaError(f"{path}: not readable as JSON ({e})") from e
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: not a JSON Schema object")
    return data


def load(root: Path, name: str) -> dict[str, Any]:
    """One schema of changes/schema/ (read again when the file changes)."""
    p = schema_dir(root) / name
    try:
        st = p.stat()
    except OSError as e:
        raise SchemaError(f"{p}: missing") from e
    return _load(str(p), (st.st_mtime_ns, st.st_size))


def enum_of(root: Path, field: str) -> list[str]:
    """The allowed values of a fragment's front-matter field (`type`, `scope`, `bump`), in the schema's order."""
    values = (load(root, FRAGMENT).get("properties") or {}).get(field, {}).get("enum")
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise SchemaError(f"{FRAGMENT}: properties.{field}.enum is not a list of strings")
    return list(values)


def pattern_of(root: Path, name: str, *where: str) -> str:
    node: Any = load(root, name)
    for key in where:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    if not isinstance(node, dict) or not isinstance(node.get("pattern"), str):
        raise SchemaError(f"{name}: {'.'.join(where)}.pattern is missing")
    return node["pattern"]


# --- the validator ----------------------------------------------------------------------------------------------------
def _kind(value: Any) -> str:
    """The JSON type of a value as a person reads it (a YAML date is called a date: it should have been quoted)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__  # date, datetime (unquoted YAML dates)


_WORDS = {"string": "a string", "integer": "an integer", "number": "a number", "boolean": "true or false",
          "array": "a list", "object": "a mapping", "null": "null"}


def _is(value: Any, t: str) -> bool:
    k = _kind(value)
    return k == t or (t == "number" and k == "integer")


def _resolve(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise SchemaError(f"only references inside the document are supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(node, dict) else None
    if not isinstance(node, dict):
        raise SchemaError(f"unresolvable reference {ref}")
    return node


def _short(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


def check(schema: dict[str, Any], value: Any, root: dict[str, Any] | None = None, at: At = ()) -> list[tuple[At, str]]:
    """Every way `value` breaks `schema`: [(where, message)]. Empty when it conforms."""
    root = root if root is not None else schema
    out: list[tuple[At, str]] = []
    if "$ref" in schema:
        out += check(_resolve(schema["$ref"], root), value, root, at)
        schema = {k: v for k, v in schema.items() if k != "$ref"}

    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is(value, x) for x in types):
            out.append((at, f"expected {' or '.join(_WORDS.get(x, x) for x in types)}, found {_WORDS.get(_kind(value), _kind(value))}"
                            + (" (quote it)" if _kind(value) in ("date", "datetime") else "")))
            return out
    if "enum" in schema and value not in schema["enum"]:
        out.append((at, f"{_short(value)} is not one of: {', '.join(str(v) for v in schema['enum'])}"))
    if "const" in schema and value != schema["const"]:
        out.append((at, f"must be {_short(schema['const'])}"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append((at, "must not be empty" if schema["minLength"] == 1 else f"at least {schema['minLength']} characters"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append((at, f"at most {schema['maxLength']} characters (has {len(value)})"))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append((at, f"{_short(value)} does not have the required form ({schema['pattern']})"))
    if _kind(value) in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            out.append((at, f"must be at least {schema['minimum']}"))
        if "maximum" in schema and value > schema["maximum"]:
            out.append((at, f"must be at most {schema['maximum']}"))

    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                out.append((at, f"missing required field \"{key}\""))
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                out += check(props[key], item, root, at + (key,))
            elif extra is False:
                near = difflib.get_close_matches(str(key), list(props), n=1)
                out.append((at + (key,), f"unknown field \"{key}\"" + (f" (did you mean \"{near[0]}\"?)" if near else "")
                            + f"; allowed: {', '.join(props)}"))
            elif isinstance(extra, dict):
                out += check(extra, item, root, at + (key,))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append((at, "must not be empty" if schema["minItems"] == 1 else f"needs at least {schema['minItems']} items"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append((at, f"at most {schema['maxItems']} items"))
        if schema.get("uniqueItems"):
            seen: list[Any] = []
            for i, item in enumerate(value):
                if item in seen:
                    out.append((at + (i,), f"{_short(item)} is listed twice"))
                seen.append(item)
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                out += check(schema["items"], item, root, at + (i,))

    for word in ("anyOf", "oneOf"):
        options = schema.get(word)
        if not isinstance(options, list):
            continue
        results = [check(o, value, root, at) for o in options]
        passing = sum(1 for r in results if not r)
        if word == "anyOf" and passing == 0 or word == "oneOf" and passing != 1:
            if word == "oneOf" and passing > 1:
                out.append((at, "matches more than one allowed form"))
                continue
            # the option of the value's own type says best what is wrong; otherwise name the forms allowed
            typed = [r for o, r in zip(options, results) if _type_fits(o, value, root)]
            if typed:
                out += typed[0]
            else:
                forms = list(dict.fromkeys(_WORDS.get(x, x) for o in options for x in _types_of(o, root)))
                out.append((at, f"expected {' or '.join(forms) or 'another form'}, found {_WORDS.get(_kind(value), _kind(value))}"))
    return out


def _types_of(schema: dict[str, Any], root: dict[str, Any]) -> list[str]:
    if "$ref" in schema:
        return _types_of(_resolve(schema["$ref"], root), root) + _types_of({k: v for k, v in schema.items() if k != "$ref"}, root)
    t = schema.get("type")
    return [t] if isinstance(t, str) else list(t or [])


def _type_fits(schema: dict[str, Any], value: Any, root: dict[str, Any]) -> bool:
    types = _types_of(schema, root)
    return bool(types) and any(_is(value, t) for t in types)


def where(at: At) -> str:
    """("summary", "en") -> "summary.en"; ("fragments", 3, "id") -> "fragments[3].id"."""
    out = ""
    for part in at:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out
