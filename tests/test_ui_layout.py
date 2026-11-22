"""What the shared components draw, measured in a browser on the UI lab (/ui-lab): the layout rules of
docs/component-guidelines.md as numbers - every row of a table one height, a column as wide whatever stands in it, a
control of one level one height, text cut and never broken, a tooltip inside the window, the keyboard through a menu.

The lab holds every shared component in its states with made-up data, so these checks need no page of the program and
no data. Nothing here knows how wide a text is: fonts differ between computers, so the checks compare boxes with each
other and with the tokens, to within a pixel. How it is run, and what it does not see: docs/ui-quality-assurance.md.
"""

from __future__ import annotations

import pytest

import ui_server

PX = 1.0      # boxes that should be equal may differ by this much (sub-pixel rounding, a zoomed screen)
ROW = {"compact": 40, "standard": 56, "comfortable": 64}      # --row-* in src/style.css
# the lab's optional columns, in the order they are given up when the box gets narrower (highest `priority` first)
GIVEN_UP = ["Score", "Contact", "Where it was found", "Applied"]
KEPT = ["Company / role", "Status"]


# ── the lab in a browser ─────────────────────────────────────────────────────────────────────────────────────────────
class Lab:
    """Pages of the lab. A page that is only measured is opened once per size, theme and language and shared; a test
    that presses or hovers gets a page of its own (`own=True`), closed when the test ends."""

    def __init__(self) -> None:
        self.contexts: dict = {}
        self.shared: dict = {}
        self.own: list = []

    def open(self, *, width: int = 1440, height: int = 900, theme: str = "light", lang: str = "en", only: str = "", narrow: int = 0, motion: bool = False, own: bool = False):
        key = (width, height, theme, lang, motion)
        if key not in self.contexts:
            self.contexts[key] = ui_server.context(width=width, height=height, theme=theme, lang=lang, reduced_motion=not motion)
        if not own and (key, only, narrow) in self.shared:
            return self.shared[(key, only, narrow)]
        page = self.contexts[key].new_page()
        page.set_default_timeout(10_000)      # everything is on this computer: what has not come by then will not
        query = "&".join(q for q in (f"only={only}" if only else "", f"narrow={narrow}" if narrow else "") if q)
        page.goto("/ui-lab" + ("?" + query if query else ""), wait_until="networkidle")      # (the words of the language arrive after the first draw)
        page.wait_for_selector("[data-lab]")
        page.wait_for_function("(lang) => document.documentElement.lang.toLowerCase().startsWith(lang) && document.fonts.status === 'loaded'"
                               " && [...document.querySelectorAll('.dt-table')].every((t) => t.getBoundingClientRect().width > 0)", arg=lang)
        frames(page)      # a table measures its box, then draws its columns
        if own:
            self.own.append(page)
        else:
            self.shared[(key, only, narrow)] = page
        return page

    def close_own(self) -> None:
        for page in self.own:
            page.close()
        self.own.clear()

    def close(self) -> None:
        self.close_own()
        for ctx in self.contexts.values():
            ctx.close()


@pytest.fixture(scope="module")
def the_lab():
    ui_server.server()
    ui_server.browser()
    lab = Lab()
    yield lab
    lab.close()


@pytest.fixture
def lab(the_lab):
    yield the_lab
    the_lab.close_own()


def sections(page) -> list[str]:
    return page.evaluate("() => [...document.querySelectorAll('[data-lab]')].map((s) => s.dataset.lab)")


def frames(page) -> None:
    """Two frames on. These pages run with prefers-reduced-motion, where every change of a style is a transition of a
    hundredth of a millisecond (the rule in style.css): what was just changed has its new value one frame later, not
    in the frame it was changed in."""
    page.evaluate("() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")


LOOKS = [("light", "en"), ("dark", "en"), ("light", "zh"), ("dark", "zh")]
WIDTHS = [1440, 1024, 640]


# ── DataTable ────────────────────────────────────────────────────────────────────────────────────────────────────────
# Every DataTable of the lab (they stand in boxes marked data-dt; the accounts table in its own), as boxes and numbers.
TABLES = """() => [...document.querySelectorAll('[data-dt], [data-lab-acc="table"]')].filter((b) => b.querySelector('.dt')).map((b) => {
  const box = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height } }
  const dt = b.querySelector('.dt'), scroll = dt.querySelector('.dt-scroll'), table = dt.querySelector('.dt-table')
  const rows = [...table.querySelectorAll('tbody > tr.dt-row')]
  // What stands in a cell and reaches out of it. A cell's own box (.dt-cell) has the cell's size and holds the
  // padding; whatever is in it has to end inside that padding, or cut itself (then what it holds is its business).
  const out = []
  for (const td of table.querySelectorAll('tbody > tr.dt-row > td')) {
    const cell = td.getBoundingClientRect(), inner = td.firstElementChild
    if (!inner) continue
    const ir = inner.getBoundingClientRect(), cs = getComputedStyle(inner)
    const room = { l: ir.left + parseFloat(cs.paddingLeft), r: ir.right - parseFloat(cs.paddingRight), t: ir.top, b: ir.bottom }
    if (ir.left < cell.left - 1 || ir.right > cell.right + 1 || ir.top < cell.top - 1 || ir.bottom > cell.bottom + 1) out.push('the cell box itself: ' + td.textContent.trim().slice(0, 40))
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
  return {
    name: b.dataset.dt || 'accounts',
    density: ['compact', 'comfortable'].find((c) => dt.classList.contains(c)) || 'standard',
    token: parseFloat(getComputedStyle(dt).getPropertyValue('--dt-row')),
    rows: rows.map((r) => box(r).h),
    cols: [...table.querySelectorAll('colgroup > col')].map((c) => box(c).w),
    heads: [...table.querySelectorAll('thead th')].map(box),
    headers: [...table.querySelectorAll('thead th')].map((th) => th.textContent.trim()),
    cells: rows.map((r) => [...r.children].map(box)),
    box: box(b), dt: box(dt), table: box(table),
    scroll: { ...box(scroll), client: scroll.clientWidth, content: scroll.scrollWidth, sideways: scroll.classList.contains('x') },
    out,
  }
})"""

