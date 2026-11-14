"""Translate the interface text collected by i18n_extract.py. Only units that have no translation yet are sent.

    uv run python scripts/i18n_translate.py [en]

Uses whichever AI service the program is set up with. The result (frontend/src/i18n/<lang>.json) is a plain
{"中文": "English"} file: review it and correct by hand - corrected entries are never overwritten.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from autoapply import db, llm, net  # noqa: E402

LANGS = {"en": "English"}
SYSTEM = """You translate the interface text of a job-application assistant from Simplified Chinese into {lang}.
The reader is a job seeker using the app; the tone is plain, direct and friendly, like good product copy - not literal.
Rules:
- {{0}}, {{1}} ... are values filled in at run time: keep every one of them, exactly, and put it where {lang} word order wants it.
- Keep product and site names, file names, code, URLs, keys and anything already in Latin letters as they are.
- Keep it short: buttons and labels are a few words. Do not add explanations, quotes or trailing punctuation that the source lacks.
- Use one consistent term per concept: 草案 = draft, 岗位 = posting (job in short labels), 投递 / 申请 = application / apply,
  需要我处理 = Needs you, 个人资料 = Profile, 材料库 = Files, 求职信 = cover letter, 简历 = résumé, 重点雇主 = priority employer,
  评分 = score, 入库条件 = intake rules, 归档 = archive, 待办 = to-do, 第三方账号 = sign-in provider.
Return one translation per item, with the same id."""
SCHEMA = llm.obj({"items": {"type": "array", "items": llm.obj({"id": {"type": "integer"}, "t": {"type": "string"}})}})


def slots(s: str) -> list[str]:
    return sorted(re.findall(r"\{\d+\}", s))


def main() -> None:
    lang = sys.argv[1] if len(sys.argv) > 1 else "en"
    db.init_db()
    net.apply()
    d = ROOT / "frontend" / "src" / "i18n"
    src = json.loads((d / "zh.json").read_text(encoding="utf-8"))
    out_path = d / f"{lang}.json"
    done: dict[str, str] = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    todo = [s for s in src if s not in done]
    print(f"{len(src)} units, {len(todo)} to translate", flush=True)
    for i in range(0, len(todo), 90):
        batch = todo[i:i + 90]
        listing = "\n".join(f"{n}\t{s}" for n, s in enumerate(batch))
        try:
            got = llm.json(f"Translate these {len(batch)} items (id, tab, text):\n\n{listing}", SCHEMA, system=SYSTEM.format(lang=LANGS[lang]))["items"]
        except llm.LLMError as e:
            print("stopped:", str(e)[:200], flush=True)
            break
        bad = 0
        for it in got:
            if 0 <= it["id"] < len(batch) and it["t"].strip():
                s = batch[it["id"]]
                if slots(s) == slots(it["t"]):  # a translation that lost or invented a value is not kept
                    done[s] = it["t"].strip()
                else:
                    bad += 1
        out_path.write_text(json.dumps(dict(sorted(done.items(), key=lambda kv: (len(kv[0]), kv[0]))), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        print(f"  {min(i + 90, len(todo))}/{len(todo)}" + (f"  ({bad} rejected: values did not match)" if bad else ""), flush=True)
    left = [s for s in src if s not in done]
    print(f"done: {len(done)} translated, {len(left)} left", flush=True)


if __name__ == "__main__":
    main()
