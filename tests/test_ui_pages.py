"""The program's own pages, measured in a browser with made-up data that is hard to draw (tests/ui_data.py: the longest
and the shortest names, Chinese ones, a posting without a title, a calendar item with an absurd title, site accounts in
every state): the page-level half of docs/ui-quality-assurance.md. test_ui_layout.py checks the shared components on
the UI lab; this checks that the pages use them so that the guarantees hold where a person looks.

As there, nothing here knows how wide a text is: boxes are compared with each other, with the tokens and with the
column bounds a page declares, to within a pixel. Every page is walked at 1440x900, 1280x800 and 1024x768, in English
and Chinese (French at 1440 - the longest words - and one dark pass).
"""

from __future__ import annotations

import json
import re
import urllib.request

import pytest

import ui_data
import ui_server
from test_ui_layout import INSIDE, PX, ROW, TIP, frames, hover, tip_text

SIZES = {1440: 900, 1280: 800, 1024: 768}


# ── the pages in a browser ───────────────────────────────────────────────────────────────────────────────────────────
# Requests that are on their way (the page's own fetches): a page is measured once it has what it shows.
BUSY = "(() => { let n = 0; const f = window.fetch; window.__aaBusy = 0; window.fetch = function (...a) { window.__aaBusy = ++n; return f.apply(this, a).finally(() => { window.__aaBusy = --n }) } })()"
SETTLED = """(lang) => document.documentElement.lang.toLowerCase().startsWith(lang) && document.fonts.status === 'loaded' && !document.querySelector('.data-wait')
  && window.__aaBusy === 0 && !!document.querySelector('main.content > :not(.remote-banner)')
  && [...document.querySelectorAll('main .dt-table')].every((t) => t.getBoundingClientRect().width > 0)"""