# The page and everything the lab stands in: nothing is wider than its place (so nothing scrolls sideways).
SIDEWAYS = """() => {
  const wide = []
  for (let el = document.querySelector('.lab'); el; el = el.parentElement) {
    if (el.scrollWidth > el.clientWidth + 1) wide.push(el.tagName.toLowerCase() + '.' + (el.getAttribute('class') || '') + ': ' + el.scrollWidth + ' in ' + el.clientWidth)
  }
  // and what makes it so: the elements that end past the right edge of the window, outermost first
  const vw = document.documentElement.clientWidth, past = []
  if (wide.length) {
    for (const el of document.querySelectorAll('.lab *')) {
      if (past.some((p) => p.contains(el))) continue
      const r = el.getBoundingClientRect()
      if (r.width && r.right > vw + 1 && !el.closest('.dt-scroll, .lab-trunc')) past.push(el)
    }
  }
  return { wide, past: past.slice(0, 8).map((el) => (el.closest('[data-lab]') || {}).dataset?.lab + ': <' + el.tagName.toLowerCase() + ' class="' + (el.getAttribute('class') || '') + '"> ends at ' + Math.round(el.getBoundingClientRect().right)) }
}"""


def check_tables(page) -> None:
    tables = page.evaluate(TABLES)
    by_name = {t["name"]: t for t in tables}
    assert {"short", "absurd", "density-compact", "density-standard", "density-comfortable", "box-420"} <= set(by_name), sorted(by_name)
    for t in tables:
        where = f"table '{t['name']}'"
        # every row is as high as the density says, whatever stands in it
        assert t["token"] == ROW[t["density"]], (where, t["density"], t["token"])
        assert all(abs(h - t["token"]) <= PX for h in t["rows"]), (where, "rows of", sorted(set(t["rows"])), "- the density says", t["token"])
        # the header and the body share their columns
        for r, cells in enumerate(t["cells"]):
            assert len(cells) == len(t["heads"]), (where, "row", r)
            for c, (cell, head) in enumerate(zip(cells, t["heads"])):
                assert abs(cell["l"] - head["l"]) <= PX and abs(cell["w"] - head["w"]) <= PX, (where, "row", r, "column", t["headers"][c] or c, cell, head)
        for c, head in enumerate(t["heads"]):
            assert abs(head["w"] - t["cols"][c]) <= PX, (where, "the column", t["headers"][c] or c, "is not as wide as it was told to be", head["w"], t["cols"][c])
        # the table never reaches out of the place it was put in; it fills that place, or scrolls inside its own box
        assert t["dt"]["l"] >= t["box"]["l"] - PX and t["dt"]["r"] <= t["box"]["r"] + PX, (where, "is wider than its place", t["dt"], t["box"])
        assert t["scroll"]["w"] <= t["dt"]["w"] + PX, (where, t["scroll"], t["dt"])
        if t["scroll"]["sideways"]:
            assert t["scroll"]["content"] > t["scroll"]["client"], (where, "says it scrolls sideways and has nothing to scroll")
        else:
            assert abs(t["table"]["w"] - t["scroll"]["client"]) <= PX, (where, "neither fills its box nor scrolls in it", t["table"]["w"], t["scroll"]["client"])
        # nothing in a cell reaches out of it
        assert not t["out"], (where, "content sticks out of its cell", t["out"][:6])
    # the same columns with short and with absurd values: exactly as wide
    assert len(by_name["short"]["cols"]) == len(by_name["absurd"]["cols"])
    assert all(abs(a - b) <= PX for a, b in zip(by_name["short"]["cols"], by_name["absurd"]["cols"])), (by_name["short"]["cols"], by_name["absurd"]["cols"])
    assert by_name["short"]["rows"] and len(by_name["short"]["rows"]) == len(by_name["absurd"]["rows"])
    # in narrower boxes the optional columns go, the one that matters least first; what has no priority stays
    hidden_before = -1
    for name in ("box-1200", "box-900", "box-640", "box-420"):
        t = by_name[name]
        assert all(k in t["headers"] for k in KEPT), (name, t["headers"])
        hidden = [h for h in GIVEN_UP if h not in t["headers"]]
        assert hidden == GIVEN_UP[:len(hidden)], (name, "gave up", hidden, "- the order is", GIVEN_UP)
        assert len(hidden) >= hidden_before, (name, "shows more columns than a wider box")
        hidden_before = len(hidden)
        if t["scroll"]["sideways"]:      # it scrolls only once there is nothing left to give up
            assert hidden == GIVEN_UP, (name, "scrolls sideways while optional columns are still shown", t["headers"])


