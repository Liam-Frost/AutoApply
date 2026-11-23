"""Screenshots of the interface for looking at a change before it is released, and for comparing before with after.

Every page (and every section of the UI lab) at several widths, in both themes and both languages, of an instance that
is ALREADY RUNNING - by default the demo (made-up data):

    uv run python scripts/demo.py --serve 8022                       a demo copy to take them from
    uv run python scripts/ui_shots.py --out shots/after              everything (several hundred pictures, some minutes)
    uv run python scripts/ui_shots.py --out shots/after --pages jobs,applications --widths 1440,1024 --langs en
    uv run python scripts/ui_shots.py --out shots/after --compare shots/before

`--compare OTHER` puts the pictures of OTHER beside the new ones: for each name, the share of pixels that differ by
more than a small amount; for those that differ, a side-by-side (other | this | where they differ) in OUT/diff, with
an index.html to page through. It is an aid for a person's eyes, NOT a gate for CI: fonts and text rendering differ
between computers, so two computers never give the same pixels - compare only pictures taken on one computer, from the
same data (the same demo copy, or two copies seeded on the same day).

Kept stable on purpose: animations off (prefers-reduced-motion, and none while the picture is taken), a fixed window
and device scale, no text caret, and the page's clock held at noon of today (so "3 hours ago" does not change while
the pictures are taken). Only pages are opened: nothing is pressed, nothing is changed.

It refuses an address on port 8000 - where a real installation listens - unless --i-know is given: pictures of your
own applications, accounts and mail do not belong in a folder of screenshots.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

WIDTHS = [1920, 1600, 1440, 1280, 1024]
HEIGHT = 900
THEMES = ["light", "dark"]
LANGS = ["zh", "en"]
LAB_WIDTHS = [1440, 640]

# name -> address: every page with each of its views and groups (the same walk as tests/test_ui_pages.py routes()).
# ({application} is the first application the instance has.)
PAGES = {
    "home": "/home",
    "todos": "/todos",
    "calendar": "/calendar",
    "calendar-week": "/calendar?view=week",
    "calendar-day": "/calendar?view=day",
    "jobs": "/jobs",
    "jobs-started": "/jobs?group=started",
    "jobs-skip": "/jobs?group=skip",
    "jobs-closed": "/jobs?group=closed",
    "sources": "/jobs/sources",
    "applications": "/applications",
    "applications-agent": "/applications?group=agent",
    "applications-sent": "/applications?group=sent",
    "applications-progress": "/applications?group=progress",
    "applications-ended": "/applications?group=ended",
    "applications-archived": "/applications?group=archived",
    "application": "/applications/{application}",
    "profile": "/profile",
    "files": "/files",
    "contacts": "/contacts",
    "accounts": "/accounts",
    "analytics": "/analytics?view=apps",
    "analytics-auto": "/analytics?view=auto",
    "analytics-sites": "/analytics?view=sites",
    "analytics-ai": "/analytics?view=ai",
    "runs": "/runs",
    "settings": "/settings",
    "settings-goals": "/settings/goals",
    "settings-automation": "/settings/automation",
    "settings-materials": "/settings/materials",
    "settings-accounts": "/settings/accounts",
    "settings-notify": "/settings/notify",
    "settings-system": "/settings/system",
    "about": "/about",
    "about-changelog": "/about/changelog",
    "about-licenses": "/about/licenses",
}


def settle(page) -> None:
    """The page has what it shows: its data, its fonts, its tables' columns."""
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:  # noqa: BLE001, S110 (a page that keeps asking the server is photographed as it is)
        pass
    try:
        page.wait_for_function("() => !document.querySelector('.data-wait') && document.fonts.status === 'loaded'", timeout=8_000)
    except Exception:  # noqa: BLE001, S110
        pass
    page.evaluate("() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")


