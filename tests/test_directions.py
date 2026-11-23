"""A posting's field from a fixed list (2026-11-23): 1,200 postings had 502 different "directions" - whatever the model
wrote, in two languages ("其他", "other", "全栈/后端", "other (mining engineering)", "MLE/时序预测" ...). The filter listed
them all, and a reader in another language read them as they were written."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoapply import db, directions

LOCALES = Path(__file__).resolve().parent.parent / "frontend" / "src" / "locales"


def _name(cat: dict, key: str) -> str | None:
    node: object = cat
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def test_every_field_and_specialty_has_a_name_in_every_language():
    for lang in ("en", "zh", "fr"):
        cat = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for k in directions.KEYS:
            name = _name(cat, "direction." + (k if "." in k else k + "._"))
            assert name and name.strip(), (lang, k)
        assert _name(cat, "direction.unsorted")
    # the list: fields, each with its specialties, and "other"; a key is lower-case words
    assert "software.backend" in directions.KEYS and "civil.mining" in directions.KEYS and "other" in directions.KEYS
    assert all(k.replace(".", "").isalpha() and k == k.lower() for k in directions.KEYS) and len(set(directions.KEYS)) == len(directions.KEYS)


def test_the_model_can_only_pick_from_the_list_and_a_word_outside_it_changes_nothing(app_env, monkeypatch):
    from autoapply import knowledge, llm, scoring
    from autoapply.models import Job

    knowledge.write("profile", "# Profile\n\n## Education\n\n- A University, BASc, Computer Engineering, 2023 - 2028\n")
    with db.session() as s:
        s.add(Job(source="manual", source_id="d1", company="Acme", title="Backend Developer Co-op", jd_text="Build APIs in Go. " * 30, direction="后端"))
    asked = {}

    def answer(prompt, schema, **k):
        asked["schema"] = schema
        return {"excluded": False, "exclusion_rule": "", "score": 8, "direction": asked.get("give", "software.backend"), "reason": "r", "term": "", "months": "", "summary": "s", "brief": ""}

    monkeypatch.setattr(llm, "json", answer)
    with db.session() as s:
        jid = s.query(Job).one().id
    scoring.score_job(jid)
    prop = asked["schema"]["properties"]["direction"]
    assert prop["enum"] == directions.KEYS and "software.backend = server-side" in prop["description"]
    with db.session() as s:
        assert s.get(Job, jid).direction == "software.backend"
    asked["give"] = "Backend / 后端"                      # (a model that answers outside the list: what the posting had stays)
    scoring.score_job(jid)
    with db.session() as s:
        assert s.get(Job, jid).direction == "software.backend"


def test_postings_labelled_before_the_list_are_sorted_into_it_by_the_model(app_env, monkeypatch):
    from autoapply import llm, tasks
    from autoapply.models import Job, Task

    old = {"p1": ("Backend Developer Co-op", "全栈/后端"), "p2": ("Mine Planning Engineer Co-op", "other (mining engineering)"),
           "p3": ("ML Intern", "MLE/时序预测"), "p4": ("Data Analyst Intern", "数据分析"), "p5": ("Not read yet", ""), "p6": ("Firmware Co-op", "hardware.digital")}
    with db.session() as s:
        for sid, (title, label) in old.items():
            s.add(Job(source="manual", source_id=sid, company="Acme", title=title, direction=label, summary=f"About {title}"))
    seen = []
    pick = {"Backend Developer Co-op": "software.backend", "Mine Planning Engineer Co-op": "civil.mining", "ML Intern": "software.ml", "Data Analyst Intern": "not a key"}

    def answer(prompt, schema, **k):
        seen.append(prompt)
        assert schema["properties"]["postings"]["items"]["properties"]["direction"]["enum"] == directions.KEYS
        rows = [json.loads(line) for line in prompt.split("<postings>\n", 1)[1].split("\n</postings>")[0].splitlines()]
        return {"postings": [{"id": r["id"], "direction": pick[r["title"]]} for r in rows]}

    monkeypatch.setattr(llm, "json", answer)
    assert len(directions.unsorted_ids()) == 4                  # a key, and no label at all, are not "before the list"
    out = directions.sort_unsorted()
    assert out == {"sorted": 3, "left": 1}
    assert "全栈/后端" in seen[0] and "Mine Planning Engineer Co-op" in seen[0] and "civil.mining = mining" in seen[0]
    with db.session() as s:
        got = {j.source_id: j.direction for j in s.query(Job)}
    assert got == {"p1": "software.backend", "p2": "civil.mining", "p3": "software.ml", "p4": "数据分析", "p5": "", "p6": "hardware.digital"}
    # the task: sorts, and goes on only while a round sorts something
    from autoapply import handlers

    monkeypatch.setattr(directions, "sort_unsorted", lambda: {"sorted": 40, "left": 12})
    handlers._directions(Task(kind="directions", ref="unsorted", payload={}))
    with db.session() as s:
        assert s.query(Task).filter_by(kind="directions").count() == 1
    assert tasks is not None


def test_a_table_brought_in_again_does_not_undo_a_sorted_field(app_env, tmp_path, monkeypatch):
    from autoapply import importer, tasks
    from autoapply.models import Job

    queued = []
    monkeypatch.setattr(tasks, "enqueue", lambda kind, **k: queued.append(kind) or 1)
    head = "\t".join(["ID", "岗位", "公司", "方向", "评分", "学期", "月数", "薪资", "工作类型", "截止时间", "投递渠道", "登记状态", "投递情况", "岗位说明"])
    row = lambda sid, d: "\t".join([sid, "Backend Co-op", "Acme", d, "8", "", "", "", "", "", "", "新增意向", "", "x"])  # noqa: E731
    f = tmp_path / "jobs.tsv"
    f.write_text("\n".join([head, row("150001", "后端"), row("150002", "全栈")]) + "\n", encoding="utf-8")
    importer.import_tsv(f)
    assert queued == ["directions"]
    with db.session() as s:
        s.query(Job).filter_by(source_id="150001").one().direction = "software.backend"
    importer.import_tsv(f)
    with db.session() as s:
        assert {j.source_id: j.direction for j in s.query(Job)} == {"150001": "software.backend", "150002": "全栈"}


@pytest.mark.parametrize("value, ok", [("software.backend", True), ("software", True), ("other", True), ("Software.Backend", False), ("后端", False), ("", False), (None, False)])
def test_what_is_a_key(value, ok):
    assert directions.valid(value) is ok
    assert directions.coerce(value) == (value.lower() if value and value.lower() in directions.KEYS else "")