def check_no_sideways_scroll(page) -> None:
    found = page.evaluate(SIDEWAYS)
    assert not found["wide"], ("the page is wider than the window", found)


@pytest.mark.parametrize("theme,lang", LOOKS)
def test_tables_keep_their_rows_and_columns_in_both_themes_and_languages(lab, theme, lang):
    page = lab.open(theme=theme, lang=lang)
    assert page.evaluate("() => [document.documentElement.dataset.theme, document.documentElement.lang.slice(0, 2)]") == [theme, lang]
    check_tables(page)
    check_no_sideways_scroll(page)


@pytest.mark.parametrize("width", WIDTHS)
def test_tables_stay_in_their_place_and_the_page_never_scrolls_sideways(lab, width):
    page = lab.open(width=width)
    check_tables(page)
    check_no_sideways_scroll(page)


def test_a_table_in_a_narrow_box_gives_up_every_optional_column_before_it_scrolls(lab):
    tables = {t["name"]: t for t in lab.open().evaluate(TABLES)}
    assert set(GIVEN_UP) <= set(tables["box-1200"]["headers"]), tables["box-1200"]["headers"]
    assert not any(h in tables["box-420"]["headers"] for h in GIVEN_UP), tables["box-420"]["headers"]
    assert len(tables["box-900"]["headers"]) < len(tables["box-1200"]["headers"]) and len(tables["box-640"]["headers"]) < len(tables["box-900"]["headers"])
    assert tables["box-420"]["scroll"]["sideways"] and tables["box-420"]["dt"]["w"] <= 420 + PX      # 40 + 220 + 150 + 52 do not fit 420: inside its box
    assert not tables["box-640"]["scroll"]["sideways"]


def test_the_page_made_narrow_keeps_every_table_inside_it(lab):
    page = lab.open(narrow=480, only="DataTable,Cells")
    check_no_sideways_scroll(page)
    for t in page.evaluate(TABLES):
        assert t["dt"]["w"] <= 480 + PX, t["name"]
        assert all(abs(h - t["token"]) <= PX for h in t["rows"]), t["name"]
        assert not t["out"], (t["name"], t["out"][:6])


def test_a_theme_is_really_another_theme(lab):
    """(so that "passes in both themes" is not the same page measured twice)"""
    seen = {theme: lab.open(theme=theme).evaluate("() => getComputedStyle(document.body).backgroundColor") for theme in ("light", "dark")}
    assert seen["light"] != seen["dark"], seen


# ── text ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
TIP = "#aa-tip.on"      # the program's one tooltip, while it shows (src/tip.js, components/TipLayer.vue)

# Every piece of cut text in the lab's Trunc grid: is it cut, and does it stay in its box.
TRUNCS = """() => [...document.querySelectorAll('[data-trunc="one"] .lab-box')].map((b, i) => {
  const el = b.querySelector('.cut'), r = el.getBoundingClientRect(), br = b.getBoundingClientRect()
  return { i, text: el.textContent.trim(), cut: el.scrollWidth > el.clientWidth, inside: r.left >= br.left - 1 && r.right <= br.right + 1, box: br.width }
})"""

# How many lines of text an element holds: text boxes whose middle lies under the line before start a new line.
LINES = """(selector) => {
  const found = []
  for (const el of document.querySelectorAll(selector)) {
    const rects = []
    const texts = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    for (let n; (n = texts.nextNode());) {
      if (!n.nodeValue.trim()) continue
      const range = document.createRange()
      range.selectNodeContents(n)
      rects.push(...range.getClientRects())
    }
    const boxes = rects.filter((r) => r.width > 0 && r.height > 0).sort((a, b) => a.top - b.top)
    if (!boxes.length) continue
    let lines = 0, bottom = -Infinity
    for (const r of boxes) { if (r.top + r.height / 2 > bottom) lines++; bottom = Math.max(bottom, r.bottom) }
    const s = getComputedStyle(el)
    const line = parseFloat(s.lineHeight) || parseFloat(s.fontSize) * 1.5
    const h = el.getBoundingClientRect().height
    if (lines > 1 || h >= 2 * line) {
      found.push((el.closest('[data-lab]') || {}).dataset?.lab + ': <' + el.tagName.toLowerCase() + ' class="' + (el.getAttribute('class') || '') + '"> "' + el.textContent.trim().slice(0, 50) + '" - ' + lines + ' lines, ' + Math.round(h) + 'px high')
    }
  }
  return found
}"""
# What never breaks: a button, a badge, a short label, a date, a state, a plain attribute, and text that is cut to one line.
ONE_LINE = ", ".join(".lab " + s for s in ("button", ".btn", ".tag", ".badge", ".atomic", ".status-label", ".meta", ".dtc-1", ".dtc-2", ".cut", ".seg-link", ".dt-sort"))