def take(a: argparse.Namespace) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    base = a.base.rstrip("/")
    noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) if not a.clock else datetime.fromisoformat(a.clock)
    taken: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # what the instance has: an application to open, and the sections of the lab
        probe = browser.new_context(base_url=base)
        try:
            apps = probe.request.get(base + "/api/applications").json().get("applications") or []
        except Exception as e:  # noqa: BLE001
            sys.exit(f"{base} does not answer like AutoApply ({e}). Start a demo copy first: uv run python scripts/demo.py --serve 8022")
        first = apps[0]["id"] if apps else None
        page = probe.new_page()
        page.goto("/ui-lab", wait_until="networkidle")
        sections = page.evaluate("() => [...document.querySelectorAll('[data-lab]')].map((s) => s.dataset.lab)")
        probe.close()

        jobs: list[tuple[str, str, int]] = []      # (name, address, width)
        for name, path in PAGES.items():
            if a.pages and name not in a.pages:
                continue
            if "{application}" in path:
                if first is None:
                    continue
                path = path.format(application=first)
            jobs += [(name, path, w) for w in a.widths]
        if not a.no_lab:
            for s in sections:
                if a.pages and "lab" not in a.pages and "lab-" + s not in a.pages:
                    continue
                jobs += [("lab-" + s, "/ui-lab?only=" + s, w) for w in a.lab_widths]
        if not jobs:
            sys.exit("nothing to take: no page of that name (pages: " + ", ".join(PAGES) + ", lab, lab-<Section>)")
        total = len(jobs) * len(a.themes) * len(a.langs)
        print(f"{total} pictures of {base} into {out}")
        t0 = time.time()
        for theme in a.themes:
            for lang in a.langs:
                for width in sorted({w for _, _, w in jobs}):
                    ctx = browser.new_context(base_url=base, viewport={"width": width, "height": HEIGHT}, device_scale_factor=1, color_scheme=theme, reduced_motion="reduce",
                                              locale="zh-CN" if lang == "zh" else "en-US", timezone_id=a.timezone)
                    ctx.add_init_script(f"try {{ localStorage.setItem('lang', '{lang}'); localStorage.setItem('theme', '{theme}') }} catch (e) {{}}")
                    page = ctx.new_page()
                    if hasattr(page, "clock"):      # (Playwright 1.45 and later)
                        page.clock.set_fixed_time(noon)
                    for name, path, w in jobs:
                        if w != width:
                            continue
                        page.goto(path)
                        settle(page)
                        png = out / f"{name}__{width}__{theme}__{lang}.png"
                        page.screenshot(path=str(png), full_page=True, animations="disabled", caret="hide")
                        taken.append(png)
                        if len(taken) % 20 == 0:
                            print(f"  {len(taken)}/{total}  ({time.time() - t0:.0f}s)")
                    ctx.close()
        browser.close()
    print(f"{len(taken)} pictures in {time.time() - t0:.0f}s")
    return taken