class Site:
    """One browser profile per size, theme and language, with one page in it that goes from address to address."""

    def __init__(self) -> None:
        self.contexts: dict = {}
        self.pages: dict = {}
        self.base = ui_server.server()
        self.apps = {r["company"] + "|" + r["status"]: r for r in self.api("/api/applications")["applications"]}

    def api(self, path: str, body: dict | None = None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 (the test copy on this computer)
            return json.load(r)

    def app_id(self, company: str, status: str) -> int:
        return self.apps[company + "|" + status]["id"]

    def page(self, width: int = 1440, lang: str = "en", theme: str = "light"):
        key = (width, lang, theme)
        if key not in self.pages:
            ctx = ui_server.context(width=width, height=SIZES[width], theme=theme, lang=lang)
            ctx.add_init_script(BUSY)
            self.contexts[key] = ctx
            page = ctx.new_page()
            page.set_default_timeout(10_000)
            self.pages[key] = page
        return self.pages[key]

    def go(self, path: str, width: int = 1440, lang: str = "en", theme: str = "light", *, reload: bool = False):
        """The page at an address, with what it shows. Within a profile the program goes there itself (its router, as a
        press on a link does): much quicker than loading it all again. `reload` loads it afresh (new data)."""
        page = self.page(width, lang, theme)
        page.mouse.move(2, 2)      # (no tooltip of the last page stays)
        if reload or not page.url.startswith(self.base):
            page.goto(path, wait_until="domcontentloaded")
        else:
            page.evaluate("(p) => document.querySelector('#app').__vue_app__.config.globalProperties.$router.push(p)", path)
        settle(page, lang)
        return page

    def close(self) -> None:
        for ctx in self.contexts.values():
            ctx.close()


def settle(page, lang: str) -> None:
    """The page has its data, its fonts and its tables' columns - and nothing more is on its way."""
    frames(page)      # (a page the router just went to is drawn, and has asked for its data, in the next frame)
    page.wait_for_function(SETTLED, arg=lang)
    page.wait_for_timeout(50)      # (what came back may ask for more: quiet twice)
    page.wait_for_function(SETTLED, arg=lang)
    frames(page)


@pytest.fixture(scope="module")
def site():
    ui_server.server()
    ui_server.browser()
    s = Site()
    yield s
    s.close()


def routes(site: Site) -> list[str]:
    """Every page a person can reach, with each of its views and groups. (Adding a page: add its address here and to
    PAGES in scripts/ui_shots.py - docs/ui-quality-assurance.md.)"""
    absurd = site.app_id(ui_data.CJK_COMPANY, "interview")
    long_one = site.app_id(ui_data.LONG_COMPANY, "draft_ready")
    return ["/home", "/todos", "/calendar?view=month", "/calendar?view=week", "/calendar?view=day",
            "/jobs", "/jobs?group=started", "/jobs?group=skip", "/jobs?group=closed", "/jobs/sources",
            *[f"/applications?group={g}" for g in ("me", "agent", "sent", "progress", "ended", "archived")],
            f"/applications/{absurd}", f"/applications/{long_one}",
            "/profile", "/files", "/contacts", "/accounts",
            "/analytics?view=apps", "/analytics?view=auto", "/analytics?view=sites", "/analytics?view=ai", "/runs",
            *[f"/settings/{g}" for g in ("overview", "goals", "automation", "materials", "accounts", "notify", "system")],
            "/about", "/about/changelog", "/about/licenses"]


# ── what every page is measured for ──────────────────────────────────────────────────────────────────────────────────
# One look at the page as it stands: its head, browser tooltips, buttons and links without a name, what reaches out of
# `main` (or is wider than it), the page scrolling sideways, and - when asked - one-line labels that broke.
AUDIT = """(oneLine) => {
  const main = document.querySelector('main.content')
  const mr = main.getBoundingClientRect()
  const desc = (el) => '<' + el.tagName.toLowerCase() + ' class="' + (el.getAttribute('class') || '') + '"> "' + (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40) + '"'
  const shown = (el) => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return (r.width > 0 || r.height > 0) && s.visibility !== 'hidden' }
  const nameOf = (el) => {
    const by = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).map((id) => document.getElementById(id)).filter(Boolean).map((e) => e.textContent).join(' ')
    const alt = [...el.querySelectorAll('img[alt]')].map((i) => i.alt).join(' ')
    return (by + ' ' + (el.getAttribute('aria-label') || '') + ' ' + el.textContent + ' ' + alt).trim()
  }
  const titled = [...main.querySelectorAll('[title]')].filter((e) => e.tagName !== 'IFRAME').map((e) => e.outerHTML.slice(0, 140))
  const nameless = [...main.querySelectorAll('button, a[href], [role="button"], [role="link"]')].filter(shown).filter((el) => !nameOf(el)).map((e) => e.outerHTML.slice(0, 140))
  // what reaches out of main: elements past its edges, unless something between them and main cuts them off (a table
  // that scrolls in its own box, a cut text), or they are fixed to the window
  const out = []
  const cut = (el) => { for (let p = el.parentElement; p && p !== main; p = p.parentElement) { const s = getComputedStyle(p); if (s.overflowX !== 'visible' || s.position === 'fixed') return true } return false }
  for (const el of main.querySelectorAll('*')) {
    if (out.length > 8) break
    const r = el.getBoundingClientRect()
    if (r.width <= 1 || (r.left >= mr.left - 1 && r.right <= mr.right + 1)) continue
    const s = getComputedStyle(el)      // (a hidden copy kept off the window to measure a label is not seen)
    if (s.position === 'fixed' || s.visibility === 'hidden' || cut(el) || out.some((o) => o.contains(el))) continue
    out.push(el)
  }
  const html = document.documentElement
  return {
    heads: main.querySelectorAll('.page-head h2').length,
    titled, nameless,
    out: out.map((el) => desc(el) + ' ' + Math.round(el.getBoundingClientRect().left) + '..' + Math.round(el.getBoundingClientRect().right) + ' in ' + Math.round(mr.left) + '..' + Math.round(mr.right)),
    sideways: [html, document.body, main].filter((e) => e.scrollWidth > e.clientWidth + 1).map((e) => e.tagName.toLowerCase() + ': ' + e.scrollWidth + ' in ' + e.clientWidth),
    buttons: main.querySelectorAll('button, a[href]').length,
  }
}"""
# What never takes two lines on a page: a button, a badge, a tab, a table's header.
ONE_LINE = "main button, main .tag, main [role=tab], main th"
# A label that broke: one of its texts runs over two lines, or - when everything in it is inline - its texts stand on
# more than one line. (Something made of two blocks on purpose - a day's name over its date in the calendar's week
# head, a posting's company over its title in a list - is not a broken label.)
WRAPPED = """(selector) => {
  const found = []
  const linesOf = (rects) => { let n = 0, bottom = -Infinity; for (const r of rects.filter((r) => r.width > 0 && r.height > 0).sort((a, b) => a.top - b.top)) { if (r.top + r.height / 2 > bottom) n++; bottom = Math.max(bottom, r.bottom) } return n }
  const clamped = (from, to) => { for (let p = from; p; p = p.parentElement) { if (getComputedStyle(p).webkitLineClamp !== 'none') return true; if (p === to) break } return false }
  for (const el of document.querySelectorAll(selector)) {
    if (!el.getBoundingClientRect().width) continue
    const texts = [], all = []
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    for (let n; (n = walker.nextNode());) {
      // (a text clamped to a number of lines on purpose - a calendar entry - is cut, not broken)
      if (!n.nodeValue.trim() || clamped(n.parentElement, el)) continue
      const range = document.createRange()
      range.selectNodeContents(n)
      const rects = [...range.getClientRects()]
      texts.push(linesOf(rects))
      all.push(...rects)
    }
    if (!texts.length) continue
    const inline = [...el.querySelectorAll('*')].every((c) => /^inline|^contents|^none/.test(getComputedStyle(c).display))
    const worst = Math.max(...texts), lines = inline ? linesOf(all) : worst
    if (worst > 1 || lines > 1) found.push('<' + el.tagName.toLowerCase() + ' class="' + (el.getAttribute('class') || '') + '"> "' + el.textContent.trim().replace(/\\s+/g, ' ').slice(0, 50) + '" - ' + lines + ' lines, ' + Math.round(el.getBoundingClientRect().height) + 'px high')
  }
  return found
}"""

# Every DataTable of the page: its rows and columns as boxes, what sticks out of its cells, where the two lines of an
# entity cell start, and the bounds its page gave each column (read from the component: they are not in the markup).
TABLES = """() => {
  const box = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height } }
  const comps = []
  const seen = new Set()
  const visit = (v) => {
    if (!v || typeof v !== 'object' || seen.has(v)) return
    seen.add(v)
    if (v.component) {
      if (v.component.type && v.component.type.__name === 'DataTable') comps.push(v.component)
      visit(v.component.subTree)
    }
    if (Array.isArray(v.children)) v.children.forEach(visit)
    if (v.suspense) visit(v.suspense.activeBranch)
  }
  visit(document.querySelector('#app')._vnode)
  return [...document.querySelectorAll('main .dt')].filter((dt) => dt.getBoundingClientRect().width).map((dt, n) => {
    const table = dt.querySelector('.dt-table'), scroll = dt.querySelector('.dt-scroll')
    const rows = [...table.querySelectorAll('tbody > tr.dt-row')]
    // what stands in a cell and reaches past it (the cell cuts it off: it is not seen whole). (The lab's test is
    // stricter - inside the cell's padding; a page may let a button's edge into the padding to line its words up.)
    const out = []
    for (const td of table.querySelectorAll('tbody > tr.dt-row > td')) {
      const cell = td.getBoundingClientRect(), inner = td.firstElementChild
      if (!inner) continue
      const room = { l: cell.left, r: cell.right, t: cell.top, b: cell.bottom }
      const walk = (el) => {
        const r = el.getBoundingClientRect()
        if (!r.width && !r.height) return
        if (r.left < room.l - 1 || r.right > room.r + 1 || r.top < room.t - 1 || r.bottom > room.b + 1) {
          out.push('<' + el.tagName.toLowerCase() + ' class="' + (el.getAttribute('class') || '') + '"> "' + el.textContent.trim().slice(0, 40) + '" by ' +
            [room.l - r.left, r.right - room.r, room.t - r.top, r.bottom - room.b].map((v) => Math.max(0, Math.round(v))).join('/') + 'px (left/right/top/bottom)')
          return
        }
        const s = getComputedStyle(el)
        if (s.overflowX !== 'visible' || s.overflowY !== 'visible' || el.tagName.toLowerCase() === 'svg') return
        for (const c of el.children) walk(c)
      }
      for (const c of inner.children) walk(c)
    }
    const comp = comps.find((c) => c.subTree && c.subTree.el === dt)
    const layout = comp && comp.exposed && comp.exposed.layout ? comp.exposed.layout.value : null
    const defs = comp ? comp.props.columns.map((c) => ({ id: c.id, width: c.width ?? null, min: c.min ?? null, max: c.max ?? null })) : null
    const heads = [...table.querySelectorAll('thead th')]
    const select = table.querySelector('thead th.dt-select') ? 1 : 0
    return {
      label: table.getAttribute('aria-label') || 'table ' + n,
      token: parseFloat(getComputedStyle(dt).getPropertyValue('--dt-row')),
      density: ['compact', 'comfortable'].find((c) => dt.classList.contains(c)) || 'standard',
      rows: rows.map((r) => box(r).h),
      heads: heads.map(box), headers: heads.map((th) => th.textContent.trim()),
      cells: rows.map((r) => [...r.children].map(box)),
      ids: layout ? (select ? [null] : []).concat(layout.visible) : null, defs, scrolls: !!(layout && layout.scroll),
      primary: rows.map((r) => r.querySelector('.entity .t-primary')).filter(Boolean).map((e) => box(e).l),
      secondary: rows.map((r) => r.querySelector('.entity .entity-2')).filter(Boolean).map((e) => box(e).l),
      dt: box(dt), scroll: { ...box(scroll), client: scroll.clientWidth, content: scroll.scrollWidth },
      out,
    }
  })
}"""


def table_faults(t: dict) -> list:
    """What is wrong with one DataTable of a page (an empty list when nothing is)."""
    where = t["label"]
    bad = []
    if t["token"] != ROW[t["density"]]:
        bad.append((where, "the row token is not the density's", t["density"], t["token"]))
    if any(abs(h - t["token"]) > PX for h in t["rows"]):
        bad.append((where, "rows of", sorted(set(round(h, 1) for h in t["rows"])), "- the density says", t["token"]))
    for r, cells in enumerate(t["cells"]):
        if len(cells) != len(t["heads"]):
            bad.append((where, "row", r, "has", len(cells), "cells under", len(t["heads"]), "headers"))
            continue
        for c, (cell, head) in enumerate(zip(cells, t["heads"])):
            if abs(cell["l"] - head["l"]) > PX or abs(cell["w"] - head["w"]) > PX:
                bad.append((where, "row", r, "column", t["headers"][c] or c, "is not under its header", round(cell["l"]), round(cell["w"]), round(head["l"]), round(head["w"])))
                break
    if t["out"]:
        bad.append((where, "content sticks out of its cell", t["out"][:5]))
    if t["dt"]["r"] > t["scroll"]["r"] + PX or t["scroll"]["w"] > t["dt"]["w"] + PX:
        bad.append((where, "the table is wider than its box", t["dt"], t["scroll"]))
    for what in ("primary", "secondary"):
        xs = t[what]
        if xs and max(xs) - min(xs) > PX:
            bad.append((where, f"the {what} lines of the entity cells start at different places", sorted(set(round(x, 1) for x in xs))))
    # the column widths stay within the bounds the page declared (tablelayout.js: a column grows past its maximum only
    # when every column that may grow has reached its own and the table must still fill its box)
    if t["ids"] and t["defs"]:
        defs = {d["id"]: d for d in t["defs"]}
        shown = [(defs[i], t["heads"][k]["w"]) for k, i in enumerate(t["ids"]) if i in defs]
        free = [(d, w) for d, w in shown if d["width"] is None]
        filling = all(d["max"] is not None and w >= d["max"] - PX for d, w in free)
        for d, w in shown:
            if d["width"] is not None:
                if not (free == [] or abs(w - d["width"]) <= PX):
                    bad.append((where, "column", d["id"], "is", w, "- declared width", d["width"]))
                continue
            low = d["min"] if d["min"] is not None else min(64, d["max"] or 64)
            if w < low - PX:
                bad.append((where, "column", d["id"], "is", w, "- narrower than its minimum", low))
            if d["max"] is not None and w > d["max"] + PX and not filling:
                bad.append((where, "column", d["id"], "is", w, "- wider than its maximum", d["max"], "while another column could still grow"))
    return bad


# Faults these tests found in a page and reported to the page's owner (frontend/src is not this file's to change). The
# walk lets exactly these through - (address, what was found, why it is here) - and
# test_the_known_faults_are_still_there fails on the day one is fixed: then its line is deleted, so it stays fixed.
KNOWN: list = []      # (none now: the analytics tables' two-line headers were the first entry, fixed since)


def known(path: str, item: str) -> bool:
    return any(re.search(where, path) and re.search(what, item) for where, what, _ in KNOWN)


def audit(page, path: str, *, one_line: bool, allow_known: bool = True) -> list:
    """Everything wrong with the page as it stands (but the KNOWN faults, unless asked for them too)."""
    found = page.evaluate(AUDIT, one_line)
    if one_line:
        found["broken"] = page.evaluate(WRAPPED, ONE_LINE)
    if allow_known:
        for k in ("titled", "nameless", "out", "broken"):
            found[k] = [x for x in found.get(k, []) if not known(path, x)]
    bad = []
    if found["heads"] != 1:
        bad.append(("the page has", found["heads"], "titles (.page-head h2): one is right"))
    for k, what in (("titled", "the browser's own tooltip (title=)"), ("nameless", "buttons or links without a name"), ("out", "reaches out of main"),
                    ("sideways", "scrolls sideways"), ("broken", "takes more than one line")):
        if found.get(k):
            bad.append((what, found[k][:5]))
    for t in page.evaluate(TABLES):
        bad += table_faults(t)
    return bad


# ── every page: the walk ─────────────────────────────────────────────────────────────────────────────────────────────
WALKS = [(1440, "en", "light"), (1280, "en", "light"), (1024, "en", "light"), (1440, "zh", "light"), (1280, "zh", "light"), (1024, "zh", "light"),
         (1440, "fr", "light"), (1440, "zh", "dark")]


@pytest.mark.parametrize("width,lang,theme", WALKS, ids=[f"{w}-{lang}-{theme}" for w, lang, theme in WALKS])
def test_every_page_has_one_title_no_browser_tooltip_named_buttons_and_stays_inside_the_window(site, width, lang, theme):
    """G, E, F on every route: one title; no `title` attribute; every button and link named; nothing past `main`; no
    sideways scroll; one-line labels one line; every DataTable's rows one height, its cells under its headers, nothing out
    of a cell, its columns within their declared bounds."""
    faults = {}
    for path in routes(site):
        page = site.go(path, width, lang, theme)
        bad = audit(page, path, one_line=True)
        if bad:
            faults[path] = bad
    assert not faults, "\n".join(f"{path}: {b}" for path, bad in faults.items() for b in bad)


def test_the_known_faults_are_still_there(site):
    """(When this fails, a fault in KNOWN was fixed: delete its line, so the walk keeps it fixed.)"""
    for where, what, why in KNOWN:
        hits = []
        for path in [r for r in routes(site) if re.search(where, r)]:
            page = site.go(path)
            found = page.evaluate(AUDIT, True)
            items = found["titled"] + found["nameless"] + found["out"] + page.evaluate(WRAPPED, ONE_LINE)
            hits += [x for x in items if re.search(what, x)]
        assert hits, f"fixed - delete its line from KNOWN in tests/test_ui_pages.py: {why}"


def test_the_theme_and_the_language_really_change(site):
    """(so that "passes in dark and in Chinese" is not the same page measured twice)"""
    looks = {}
    for lang, theme in (("en", "light"), ("zh", "dark")):
        page = site.go("/home", 1440, lang, theme)
        looks[(lang, theme)] = page.evaluate("() => [getComputedStyle(document.body).backgroundColor, document.querySelector('.page-head h2').textContent]")
    assert looks[("en", "light")][0] != looks[("zh", "dark")][0] and looks[("en", "light")][1] != looks[("zh", "dark")][1], looks


RING = """() => { const e = document.activeElement, s = getComputedStyle(e)
  return { what: e.tagName.toLowerCase() + '.' + (e.getAttribute('class') || '') + ' "' + (e.getAttribute('aria-label') || e.textContent.trim()).slice(0, 30) + '"',
           inMain: !!e.closest('main'), parts: ['date', 'time', 'datetime-local', 'month', 'week'].includes(e.type),
           seen: e.matches(':focus-visible'), style: s.outlineStyle, width: parseFloat(s.outlineWidth) || 0, shadow: s.boxShadow } }"""


def test_the_keyboards_place_is_visible_on_every_page(site):
    """G: the first stops of the Tab key in each page's `main` show a focus ring."""
    faults = []
    stops = 0
    for path in routes(site):
        page = site.go(path)
        if not page.evaluate("() => { const e = document.querySelector('main button, main a[href], main input, main select, main [tabindex=\"0\"]'); if (e) e.focus(); return !!e }"):
            continue
        page.keyboard.press("Shift+Tab")
        for _ in range(10):
            page.keyboard.press("Tab")
            ring = page.evaluate(RING)
            if not ring["inMain"]:
                break
            stops += 1
            if ring["parts"]:      # a date field: the browser marks the part the keyboard is on
                continue
            if not ring["seen"] or ((ring["style"] in ("none", "hidden") or ring["width"] < 2) and ring["shadow"] in ("none", "")):
                faults.append((path, ring))
    assert stops > 100, stops
    assert not faults, faults[:10]


# ── A. applications: the next event ─────────────────────────────────────────────────────────────────────────────────
NEXT_EVENT = """(company) => {
  const table = document.querySelector('main .dt-table')
  const heads = [...table.querySelectorAll('thead th')]
  const row = [...table.querySelectorAll('tbody > tr.dt-row')].find((r) => r.textContent.includes(company))
  const cell = row ? row.querySelector('.dtc') : null
  return {
    widths: heads.map((th) => th.getBoundingClientRect().width), rows: table.querySelectorAll('tbody > tr.dt-row').length,
    text: cell ? cell.textContent : null, primary: cell && cell.querySelector('.dtc-1') ? cell.querySelector('.dtc-1').textContent.trim() : '',
    secondary: cell && cell.querySelector('.dtc-2') ? cell.querySelector('.dtc-2').textContent.trim() : '',
  }
}"""


def absurd_item(site: Site) -> dict | None:
    from datetime import date, timedelta

    items = site.api(f"/api/calendar?start={date.today()}&end={date.today() + timedelta(days=30)}")["items"]
    return next((x for x in items if str(x.get("title") or "").startswith(ui_data.ABSURD_EVENT[:20])), None)


@pytest.mark.parametrize("width", list(SIZES))
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_an_absurd_next_event_does_not_move_a_column_and_the_cell_says_when_and_what(site, width, lang):
    path = "/applications?group=progress"
    page = site.go(path, width, lang)
    with_it = page.evaluate(NEXT_EVENT, ui_data.CJK_COMPANY)
    assert with_it["text"] is not None, "the application with the absurd next event is not in its group, or its cell is not a DateTimeCell"
    # the cell says when and what kind - not the company, the position or the item's title (those are in its tooltip)
    for what in (ui_data.CJK_COMPANY, ui_data.CJK_TITLE, ui_data.ABSURD_EVENT[:24]):
        assert what not in with_it["text"], (what, with_it["text"])
    assert re.search(r"\d{1,2}:\d{2}", with_it["primary"]), ("no time in the next event's cell", with_it)
    assert with_it["secondary"], ("no kind in the next event's cell", with_it)
    # the same table without it: every column as wide
    item = absurd_item(site)
    assert item, "the absurd calendar item is not on the calendar"
    tid = int(str(item.get("todo_id") or item.get("id")).split(":")[-1])
    site.api(f"/api/todos/{tid}/done", {"resume": False})
    try:
        without = site.go(path, width, lang).evaluate(NEXT_EVENT, ui_data.CJK_COMPANY)
    finally:
        start = str(item["start"])
        site.api("/api/calendar/items", {"title": ui_data.ABSURD_EVENT, "day": start[:10], "time": start[11:16], "application_id": site.app_id(ui_data.CJK_COMPANY, "interview")})
    assert without["rows"] == with_it["rows"] and ui_data.ABSURD_EVENT[:24] not in (without["text"] or "")
    assert len(without["widths"]) == len(with_it["widths"])
    assert all(abs(a - b) <= PX for a, b in zip(with_it["widths"], without["widths"])), ("columns moved", with_it["widths"], without["widths"])


# ── B. applications and postings: rows, lines, cut names ─────────────────────────────────────────────────────────────
LISTS = [f"/applications?group={g}" for g in ("me", "agent", "sent", "progress", "ended")] + ["/jobs", "/jobs?group=skip", "/jobs?group=closed"]


@pytest.mark.parametrize("width", list(SIZES))
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_application_and_posting_tables_keep_one_row_height_and_one_text_line(site, width, lang):
    faults = []
    seen = 0
    for path in LISTS:
        tables = site.go(path, width, lang).evaluate(TABLES)
        assert tables, (path, "shows no DataTable")
        for t in tables:
            seen += len(t["rows"])
            assert t["primary"], (path, "no entity cell (company and position) in the table")
            faults += [(path, *b) for b in table_faults(t)]
    assert seen > 40, seen
    assert not faults, faults


CUT = """(text) => { const el = [...document.querySelectorAll('main .dt-row .entity .t-primary, main .dt-row .entity .entity-2')].find((e) => e.textContent.trim() === text)
  if (!el) return null
  el.setAttribute('data-test-hover', '1'); return { cut: el.scrollWidth > el.clientWidth } }"""


@pytest.mark.parametrize("path", ["/applications?group=me", "/jobs"])
@pytest.mark.parametrize("width,lang", [(1440, "en"), (1024, "zh")])
def test_a_cut_name_shows_all_of_it_in_the_tooltip_and_a_short_one_shows_none(site, path, width, lang):
    page = site.go(path, width, lang)
    for text, cut in ((ui_data.LONG_COMPANY, True), (ui_data.LONG_TITLE, True), (ui_data.SHORT, False)):
        page.evaluate("() => document.querySelectorAll('[data-test-hover]').forEach((e) => e.removeAttribute('data-test-hover'))")
        found = page.evaluate(CUT, text)
        assert found, (path, "no row shows", text[:30])
        assert found["cut"] is cut, (path, text[:30], "cut" if found["cut"] else "not cut")
        hover(page, "[data-test-hover]")
        if cut:
            page.wait_for_selector(TIP)
            assert tip_text(page) == text, (path, tip_text(page))
        else:
            page.wait_for_timeout(600)      # (it would show after 350ms)
            assert not page.query_selector(TIP), (path, "a name that fits shows a tooltip:", tip_text(page))
        page.mouse.move(2, 2)
        page.wait_for_selector(TIP, state="detached")


# ── C. site accounts ─────────────────────────────────────────────────────────────────────────────────────────────────
ACC_ROWS = """() => [...document.querySelectorAll('main .dt-row')].map((r) => {
  const box = (e) => { const x = e.getBoundingClientRect(); return { l: x.left, t: x.top, w: x.width, h: x.height } }
  const acts = [...r.querySelectorAll('.cred .cred-acts button')], cred = r.querySelector('.cred')
  const buttons = [...r.querySelectorAll('button')].filter((b) => b.getBoundingClientRect().width > 0 && !b.closest('.cred'))
  return { text: r.innerText, h: box(r).h, last: acts.length ? box(acts[acts.length - 1]) : null, cred: cred ? box(cred) : null,
           credText: cred ? box(cred.querySelector('.cred-text')).l : null,
           buttons: buttons.map((b) => ({ name: (b.getAttribute('aria-label') || b.textContent).trim(), danger: b.classList.contains('danger') })) }
})"""


@pytest.mark.parametrize("width,lang,theme", [(1440, "en", "light"), (1280, "zh", "light"), (1024, "en", "light"), (1024, "fr", "light"), (1440, "zh", "dark")])
def test_site_account_rows_are_one_height_and_the_password_button_stands_in_one_place(site, width, lang, theme):
    page = site.go("/accounts", width, lang, theme)
    rows = page.evaluate(ACC_ROWS)
    assert len(rows) >= len(ui_data.ACCOUNTS), len(rows)
    assert max(r["h"] for r in rows) - min(r["h"] for r in rows) <= PX, [r["h"] for r in rows]
    if not any(r["cred"] for r in rows):      # a narrow window gave the column up (it is optional; the details show it)
        assert len([t for t in page.evaluate(TABLES) if t["ids"] and "cred" not in t["ids"]]) == 1, "no credential cell, and no column given up"
        rows = []
    assert all(r["cred"] for r in rows), "some rows have a credential cell and some have none"
    for what, at in (("text", [r["credText"] for r in rows]), ("button", [r["last"]["l"] for r in rows]), ("button's top in its row", [r["last"]["t"] - r["cred"]["t"] for r in rows])):
        assert not at or max(at) - min(at) <= PX, (f"the credential cell's {what} moves from row to row", at)
    for r in page.evaluate(ACC_ROWS):
        # the long technical error is behind the state's tooltip and in the details - never in the row
        assert ui_data.ERROR_MARK not in r["text"] and "TimeoutError" not in r["text"], r["text"]
        # what destroys something is in the row's menu, not a button of the row
        assert not any(b["danger"] for b in r["buttons"]), r["buttons"]
        assert len(r["buttons"]) <= 2, ("more than the sign-in button and the menu in a row", r["buttons"])


def test_the_row_menu_holds_the_destructive_actions(site):
    page = site.go("/accounts")
    row = page.locator("main .dt-row", has_text="zq-ready")
    row.locator(".menu > button").click()
    page.wait_for_selector(".menu-pop")
    frames(page)
    assert page.locator(".menu-pop .menu-item.danger").count() >= 1, page.inner_text(".menu-pop")
    assert page.evaluate(INSIDE, ".menu-pop")["ok"]
    page.keyboard.press("Escape")
    page.wait_for_selector(".menu-pop", state="detached")


PASSWORD_ANYWHERE = """(pw) => {
  const hits = []
  for (const el of document.querySelectorAll('*')) for (const a of el.attributes) if (a.value.includes(pw)) hits.push(el.tagName + '[' + a.name + ']')
  const tip = document.querySelector('#aa-tip')
  if (tip && tip.textContent.includes(pw)) hits.push('#aa-tip')
  try { for (const k of Object.keys(localStorage)) if (String(localStorage.getItem(k)).includes(pw)) hits.push('localStorage.' + k) } catch (e) {}
  return hits
}"""
EYE = """() => { const r = [...document.querySelectorAll('main .dt-row')].find((x) => x.textContent.includes('zq-ready')), b = [...r.querySelectorAll('.cred-acts button')].pop()
  return { name: b.getAttribute('aria-label'), glyph: b.querySelector('svg path').getAttribute('d'), value: r.querySelector('.cred-value') ? r.querySelector('.cred-value').textContent : null } }"""


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_reveal_shows_the_password_turns_the_eye_and_puts_it_in_no_name_or_tooltip(site, lang):
    page = site.go("/accounts", 1440, lang)
    before = page.evaluate(EYE)
    assert before["value"] is None
    page.locator("main .dt-row", has_text="zq-ready").locator(".cred-acts button").last.click()
    page.wait_for_selector('.dialog[role="alertdialog"]')      # it asks first
    page.locator(".dialog .dialog-acts button.primary").click()
    page.wait_for_selector("main .dt-row .cred-value")
    frames(page)
    after = page.evaluate(EYE)
    assert after["value"] == ui_data.PASSWORD
    assert after["name"] != before["name"] and after["glyph"] != before["glyph"], ("the eye did not turn into the crossed eye", before, after)
    hover(page, "main .dt-row .cred-value")
    page.wait_for_timeout(500)
    assert not page.evaluate(PASSWORD_ANYWHERE, ui_data.PASSWORD), page.evaluate(PASSWORD_ANYWHERE, ui_data.PASSWORD)
    # hidden again
    page.locator("main .dt-row", has_text="zq-ready").locator(".cred-acts button").last.click()
    page.wait_for_selector("main .dt-row .cred-value", state="detached")


# ── D. identity-provider cards ───────────────────────────────────────────────────────────────────────────────────────
CARDS = """() => [...document.querySelectorAll('main .pgrid')].map((g) => {
  const box = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height } }
  return { box: box(g), cards: [...g.querySelectorAll('.pcard')].map((c) => ({ ...box(c), foot: c.querySelector('.pcard-foot') ? box(c.querySelector('.pcard-foot')) : null,
    main: c.querySelector('.pcard-foot .pcard-main') ? box(c.querySelector('.pcard-foot .pcard-main')) : null })) }
})"""


@pytest.mark.parametrize("width,lang,theme", [(1440, "en", "light"), (1280, "zh", "light"), (1024, "en", "light"), (1440, "fr", "light"), (1024, "zh", "dark")])
def test_provider_cards_of_one_row_line_up_and_no_button_wraps(site, width, lang, theme):
    page = site.go("/accounts", width, lang, theme)
    grids = page.evaluate(CARDS)
    assert grids and any(len(g["cards"]) >= 2 for g in grids), grids
    beside = 0
    for g in grids:
        rows: dict = {}
        for card in g["cards"]:
            assert card["l"] >= g["box"]["l"] - PX and card["r"] <= g["box"]["r"] + PX, ("a card reaches out of its grid", card, g["box"])
            rows.setdefault(round(card["t"]), []).append(card)
        for cards in rows.values():
            beside = max(beside, len(cards))
            assert max(c["h"] for c in cards) - min(c["h"] for c in cards) <= PX, ("cards of one row differ in height", [c["h"] for c in cards])
            feet = [c["foot"] for c in cards]
            assert all(feet) and max(f["b"] for f in feet) - min(f["b"] for f in feet) <= PX, ("the feet of one row do not end on one line", feet)
            mains = [c["main"] for c in cards]
            assert all(mains), "a card without its main button (.pcard-main)"
            for k in ("t", "w", "h"):
                assert max(m[k] for m in mains) - min(m[k] for m in mains) <= PX, (f"the main buttons of one row differ ({k})", [m[k] for m in mains])
    assert beside >= 2
    broken = page.evaluate(WRAPPED, "main .pcard button, main .pcard .tag")
    assert not broken, broken


# ── E. the shared tooltip on a page ──────────────────────────────────────────────────────────────────────────────────
def test_an_icon_button_shows_its_tooltip_on_hover_and_on_keyboard_focus(site):
    page = site.go("/accounts")
    eye = page.locator("main .dt-row", has_text="zq-ready").locator(".cred-acts button").last
    name = eye.get_attribute("aria-label")
    assert name and not eye.get_attribute("title")
    hover(page, eye)
    page.wait_for_selector(TIP)
    assert tip_text(page) == name
    page.mouse.move(2, 2)
    page.wait_for_selector(TIP, state="detached")
    eye.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    page.wait_for_selector(TIP, timeout=1000)
    assert tip_text(page) == name and page.evaluate("() => document.activeElement.getAttribute('aria-label')") == name


@pytest.mark.parametrize("width", [1440, 1024])
def test_a_tooltip_in_a_table_at_the_right_edge_stays_inside_the_window(site, width):
    page = site.go("/applications?group=me", width)
    more = page.locator("main .dt-row .menu > button").first      # the row menu, in the last column
    box = more.bounding_box()
    assert box and box["x"] + box["width"] > width - 120, ("the row menu is not near the right edge", box)
    hover(page, more)
    page.wait_for_selector(TIP)
    page.wait_for_timeout(50)      # (placed after it was measured)
    where = page.evaluate(INSIDE, "#aa-tip")
    assert where["ok"], where


# ── F. analytics, settings and about: structure by content, semantic controls ────────────────────────────────────────
# Cards side by side in one row: how much of each is empty below what it holds (its last child's bottom, plus the card's
# padding), as a share of its height. Two cards share a row only when they hold about as much (views/analytics/layout.js).
ROW_EMPTY = """() => {
  const out = []
  for (const row of document.querySelectorAll('main .an-row')) {
    const cards = [...row.children].filter((c) => c.getBoundingClientRect().height > 0)
    if (cards.length < 2 || new Set(cards.map((c) => Math.round(c.getBoundingClientRect().top))).size > 1) continue
    for (const c of cards) {
      const r = c.getBoundingClientRect()
      let bottom = r.top
      for (const k of c.querySelectorAll('*')) { const b = k.getBoundingClientRect(); if (b.height && b.bottom > bottom) bottom = b.bottom }
      const pad = parseFloat(getComputedStyle(c).paddingBottom) || 0
      out.push({ row: row.className, card: (c.querySelector('h3, .card-title, .card-head') || c).textContent.trim().slice(0, 40), empty: (r.bottom - bottom - pad) / r.height })
    }
  }
  return out
}"""


@pytest.mark.parametrize("width", [1440, 1280, 1024])
@pytest.mark.parametrize("lang", ["en", "zh"])
def test_no_card_beside_a_taller_one_is_left_mostly_empty(site, width, lang):
    bad = []
    for path in ("/analytics?view=apps", "/analytics?view=auto", "/analytics?view=sites", "/analytics?view=ai"):
        page = site.go(path, width, lang)
        bad += [(path, c) for c in page.evaluate(ROW_EMPTY) if c["empty"] > 0.4]
    assert not bad, bad


def test_the_time_zone_is_chosen_from_a_list_searched_by_city_with_the_programs_own_offsets(site):
    page = site.go("/settings/notify/reminders")
    trigger = page.locator("main #time-zone")
    assert trigger.get_attribute("aria-haspopup") == "listbox" and not page.locator("main input#time-zone").count()      # not a field to type a zone into
    trigger.focus()
    page.keyboard.press("Enter")
    search = page.locator("[role=combobox][aria-expanded=true]")
    search.wait_for()
    assert page.evaluate("() => document.activeElement.getAttribute('role')") == "combobox"
    page.keyboard.type("Vancouver")
    first = page.locator("[role=listbox] [role=option]").first
    first.wait_for()
    # British Columbia is UTC-7 all year since 2026: the offset is the server's (its own tzdata), never the browser's
    assert "America/Vancouver" in first.inner_text() and "UTC−07:00" in first.inner_text(), first.inner_text()
    active = page.evaluate("() => document.getElementById(document.activeElement.getAttribute('aria-activedescendant')).textContent")
    assert "America/Vancouver" in active
    page.keyboard.press("Escape")      # closes without a change
    search.wait_for(state="detached")
    assert "Vancouver" not in trigger.inner_text() and page.evaluate("() => document.activeElement.id") == "time-zone"
    trigger.focus()
    page.keyboard.press("Enter")
    page.keyboard.type("+05:30")
    page.locator("[role=listbox] [role=option]", has_text="Asia/Kolkata").first.wait_for()      # by offset, a half hour too
    page.keyboard.press("Escape")


def test_the_reminders_of_a_kind_are_chips_never_a_list_of_minutes_to_type(site):
    page = site.go("/settings/notify/reminders")
    sec = page.locator("main #set-reminders")
    sec.wait_for()
    assert not sec.locator("input:not([type=time]):not([type=checkbox])").count(), "a field to type minutes into"
    chips = sec.locator(".fchip.lg")
    assert chips.count() >= 3
    heights = {round(b["height"]) for b in (chips.nth(i).bounding_box() for i in range(chips.count()))}
    assert len(heights) == 1, heights
    for i in range(chips.count()):      # each × says which reminder it removes, in the words the chip shows
        said, name = chips.nth(i).locator(".rr-text").inner_text().strip(), chips.nth(i).locator("button").get_attribute("aria-label") or ""
        assert said and said in name and len(name) > len(said), (said, name)


# Cards of a page that stand side by side (their tops at one height): the overview of About has none - one column.
SIDE_BY_SIDE = """() => { const cards = [...document.querySelectorAll('main .card')].filter((c) => c.getBoundingClientRect().height > 0)
  const tops = cards.map((c) => Math.round(c.getBoundingClientRect().top)); return tops.length - new Set(tops).size }"""
OPEN_ROWS = "() => [...document.querySelectorAll('main .cl-row[aria-expanded=true]')].map((b) => b.closest('[id]').id)"


@pytest.mark.parametrize("width", [1440, 1024])
def test_the_about_overview_is_one_column_with_one_update_section_and_advanced_folded(site, width):
    page = site.go("/about", width, reload=True)
    assert page.locator("main .up-sec").count() == 1 and page.evaluate(SIDE_BY_SIDE) == 0
    adv = page.locator("main .up-adv-toggle")
    assert adv.get_attribute("aria-expanded") == "false" and not page.locator("main #up-adv-body").is_visible()
    adv.click()
    assert adv.get_attribute("aria-expanded") == "true" and page.locator("main #up-adv-body").is_visible()
    # a copy run from source is updated by hand: the overview offers no button that pretends to update it
    labels = [b.inner_text().strip() for b in page.locator("main .up-sec button").all()]
    assert not any(w in " ".join(labels).lower() for w in ("switch to", "download and prepare", "install")), labels
    site.go("/about/changelog", width)
    page = site.go("/about", width)
    assert page.locator("main .up-adv-toggle").get_attribute("aria-expanded") == "false"      # (folded again: a design, not a memory)


def test_the_changelog_opens_folded_one_release_at_a_time_and_keeps_the_full_notes(site):
    data = site.api("/api/about/changelog")
    released = [v for v in data["versions"] if not v["unreleased"]]
    page = site.go("/about")
    tab = page.locator("main [role=tab][data-tab=overview]")
    tab.focus()
    page.keyboard.press("ArrowRight")
    page.wait_for_url("**/about/changelog")
    settle(page, "en")
    assert page.evaluate("() => document.activeElement.dataset.tab") == "changelog"      # the keyboard stays on the tab
    rows = page.locator("main .cl-ver .cl-row")
    assert rows.count() == len(released) and page.locator("main .cl-node").count() == len(released)
    assert page.locator("main .cl-un").count() == (1 if any(v["unreleased"] for v in data["versions"]) else 0)
    # first open: everything folded - the newest and the running version too; no body text, no list of versions beside
    assert page.evaluate(OPEN_ROWS) == [] and page.locator("main .cl-panel").count() == 0
    line = page.locator("main .cl-line").bounding_box()
    main = page.locator("main.content").bounding_box()
    assert line["width"] > 0.8 * (main["width"] - 64), (line, main)
    # one at a time: opening another closes the first; the open one is in the address
    rows.nth(1).click()
    page.wait_for_url("**v=" + released[1]["version"])
    assert len(page.evaluate(OPEN_ROWS)) == 1 and page.locator("main .cl-panel").count() == 1
    rows.nth(0).click()
    page.wait_for_url("**v=" + released[0]["version"])
    opened = page.evaluate(OPEN_ROWS)
    assert len(opened) == 1 and page.locator("main .cl-ver.open .cl-num").inner_text().strip().endswith(released[0]["version"])
    panel = page.locator("main .cl-panel")
    assert 3 <= panel.locator(".cl-hl > li").count() <= 6      # the curated highlights, not the notes
    rows.nth(0).click()
    page.wait_for_function("() => !location.search.includes('v=')")
    assert page.evaluate(OPEN_ROWS) == []
    # a search opens nothing
    page.locator("main input.search").fill("calendar")
    page.wait_for_timeout(300)
    assert page.evaluate(OPEN_ROWS) == [] and page.locator("main .cl-ver").count() >= 1
    page.locator("main input.search").fill("")
    # a link to a release opens it, and only it; its full notes are all there, as written
    oldest = released[-1]
    page = site.go("/about/changelog?v=" + oldest["version"], reload=True)
    page.wait_for_function("() => document.querySelectorAll('main .cl-row[aria-expanded=true]').length === 1")
    page.locator("main .cl-panel button[aria-haspopup=dialog]").click()
    drawer = page.locator(".drawer, [role=dialog]").last
    drawer.wait_for()
    first_item = oldest["sections"][0]["items"][0]
    words = first_item.split("\n")[0].replace("**", "").replace("*", "")[:40]
    assert words in drawer.inner_text(), words
    page.keyboard.press("Escape")
    site.go("/about")      # (the next test starts where a person would)