def hover(page, target) -> None:
    """Rest the pointer on something. It is brought into view first and the page left to settle: a scroll under the
    pointer takes a tooltip that is about to show away (src/tip.js) - a person's wheel does that, and so would the
    scroll a test makes to reach its target."""
    it = page.locator(target) if isinstance(target, str) else target
    it.scroll_into_view_if_needed()
    page.wait_for_timeout(120)
    it.hover()


def tip_text(page) -> str:
    return page.evaluate("() => { const t = document.querySelector('#aa-tip.on'); return t ? t.textContent : '' }")


def no_tip_after_hovering(page, selector: str) -> None:
    hover(page, selector)
    page.wait_for_timeout(600)      # (it would show after 350ms)
    assert not page.query_selector(TIP), (selector, "shows a tooltip:", tip_text(page))


def test_text_that_is_cut_says_all_of_it_in_the_tooltip_and_text_that_fits_has_none(lab):
    page = lab.open(only="Text,Tooltip", own=True)
    truncs = page.evaluate(TRUNCS)
    assert len(truncs) == 15 and all(t["inside"] for t in truncs), [t for t in truncs if not t["inside"]]
    cut = [t for t in truncs if t["cut"]]
    whole = [t for t in truncs if not t["cut"]]
    assert cut and whole, "the lab is meant to show both"      # (which ones fit depends on the font: nothing is asserted about that)
    boxes = page.locator('[data-trunc="one"] .lab-box .cut')
    # a cut one: hover - the whole text, in the program's tooltip, and the element is described by it
    one = cut[0]
    hover(page, boxes.nth(one["i"]))
    page.wait_for_selector(TIP)
    assert tip_text(page) == one["text"]
    assert boxes.nth(one["i"]).get_attribute("aria-describedby") == "aa-tip"
    assert page.evaluate("() => document.querySelector('#aa-tip').getAttribute('role')") == "tooltip"
    page.mouse.move(2, 2)
    page.wait_for_selector(TIP, state="detached")
    # one that fits: nothing
    hover(page, boxes.nth(whole[0]["i"]))
    page.wait_for_timeout(600)
    assert not page.query_selector(TIP), (whole[0], tip_text(page))
    page.mouse.move(2, 2)
    # the same on the tooltip's own samples: cut text (its own, a given one, two lines), and two that fit
    for name in ("cut", "cut2"):
        el = page.locator(f'[data-t="{name}"]')
        assert el.evaluate("(e) => e.scrollWidth > e.clientWidth || e.scrollHeight > e.clientHeight"), name
        hover(page, el)
        page.wait_for_selector(TIP)
        assert tip_text(page) == el.evaluate("(e) => e.textContent.replace(/\\s+/g, ' ').trim()"), name
        page.mouse.move(2, 2)
        page.wait_for_selector(TIP, state="detached")
    for name in ("fits", "trunc-fits"):
        assert page.locator(f'[data-t="{name}"]').evaluate("(e) => e.scrollWidth <= e.clientWidth"), name
        no_tip_after_hovering(page, f'[data-t="{name}"]')
    # given room, the text that was cut has no tooltip any more
    page.click('[data-t="wider"]')
    if page.locator('[data-t="cut"]').evaluate("(e) => e.scrollWidth <= e.clientWidth"):
        no_tip_after_hovering(page, '[data-t="cut"]')


def test_nothing_in_the_lab_uses_the_browsers_own_tooltip(lab):
    page = lab.open()
    titled = page.evaluate("() => [...document.querySelectorAll('.lab [title]')].filter((e) => e.tagName !== 'IFRAME').map((e) => (e.closest('[data-lab]') || {}).dataset?.lab + ': ' + e.outerHTML.slice(0, 120))")
    assert not titled, titled


@pytest.mark.parametrize("lang,narrow", [("en", 0), ("zh", 0), ("en", 480), ("zh", 480)])
def test_buttons_badges_and_short_labels_are_one_line(lab, lang, narrow):
    page = lab.open(lang=lang, narrow=narrow)
    assert page.evaluate("(s) => document.querySelectorAll(s).length", ONE_LINE) > 100
    broken = page.evaluate(LINES, ONE_LINE)
    assert not broken, broken[:10]


# ── controls ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# The controls that stand beside each other in the lab's "one level, one height" rows.
LEVEL = """(level) => [...document.querySelectorAll('[data-level="' + level + '"] > *')].map((el) => {
  const r = el.getBoundingClientRect()
  return { what: el.tagName.toLowerCase() + '.' + (el.getAttribute('class') || '') + (el.type ? '[' + el.type + ']' : ''), h: r.height, top: r.top, middle: r.top + r.height / 2 }
})"""
ICON_BUTTONS = """() => [...document.querySelectorAll('.lab .icon-btn')].map((el) => {
  const r = el.getBoundingClientRect(), glyph = el.querySelector('svg')
  return { name: el.getAttribute('aria-label') || '', w: r.width, h: r.height, small: el.classList.contains('sm'), busy: el.classList.contains('busy'),
           titled: el.hasAttribute('title'), glyph: !!glyph, where: (el.closest('[data-lab]') || {}).dataset?.lab }
})"""