def compare(out: Path, other: Path, taken: list[Path], *, threshold: int, min_ratio: float) -> None:
    """Each picture beside the one of the same name in `other`: how much of it differs, and a side-by-side for a person
    to look at when it does. `other` may also hold pictures of one size and look named by the page alone (home.png,
    applications-sent.png - a set taken by hand): a picture is then compared with the one of its page."""
    from PIL import Image, ImageChops

    names = sorted(p.name for p in taken) if taken else sorted(p.name for p in out.glob("*.png"))
    there = {p.name for p in other.glob("*.png")}
    diff_dir = out / "diff"
    diff_dir.mkdir(exist_ok=True)
    rows: list[tuple[float, str, str]] = []
    used: set[str] = set()
    for name in names:
        match = name if name in there else name.split("__")[0] + ".png" if name.split("__")[0] + ".png" in there else None
        if match is None:
            rows.append((1.0, name, "new: not in " + str(other)))
            continue
        used.add(match)
        new, old = Image.open(out / name).convert("RGB"), Image.open(other / match).convert("RGB")
        note = "" if new.size == old.size else f"size {old.size[0]}x{old.size[1]} -> {new.size[0]}x{new.size[1]}"
        w, h = max(new.width, old.width), max(new.height, old.height)

        def on_canvas(im):  # noqa: ANN001, ANN202 (a page that got longer is compared over the longer of the two)
            if im.size == (w, h):
                return im
            canvas = Image.new("RGB", (w, h), (255, 0, 255))
            canvas.paste(im, (0, 0))
            return canvas

        new, old = on_canvas(new), on_canvas(old)
        delta = ImageChops.difference(new, old).convert("L").point(lambda v: 255 if v > threshold else 0)
        ratio = delta.histogram()[255] / (w * h)
        rows.append((ratio, name, note))
        if ratio > min_ratio or note:
            marked = Image.composite(Image.new("RGB", (w, h), (255, 0, 80)), new.point(lambda v: 128 + v // 2), delta)      # the new picture, faded, the differences in red
            side = Image.new("RGB", (w * 3 + 32, h), (128, 128, 128))
            for i, im in enumerate((old, new, marked)):
                side.paste(im, (i * (w + 16), 0))
            side.save(diff_dir / name)
    gone = sorted(there - used) if not taken else []
    rows.sort(reverse=True)
    differ = [r for r in rows if r[0] > min_ratio or r[2]]
    lines = [f"{ratio * 100:7.3f}%  {name}  {note}".rstrip() for ratio, name, note in rows]
    (out / "compare.txt").write_text("\n".join(lines + ["gone: " + g for g in gone]) + "\n", encoding="utf-8")
    html = ["<!doctype html><meta charset='utf-8'><title>UI comparison</title><style>body{font:14px system-ui;margin:24px;background:#888;color:#fff}img{max-width:100%;display:block;margin:8px 0 32px}</style>",
            f"<h1>{len(differ)} of {len(rows)} pictures differ</h1><p>left: {other} &nbsp; middle: {out} &nbsp; right: where they differ. Share of pixels that differ by more than {threshold}/255.</p>"]
    html += [f"<h3>{ratio * 100:.3f}% &nbsp; {name} &nbsp; {note}</h3><img loading='lazy' src='{name}'>" for ratio, name, note in differ if (diff_dir / name).exists()]
    (diff_dir / "index.html").write_text("\n".join(html), encoding="utf-8")
    print(f"\n{len(differ)} of {len(rows)} pictures differ from {other} (more than {min_ratio * 100:.2f}% of the pixels, or another size)")
    for line in lines[:25]:
        print(" ", line)
    if len(lines) > 25:
        print(f"  ... the rest in {out / 'compare.txt'}")
    for g in gone:
        print("  gone:", g)
    print(f"side-by-sides: {diff_dir / 'index.html'}")
    print("This is for a person to look through - not a pass or a fail. Pictures from two different computers always differ (fonts).")


def main() -> None:
    def listed(kind):  # noqa: ANN001, ANN202
        return lambda v: [kind(x) for x in v.split(",") if x.strip()]

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://127.0.0.1:8022", help="the running instance (default: the demo on 8022)")
    ap.add_argument("--out", required=True, help="the folder the pictures go into")
    ap.add_argument("--compare", metavar="OTHER_DIR", help="compare with the pictures of the same names in this folder")
    ap.add_argument("--only-compare", action="store_true", help="take nothing: compare what is in --out with --compare")
    ap.add_argument("--pages", type=listed(str), default=[], help="some of: " + ", ".join(PAGES) + ", lab, lab-<Section> (default: all)")
    ap.add_argument("--widths", type=listed(int), default=WIDTHS, help="default " + ",".join(map(str, WIDTHS)))
    ap.add_argument("--lab-widths", type=listed(int), default=LAB_WIDTHS, help="default " + ",".join(map(str, LAB_WIDTHS)))
    ap.add_argument("--themes", type=listed(str), default=THEMES, help="default light,dark")
    ap.add_argument("--langs", type=listed(str), default=LANGS, help="default zh,en")
    ap.add_argument("--no-lab", action="store_true", help="leave the UI lab out")
    ap.add_argument("--clock", metavar="ISO", help="the time the pages believe it is (default: noon today)")
    ap.add_argument("--timezone", default="America/Vancouver", help="the time zone the pages are shown in (the demo's applicant lives there)")
    ap.add_argument("--threshold", type=int, default=16, help="with --compare: a pixel differs when a channel differs by more than this (0-255, default 16)")
    ap.add_argument("--min-ratio", type=float, default=0.0005, help="with --compare: a picture differs when more than this share of its pixels does (default 0.0005)")
    ap.add_argument("--i-know", action="store_true", help="allow an address on port 8000 (a real installation: your own data ends up in the pictures)")
    a = ap.parse_args()
    url = urlparse(a.base)
    if url.scheme not in ("http", "https") or not url.hostname:
        sys.exit("--base is an address like http://127.0.0.1:8022")
    if (url.port or (443 if url.scheme == "https" else 80)) == 8000 and not a.i_know:
        sys.exit("Port 8000 is where a real installation listens: its pictures would show your own applications, accounts and mail.\n"
                 "Take them from a demo copy (uv run python scripts/demo.py --serve 8022), or pass --i-know if this really is what you want.")
    unknown = [p for p in a.pages if p not in PAGES and p != "lab" and not p.startswith("lab-")]
    if unknown:
        sys.exit("no such page: " + ", ".join(unknown) + " (pages: " + ", ".join(PAGES) + ", lab, lab-<Section>)")
    taken = [] if a.only_compare else take(a)
    if a.compare:
        other = Path(a.compare)
        if not other.is_dir():
            sys.exit(f"{other} is not a folder of pictures")
        compare(Path(a.out), other, taken, threshold=a.threshold, min_ratio=a.min_ratio)


if __name__ == "__main__":
    main()