def check_controls(page) -> None:
    for level, height in (("md", 32), ("sm", 28)):
        row = page.evaluate(LEVEL, level)
        kinds = " ".join(c["what"] for c in row)
        assert "button" in kinds and "input" in kinds and ".sel" in kinds, kinds
        assert level != "md" or "div.seg" in kinds, kinds
        assert all(abs(c["h"] - height) <= PX / 2 for c in row), (level, [(c["what"], c["h"]) for c in row if abs(c["h"] - height) > PX / 2])
        assert max(c["middle"] for c in row) - min(c["middle"] for c in row) <= PX, (level, "the controls of one row are not on one line", [(c["what"], c["middle"]) for c in row])
    icons = page.evaluate(ICON_BUTTONS)
    assert len(icons) > 20
    for b in icons:
        assert b["name"].strip(), ("an icon button without a name", b)
        assert not b["titled"] and b["glyph"], b
        side = 24 if b["small"] else 28
        assert abs(b["w"] - side) <= PX / 2 and abs(b["h"] - side) <= PX / 2, ("an icon button is not the square it should be", b)
    # the sizes of ordinary buttons, and a badge
    for size, height in (("sm", 28), ("md", 32), ("lg", 36)):
        heights = page.evaluate("(size) => [...document.querySelectorAll('[data-btn-size=\"' + size + '\"] > *')].map((e) => e.getBoundingClientRect().height)", size)
        assert len(heights) >= 6 and all(abs(h - height) <= PX / 2 for h in heights), (size, heights)
    tags = page.evaluate("() => [...document.querySelectorAll('.lab .tag, .lab .badge')].filter((e) => e.getBoundingClientRect().width).map((e) => e.getBoundingClientRect().height)")
    assert tags and all(abs(h - 20) <= PX / 2 for h in tags), sorted(set(tags))


@pytest.mark.parametrize("theme,lang", LOOKS)
def test_controls_of_one_level_are_one_height(lab, theme, lang):
    check_controls(lab.open(theme=theme, lang=lang))


def test_a_button_that_is_under_way_keeps_its_size(lab):
    page = lab.open(only="Buttons", own=True)
    size = SIZE
    # an icon button: pressed, it works for a moment - the spinner stands where the glyph was
    icon = page.locator('[data-icon-size="md"] .icon-btn[aria-label="Check again"]')
    neighbour = page.locator('[data-icon-size="md"] .icon-btn[aria-label="More"]')
    before, beside = icon.evaluate(size), neighbour.evaluate(size)
    icon.click()
    page.wait_for_selector('[data-icon-size="md"] .icon-btn.busy[aria-label="Check again"]')
    frames(page)      # (it stays under way for nearly two seconds)
    assert icon.get_attribute("aria-busy") == "true"
    assert icon.evaluate(size) == pytest.approx(before, abs=PX / 2) and neighbour.evaluate(size) == pytest.approx(beside, abs=PX / 2)
    assert icon.evaluate("(e) => getComputedStyle(e.querySelector('svg')).visibility") == "hidden"      # the glyph gave way, its room did not
    # and the one the lab shows under way all the time is the square its neighbours are
    always = page.locator('[data-icon-size="md"] .icon-btn[aria-label="Checking"]')
    assert always.evaluate(size)[:2] == pytest.approx(neighbour.evaluate(size)[:2], abs=PX / 2)
    assert always.evaluate("(e) => getComputedStyle(e.querySelector('svg')).visibility") == "hidden"


SIZE = "(e) => { const r = e.getBoundingClientRect(); return [r.width, r.height, r.left, r.top] }"


def mark_busy(page):
    """An ordinary button and the one after it, before and after it is marked the way ui.run marks the button that was
    pressed (data-busy)."""
    button, beside = page.locator('[data-btn-size="md"] > button').nth(0), page.locator('[data-btn-size="md"] > button').nth(1)
    before = button.evaluate(SIZE), beside.evaluate(SIZE)
    button.evaluate("(e) => { e.setAttribute('data-busy', ''); e.setAttribute('aria-busy', 'true') }")
    return before, (button.evaluate(SIZE), beside.evaluate(SIZE))


def test_an_ordinary_button_that_is_under_way_keeps_its_height(lab):
    (before, _), (after, _) = mark_busy(lab.open(only="Buttons", own=True))
    assert after[1] == pytest.approx(before[1], abs=PX / 2) and after[3] == pytest.approx(before[3], abs=PX / 2)


def test_an_ordinary_button_that_is_under_way_keeps_its_width_and_moves_nothing(lab):
    """(The spinner stands over the label, not after it: the button does not grow and pushes nothing aside.)"""
    page = lab.open(only="Buttons", own=True)
    (button, beside), (b_after, beside_after) = mark_busy(page)
    frames(page)
    b_after = page.locator('[data-btn-size="md"] > button').nth(0).evaluate(SIZE)
    beside_after = page.locator('[data-btn-size="md"] > button').nth(1).evaluate(SIZE)
    assert b_after == pytest.approx(button, abs=PX / 2), ("the button changed its size or place while under way", button, b_after)
    assert beside_after == pytest.approx(beside, abs=PX / 2), ("the button beside it moved", beside, beside_after)


# ── tooltip, menu, popover ───────────────────────────────────────────────────────────────────────────────────────────
ACTIVE = "() => { const e = document.activeElement; return e ? (e.getAttribute('data-t') || e.getAttribute('aria-label') || e.textContent.trim()) : '' }"
INSIDE = """(selector) => { const r = document.querySelector(selector).getBoundingClientRect(), w = document.documentElement.clientWidth, h = document.documentElement.clientHeight
  return { ok: r.left >= 0 && r.top >= 0 && r.right <= w && r.bottom <= h && r.width > 0 && r.height > 0, box: [r.left, r.top, r.right, r.bottom], window: [w, h] } }"""


def opened(page, selector: str) -> None:
    """A menu or a popover is there, and where it belongs: it is drawn, measured, then put beside its button."""
    page.wait_for_selector(selector)
    frames(page)


def test_the_tooltip_shows_on_keyboard_focus_and_escape_hides_it(lab):
    page = lab.open(only="Tooltip", own=True)
    page.focus('[data-t="top"]')      # put there by the program: says nothing (a drawer that closes gives the focus back like this)
    page.wait_for_timeout(150)
    assert not page.query_selector(TIP)
    page.keyboard.press("Tab")        # moved there by the person: at once, without the hover's wait
    page.wait_for_selector(TIP, timeout=300)
    assert page.evaluate(ACTIVE) == "bottom" and tip_text(page) == "Below the button"
    assert page.get_attribute('[data-t="bottom"]', "aria-describedby") == "aa-tip"
    assert page.evaluate("() => document.querySelector('#aa-tip').dataset.side") == "bottom"
    page.keyboard.press("Escape")
    page.wait_for_selector(TIP, state="detached")
    assert page.evaluate(ACTIVE) == "bottom"      # the focus stays where it was
    assert page.get_attribute('[data-t="bottom"]', "aria-describedby") is None
    # an icon button's name is its tooltip; the (i) too
    page.focus('[data-t="iconbtn"]')
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    page.wait_for_selector(TIP, timeout=300)
    assert tip_text(page) == "Show the password" == page.get_attribute('[data-t="iconbtn"]', "aria-label")
    # a text that is empty shows nothing
    page.keyboard.press("Escape")
    no_tip_after_hovering(page, '[data-t="empty"]')


@pytest.mark.parametrize("width,height", [(1440, 900), (640, 700)])
def test_the_tooltip_stays_inside_the_window_at_its_edges(lab, width, height):
    page = lab.open(width=width, height=height, only="Tooltip", own=True)
    page.click('[data-t="corners"]')
    for corner in ("c-tl", "c-tr", "c-bl", "c-br"):
        hover(page, f'[data-t="{corner}"]')
        page.wait_for_selector(TIP)
        page.wait_for_timeout(50)      # (placed after it was measured)
        where = page.evaluate(INSIDE, "#aa-tip")
        assert where["ok"], (corner, where)
        assert len(tip_text(page)) > 60      # the whole sentence, not a shortened one
        page.mouse.move(width / 2, height / 2)
        page.wait_for_selector(TIP, state="detached")
    # asked to the right of a button at the right edge: it goes where there is room
    page.click('[data-t="corners"]')
    page.locator('[data-t="edge-right"]').scroll_into_view_if_needed()
    hover(page, '[data-t="edge-right"]')
    page.wait_for_selector(TIP)
    page.wait_for_timeout(50)
    assert page.evaluate(INSIDE, "#aa-tip")["ok"]


def test_a_menu_is_worked_with_the_keyboard_and_gives_the_focus_back(lab):
    page = lab.open(only="Menu", own=True)
    trigger = page.locator('[data-t="m-default"] > button')
    assert trigger.get_attribute("aria-haspopup") == "menu" and trigger.get_attribute("aria-expanded") == "false"
    trigger.focus()
    page.keyboard.press("Enter")
    opened(page, '.menu-pop[role="menu"]')
    assert trigger.get_attribute("aria-expanded") == "true"
    assert page.evaluate(ACTIVE) == "Open the posting"      # the focus is on the first action
    page.keyboard.press("ArrowDown")
    assert page.evaluate(ACTIVE) == "Copy the link"
    page.keyboard.press("ArrowUp")
    assert page.evaluate(ACTIVE) == "Open the posting"
    page.keyboard.press("End")
    assert page.evaluate(ACTIVE) == "Delete the account"
    page.keyboard.press("Home")
    page.keyboard.press("ArrowDown")
    assert page.evaluate(INSIDE, ".menu-pop")["ok"]
    page.keyboard.press("Enter")
    page.wait_for_selector(".menu-pop", state="detached")
    assert page.inner_text('[data-t="picked"]') == "copy"
    assert trigger.evaluate("(e) => e === document.activeElement") and trigger.get_attribute("aria-expanded") == "false"
    # Escape closes it without choosing, and the focus is on the button again
    page.keyboard.press("Enter")
    opened(page, ".menu-pop")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Escape")
    page.wait_for_selector(".menu-pop", state="detached")
    assert page.inner_text('[data-t="picked"]') == "copy" and trigger.evaluate("(e) => e === document.activeElement")
    # a menu at the right edge of the page opens inside the window; pressing it does not press the row it is in
    page.click('[data-t="m-edge"] > button')
    opened(page, ".menu-pop")
    assert page.evaluate(INSIDE, ".menu-pop")["ok"]
    page.keyboard.press("Escape")
    page.click('[data-t="m-row"] > button')
    opened(page, ".menu-pop")
    page.keyboard.press("Escape")
    assert page.inner_text('[data-t="row-opened"]') == "0"


def test_a_popover_takes_the_focus_and_gives_it_back_on_escape(lab):
    page = lab.open(only="Popover", own=True)
    trigger = page.locator('[data-t="p-form-btn"]')
    assert trigger.get_attribute("aria-haspopup") == "dialog"
    trigger.focus()
    page.keyboard.press("Enter")
    opened(page, '.pop[role="dialog"]')
    assert page.get_attribute(".pop", "aria-label") == "The browser of this site"
    assert page.evaluate("() => document.querySelector('.pop').contains(document.activeElement)")
    assert page.evaluate(ACTIVE) == "p-name"      # on what the box is for, not on the (i) beside its label
    assert page.evaluate(INSIDE, ".pop")["ok"]
    page.keyboard.press("Escape")
    page.wait_for_selector(".pop", state="detached")
    assert trigger.evaluate("(e) => e === document.activeElement") and trigger.get_attribute("aria-expanded") == "false"
    # a text: the focus goes to the box itself; a press outside closes it
    page.click('[data-t="p-help-btn"]')
    opened(page, ".pop")
    assert page.evaluate("() => document.querySelector('.pop').contains(document.activeElement)")
    page.mouse.click(5, 5)
    page.wait_for_selector(".pop", state="detached")
    # at the right edge of the page it stays inside the window
    page.click('[data-t="p-edge-btn"]')
    opened(page, ".pop")
    assert page.evaluate(INSIDE, ".pop")["ok"]


# ── accessibility basics ─────────────────────────────────────────────────────────────────────────────────────────────
# Buttons and links without a name a screen reader could say: their words, an aria-label, or what aria-labelledby names.
NAMELESS = """() => [...document.querySelectorAll('.lab button, .lab a, .lab [role="button"], .lab [role="link"]')].filter((el) => {
  const by = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).map((id) => document.getElementById(id)).filter(Boolean).map((e) => e.textContent).join(' ')
  const alt = [...el.querySelectorAll('img[alt]')].map((i) => i.alt).join(' ')
  return !(by.trim() || (el.getAttribute('aria-label') || '').trim() || el.textContent.trim() || alt.trim())
}).map((el) => (el.closest('[data-lab]') || {}).dataset?.lab + ': ' + el.outerHTML.slice(0, 140))"""
RING = """() => { const e = document.activeElement, s = getComputedStyle(e)
  return { what: e.tagName.toLowerCase() + '.' + (e.getAttribute('class') || '') + ' "' + (e.getAttribute('aria-label') || e.textContent.trim()).slice(0, 30) + '"', inLab: !!e.closest('.lab'),
           parts: ['date', 'time', 'datetime-local', 'month', 'week'].includes(e.type),
           seen: e.matches(':focus-visible'), style: s.outlineStyle, width: parseFloat(s.outlineWidth) || 0, shadow: s.boxShadow } }"""


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_every_button_and_link_has_a_name(lab, lang):
    page = lab.open(lang=lang)
    assert page.evaluate("() => document.querySelectorAll('.lab button, .lab a').length") > 150
    nameless = page.evaluate(NAMELESS)
    assert not nameless, nameless


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_keyboards_place_is_always_visible(lab, theme):
    page = lab.open(theme=theme, only="Buttons,Cells,Status,Heads", own=True)
    page.evaluate("() => document.querySelector('.lab button, .lab a').focus()")
    seen = []
    for _ in range(70):
        page.keyboard.press("Tab")
        ring = page.evaluate(RING)
        if not ring["inLab"]:
            break
        seen.append(ring["what"])
        if ring["parts"]:      # a date field: the browser marks the part (day, month, the calendar button) the keyboard is on
            continue
        assert ring["seen"], ring
        assert ring["style"] not in ("none", "hidden") and ring["width"] >= 2, ("no focus ring on", ring)
    kinds = " ".join(seen)
    assert len(seen) >= 40 and "button." in kinds and "input." in kinds and "icon-btn" in kinds and "a." in kinds, seen


def test_reduced_motion_takes_the_transitions_away(lab):
    longest = """() => { let most = 0, where = ''
      const seconds = (v) => Math.max(...v.split(',').map((x) => (x.trim().endsWith('ms') ? parseFloat(x) / 1000 : parseFloat(x)) || 0))
      for (const el of document.querySelectorAll('body *')) {
        const s = getComputedStyle(el), t = Math.max(seconds(s.transitionDuration), s.animationName !== 'none' ? seconds(s.animationDuration) : 0)
        if (t > most) { most = t; where = el.tagName.toLowerCase() + '.' + (el.getAttribute('class') || '') }
      }
      return { most, where } }"""
    moving = lab.open(only="Buttons,DataTable,Tooltip", motion=True).evaluate(longest)
    assert moving["most"] >= 0.1, ("nothing moves even without the setting: the check below would say nothing", moving)
    still_page = lab.open(only="Buttons,DataTable,Tooltip", own=True)
    hover(still_page, '[data-t="top"]')
    still_page.wait_for_selector(TIP)
    still = still_page.evaluate(longest)
    assert still["most"] <= 0.001, ("something still moves under prefers-reduced-motion", still)


# ── accounts: provider cards and the credential cell ─────────────────────────────────────────────────────────────────
# The lab's Accounts section (written with the accounts page): the grids of provider cards, and the accounts table
# with a CredentialCell in every row.
ACCOUNTS = """() => {
  const sec = document.querySelector('[data-lab="Accounts"]')
  if (!sec) return null
  const box = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height } }
  const grids = [...sec.querySelectorAll('[data-lab-acc^="cards"]')].map((g) => ({
    name: g.dataset.labAcc, box: box(g),
    cards: [...g.querySelectorAll('.pcard')].map((c) => ({ ...box(c), foot: c.querySelector('.pcard-foot') ? box(c.querySelector('.pcard-foot')) : null, main: c.querySelector('.pcard-foot button') ? box(c.querySelector('.pcard-foot button')) : null })),
  }))
  const rows = [...sec.querySelectorAll('[data-lab-acc="table"] tbody > tr.dt-row')].map((r) => {
    const cred = r.querySelector('.cred'), text = cred && cred.querySelector('.cred-text'), buttons = cred ? [...cred.querySelectorAll('.cred-acts button')] : []
    return { h: box(r).h, cred: cred ? box(cred) : null, text: text ? box(text).l : null, last: buttons.length ? box(buttons[buttons.length - 1]) : null, buttons: buttons.length }
  })
  return { grids, rows }
}"""


@pytest.mark.parametrize("theme,lang", [("light", "en"), ("dark", "zh")])
def test_provider_cards_line_up_and_the_credential_button_stands_in_one_place(lab, theme, lang):
    page = lab.open(theme=theme, lang=lang)
    found = page.evaluate(ACCOUNTS)
    if found is None:
        pytest.skip("the lab has no Accounts section")
    # provider cards: those of one row are one height, and their feet (the button row) end on one line
    assert found["grids"] and all(g["cards"] for g in found["grids"]), "the Accounts section shows no grid of provider cards ([data-lab-acc^=cards] .pcard)"
    beside = 0
    for g in found["grids"]:
        rows: dict = {}
        for card in g["cards"]:      # cards whose tops are in line stand in one row
            assert card["l"] >= g["box"]["l"] - PX and card["r"] <= g["box"]["r"] + PX, (g["name"], "a card reaches out of its grid", card)
            rows.setdefault(round(card["t"]), []).append(card)
        for cards in rows.values():
            beside = max(beside, len(cards))
            assert max(c["h"] for c in cards) - min(c["h"] for c in cards) <= PX, (g["name"], "provider cards of one row differ in height", [c["h"] for c in cards])
            assert max(c["w"] for c in cards) - min(c["w"] for c in cards) <= PX, (g["name"], "provider cards of one row differ in width", [c["w"] for c in cards])
            feet = [c["foot"] for c in cards]
            assert all(feet), "a provider card has no .pcard-foot"
            assert max(f["b"] for f in feet) - min(f["b"] for f in feet) <= PX, (g["name"], "the feet of the cards of one row do not line up", [f["b"] for f in feet])
            mains = [c["main"] for c in cards if c["main"]]
            assert max(m["t"] for m in mains) - min(m["t"] for m in mains) <= PX and max(m["h"] for m in mains) - min(m["h"] for m in mains) <= PX, (g["name"], "the main buttons of one row are not on one line", mains)
    assert beside >= 2, "no two provider cards stand beside each other"
    # the accounts table: whatever a row's password cell shows - dots, the value, nothing saved - its text starts at
    # one place and its last button (show / hide / add) stands at one place
    rows = [r for r in found["rows"] if r["cred"]]
    assert len(rows) >= 4, "the Accounts section's table shows no rows with a credential cell (.cred)"
    assert {r["buttons"] for r in rows} >= {1}, rows
    assert max(r["h"] for r in rows) - min(r["h"] for r in rows) <= PX, [r["h"] for r in rows]
    assert all(r["last"] for r in rows), "a credential cell without a button"
    for what, at in (("text", [r["text"] for r in rows]), ("button", [r["last"]["l"] for r in rows]), ("button's top edge in its row", [r["last"]["t"] - r["cred"]["t"] for r in rows])):
        assert max(at) - min(at) <= PX, (f"the credential cell's {what} moves from row to row", at)
