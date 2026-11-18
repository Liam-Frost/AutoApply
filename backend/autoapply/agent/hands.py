"""The browser, as the agent's tools.

Nothing here knows what an application form is. The tools show the page (a screenshot, its text, its controls with a
number each) and act on it (click, type, choose, upload, keys, a script); what to do with them is the agent's.

Every control the page shows is given a number that stays with it while the page lives (``[12] button "Next"``), in
the page itself and inside its open shadow roots and same-origin frames. A tool acts on a number, on a CSS selector,
or on a point of the screenshot - whichever the agent finds the control by.

Works on both browsers the program drives (the automated one and the ordinary one): only what both offer is used -
a script in the page, the mouse, the keyboard, a file for a file field.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from .. import llm

# The controls of the page, numbered. Run in the page; returns lines of text.
_CONTROLS = r"""(opts) => {
  const want = (opts && opts.filter || '').toLowerCase(), all = !!(opts && opts.all), limit = (opts && opts.limit) || 300;
  const SEL = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], [role=checkbox], [role=radio], [role=switch], [role=combobox], [role=listbox], [role=option], [role=menuitem], [role=tab], [role=textbox], [role=searchbox], [role=spinbutton], [role=slider], [contenteditable=""], [contenteditable=true], [tabindex]:not([tabindex="-1"]), label[for]';
  window.__aaN = window.__aaN || 0;
  const text = (n) => ((n && (n.innerText || n.textContent)) || '').replace(/\s+/g, ' ').trim();
  const out = [];
  const walk = (root, dx, dy, depth) => {
    let found = [];
    try { found = [...root.querySelectorAll(SEL)]; } catch (e) {}
    for (const e of found) {
      const tag = e.tagName.toLowerCase(), type = (e.getAttribute('type') || '').toLowerCase();
      if (tag === 'input' && type === 'hidden') continue;
      if (tag === 'label' && e.htmlFor && root.getElementById && root.getElementById(e.htmlFor)) continue;      // its control is listed
      const r = e.getBoundingClientRect(), st = getComputedStyle(e);
      const shown = r.width > 1 && r.height > 1 && st.visibility !== 'hidden' && st.display !== 'none';
      const real = shown && st.opacity !== '0';
      // a file field, a checkbox, a radio is often there without being seen (a styled label stands for it): listed anyway
      const stands = tag === 'input' && ['file', 'checkbox', 'radio'].includes(type);
      if (!all && !real && !stands) continue;
      let ref = e.getAttribute('data-aa');
      if (!ref) { ref = String(++window.__aaN); e.setAttribute('data-aa', ref); }
      const role = e.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'input' ? (type || 'text') : tag === 'label' ? 'label' : tag);
      const by = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map((id) => text(document.getElementById(id))).join(' ');
      let lab = '';
      if (e.labels && e.labels.length) lab = [...e.labels].map(text).join(' ');
      if (!lab && e.closest) { const w = e.closest('label'); if (w) lab = text(w); }
      const name = (e.getAttribute('aria-label') || by || lab || (['button', 'a', 'summary', 'label'].includes(tag) || e.getAttribute('role') ? text(e) : '') || e.getAttribute('placeholder') || e.getAttribute('title') || e.getAttribute('alt') || e.getAttribute('name') || e.id || text(e) || '').slice(0, 140);
      const bits = [];
      if (tag === 'select') {
        const opt = [...e.options];
        bits.push('chosen=' + JSON.stringify(opt.filter((o) => o.selected).map((o) => text(o)).join(', ')));
        bits.push('options=' + JSON.stringify(opt.slice(0, 40).map((o) => text(o)).filter(Boolean)) + (opt.length > 40 ? ' (+' + (opt.length - 40) + ' more)' : ''));
      } else if (tag === 'input' && ['checkbox', 'radio'].includes(type)) {
        bits.push(e.checked ? 'checked' : 'not checked');
      } else if (e.getAttribute('aria-checked')) {
        bits.push(e.getAttribute('aria-checked') === 'true' ? 'checked' : 'not checked');
      } else if (tag === 'input' && type === 'password') {
        bits.push(e.value ? 'filled (hidden)' : 'empty');
      } else if (tag === 'input' && type === 'file') {
        bits.push('files=' + JSON.stringify([...(e.files || [])].map((f) => f.name)));
      } else if (tag === 'input' || tag === 'textarea') {
        bits.push('value=' + JSON.stringify(String(e.value || '').slice(0, 160)) + (String(e.value || '').length > 160 ? '…' : ''));
      } else if (e.isContentEditable) {
        bits.push('text=' + JSON.stringify(text(e).slice(0, 160)));
      }
      if (e.required || e.getAttribute('aria-required') === 'true') bits.push('required');
      if (e.disabled || e.getAttribute('aria-disabled') === 'true') bits.push('disabled');
      if (e.getAttribute('aria-expanded')) bits.push(e.getAttribute('aria-expanded') === 'true' ? 'open' : 'closed');
      if (e.getAttribute('aria-selected') === 'true') bits.push('selected');
      if (e.getAttribute('aria-invalid') === 'true') {
        const err = (e.getAttribute('aria-errormessage') || e.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean).map((id) => text(document.getElementById(id))).join(' ');
        bits.push('INVALID' + (err ? ': ' + err.slice(0, 120) : ''));
      }
      if (!real) bits.push('not visible');
      const inView = r.bottom > 0 && r.top < innerHeight;
      const line = '[' + ref + '] ' + role + ' ' + JSON.stringify(name) + (bits.length ? ' ' + bits.join(' ') : '') + (inView || !real ? '' : ' (off screen)') + (depth ? ' (in frame)' : '');
      if (want && !line.toLowerCase().includes(want)) continue;
      out.push(line);
      if (out.length >= limit) return;
    }
    let every = [];
    try { every = [...root.querySelectorAll('*')]; } catch (e) {}
    // What the page makes clickable without saying so: a link without an address, a div with a handler ("Remove this
    // job"). Told by the pointer the page shows over it; listed once, at the outermost element that has it.
    for (const e of every) {
      if (out.length >= limit) return;
      if (e.matches(SEL) || e.closest(SEL) || e.querySelector(SEL)) continue;
      const st = getComputedStyle(e);
      if (st.cursor !== 'pointer' || (e.parentElement && getComputedStyle(e.parentElement).cursor === 'pointer')) continue;
      const r = e.getBoundingClientRect(), name = text(e).slice(0, 140);
      if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || !name) continue;
      let ref = e.getAttribute('data-aa');
      if (!ref) { ref = String(++window.__aaN); e.setAttribute('data-aa', ref); }
      const inView = r.bottom > 0 && r.top < innerHeight;
      const line = '[' + ref + '] clickable ' + JSON.stringify(name) + (inView ? '' : ' (off screen)') + (depth ? ' (in frame)' : '');
      if (want && !line.toLowerCase().includes(want)) continue;
      out.push(line);
    }
    for (const e of every) {
      if (out.length >= limit) return;
      if (e.shadowRoot) walk(e.shadowRoot, dx, dy, depth);
      if (e.tagName === 'IFRAME') { try { if (e.contentDocument) { const r = e.getBoundingClientRect(); walk(e.contentDocument, dx + r.left, dy + r.top, depth + 1); } } catch (err) {} }
    }
  };
  walk(document, 0, 0, 0);
  const frames = [...document.querySelectorAll('iframe')].filter((f) => { try { return !f.contentDocument; } catch (e) { return true; } }).map((f) => f.src).filter(Boolean);
  return out.join('\n') + (out.length >= limit ? '\n… (more: narrow it with filter=…)' : '')
    + (frames.length ? '\nFrames from another site, not listed here (open one with goto to work in it): ' + frames.slice(0, 5).join(' , ') : '');
}"""

# Find a numbered control (through shadow roots and same-origin frames), bring it into view, say where it is.
_WHERE = r"""(ref) => {
  const find = (root, dx, dy) => {
    let hit = null;
    try { hit = root.querySelector('[data-aa="' + ref + '"]'); } catch (e) {}
    if (hit) return [hit, dx, dy];
    let every = [];
    try { every = [...root.querySelectorAll('*')]; } catch (e) {}
    for (const e of every) {
      if (e.shadowRoot) { const h = find(e.shadowRoot, dx, dy); if (h) return h; }
      if (e.tagName === 'IFRAME') { try { if (e.contentDocument) { const r = e.getBoundingClientRect(); const h = find(e.contentDocument, dx + r.left, dy + r.top); if (h) return h; } } catch (err) {} }
    }
    return null;
  };
  let got = find(document, 0, 0);
  if (!got) return null;
  got[0].scrollIntoView({block: 'center', inline: 'center'});
  got = find(document, 0, 0);
  const e = got[0], r = e.getBoundingClientRect();
  window.__aaAt = e;
  return {x: got[1] + r.left + r.width / 2, y: got[2] + r.top + r.height / 2, w: r.width, h: r.height, tag: e.tagName.toLowerCase(), type: (e.getAttribute('type') || '').toLowerCase(),
          editable: !!e.isContentEditable, top: got[1] === 0 && got[2] === 0 && e.ownerDocument === document && !e.getRootNode().host};
}"""


class Hands:
    """The tools of one run. ``page``: the page the agent starts on; it follows the agent to whatever tab it opens.
    ``files``: the applicant's documents it may upload, by the name it is told ({name: path})."""

    def __init__(self, page: Any, *, files: dict[str, str] | None = None, shots: Path | None = None) -> None:
        self.page, self.files, self.shots = page, dict(files or {}), shots
        self.n_shots = 0

    # --- seeing ------------------------------------------------------------------------------------------------
    def _where_am_i(self) -> str:
        try:
            return f"{self.page.title()[:80]!r} at {self.page.url}"
        except Exception:  # noqa: BLE001 - between two pages
            return "a page that is loading"

    def look(self) -> list:
        """A picture of what the window shows now."""
        png = self.page.screenshot(full_page=False)
        if self.shots is not None:
            self.shots.mkdir(parents=True, exist_ok=True)
            self.n_shots += 1
            (self.shots / f"{self.n_shots:03d}.png").write_bytes(png)
        return [{"type": "text", "text": self._where_am_i()}, llm.image_block(png)]

    def read(self, max_chars: int = 20000, find: str = "") -> str:
        """The text of the page (and of its same-origin frames). ``find``: only the lines around this word."""
        js = r"""() => { const parts = [document.body ? document.body.innerText : ''];
            for (const f of document.querySelectorAll('iframe')) { try { if (f.contentDocument && f.contentDocument.body) parts.push('[frame] ' + f.contentDocument.body.innerText); } catch (e) {} }
            return parts.join('\n'); }"""
        text = str(self.page.evaluate(js) or "")
        if find:
            lines, low = text.splitlines(), find.lower()
            keep: list[str] = []
            for i, ln in enumerate(lines):
                if low in ln.lower():
                    keep += ["…"] + lines[max(0, i - 2): i + 4]
            text = "\n".join(keep) or f"(nothing on the page says {find!r})"
        return f"{self._where_am_i()}\n\n{text[:max_chars]}" + ("\n… (cut; ask for more with max_chars, or for a part with find)" if len(text) > max_chars else "")

    def controls(self, filter: str = "", all: bool = False) -> str:  # noqa: A002
        """Everything on the page that can be acted on, each with its number."""
        got = str(self.page.evaluate(_CONTROLS, {"filter": filter, "all": bool(all)}) or "")
        return f"{self._where_am_i()}\n{got or '(no controls found)'}"

    # --- acting ------------------------------------------------------------------------------------------------
    def _at(self, ref: str = "", selector: str = "") -> dict[str, Any]:
        if selector:
            n = self.page.evaluate("""(sel) => { const e = document.querySelector(sel); if (!e) return null;
                if (!e.getAttribute('data-aa')) { window.__aaN = (window.__aaN || 0) + 1; e.setAttribute('data-aa', String(window.__aaN)); } return e.getAttribute('data-aa'); }""", selector)
            if not n:
                raise LookupError(f"nothing on the page matches the selector {selector!r}")
            ref = str(n)
        ref = str(ref).strip().strip("[]")
        at = self.page.evaluate(_WHERE, ref)
        if not at:
            raise LookupError(f"there is no control [{ref}] on this page any more (the page changed: list the controls again)")
        at["ref"] = ref
        return at

    def _settle(self, before: list[Any], seconds: float = 0.6) -> str:
        """After an action: give the page a moment, and follow it to a tab it opened."""
        time.sleep(seconds)
        try:
            pages = [p for p in self.page.context.pages if not p.is_closed()]
        except Exception:  # noqa: BLE001
            pages = []
        new = [p for p in pages if p not in before]
        if new:
            self.page = new[-1]
            try:
                self.page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            return f" It opened a new tab, which is the current one now: {self._where_am_i()}."
        return f" Now on {self._where_am_i()}."

    def _pages(self) -> list[Any]:
        try:
            return [p for p in self.page.context.pages if not p.is_closed()]
        except Exception:  # noqa: BLE001
            return [self.page]

    def click(self, ref: str = "", selector: str = "", x: float = -1, y: float = -1, double: bool = False) -> str:
        """Click a control by its number or a selector, or a point of the picture."""
        before = self._pages()
        if x >= 0 and y >= 0 and not ref and not selector:
            px, py, what = float(x), float(y), f"the point ({int(x)}, {int(y)})"
        else:
            at = self._at(ref, selector)
            px, py, what = at["x"], at["y"], f"[{at['ref']}]"
            if at["w"] < 2 or at["h"] < 2:       # there without being seen (a file field, a styled checkbox): pressed through the page
                self.page.evaluate("() => { window.__aaAt.click(); }")
                return f"clicked {what} (it has no size on screen, so through the page)." + self._settle(before)
        self.page.mouse.click(px, py)
        if double:
            self.page.mouse.click(px, py)
        return f"clicked {what}." + self._settle(before)

    def type(self, text: str, ref: str = "", selector: str = "", keys: bool = False, enter: bool = False) -> str:  # noqa: A003
        """Put text in a box, replacing what it holds. ``keys``: key by key (a box that searches as one types).
        Without a number or selector: into whatever has the focus."""
        before = self._pages()
        if ref or selector:
            at = self._at(ref, selector)
            if at["type"] == "password" and text != "":       # (emptying a password box is not typing a password)
                raise PermissionError("a password is not typed by you: use type_password for the applicant's password on this site")
            self.page.mouse.click(at["x"], at["y"])
            time.sleep(0.15)
            self.page.evaluate("""() => { const e = window.__aaAt; if (!e) return; e.focus();
                if (e.select) { try { e.select(); } catch (err) {} } else if (e.isContentEditable) { const r = document.createRange(); r.selectNodeContents(e); const s = getSelection(); s.removeAllRanges(); s.addRange(r); } }""")
        elif text != "" and self.page.evaluate("() => { const e = document.activeElement; return !!(e && e.tagName === 'INPUT' && (e.getAttribute('type') || '').toLowerCase() === 'password'); }"):
            raise PermissionError("a password is not typed by you: use type_password for the applicant's password on this site")
        if text == "":
            self.page.keyboard.press("Delete")
        elif keys:
            self.page.keyboard.press("Delete")
            self.page.keyboard.type(str(text), delay=35)
        else:
            self.page.keyboard.insert_text(str(text))
        if enter:
            self.page.keyboard.press("Enter")
        return f"typed {len(str(text))} character(s)." + self._settle(before, 0.4)

    def press(self, keys: str) -> str:
        """Press a key or a chord (Enter, Tab, Escape, ArrowDown, Control+A ...), on what has the focus."""
        before = self._pages()
        for key in str(keys).split():
            self.page.keyboard.press(key)
        return f"pressed {keys}." + self._settle(before, 0.4)

    def choose(self, option: str, ref: str = "", selector: str = "") -> str:
        """Choose an entry of a native list (a <select>) by its text."""
        at = self._at(ref, selector)
        if at["tag"] != "select":
            raise LookupError(f"[{at['ref']}] is not a native list: click it, then click the entry it shows (or type into it)")
        got = self.page.evaluate("""(want) => { const e = window.__aaAt, low = want.trim().toLowerCase();
            const t = (o) => (o.textContent || '').replace(/\\s+/g, ' ').trim();
            const opt = [...e.options].find((o) => t(o).toLowerCase() === low || o.value.toLowerCase() === low) || [...e.options].find((o) => t(o).toLowerCase().includes(low));
            if (!opt) return null;
            Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(e, opt.value);
            e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
            return t(opt); }""", str(option))
        if got is None:
            raise LookupError(f"[{at['ref']}] has no entry like {option!r}: list the controls to see its entries")
        return f"chose {got!r} in [{at['ref']}]."

    def upload(self, file: str, ref: str = "", selector: str = "") -> str:
        """Give one of the applicant's files to a file field, or to the button that opens the file window."""
        if file not in self.files:
            raise LookupError(f"there is no file called {file!r}. The applicant's files: {sorted(self.files)}")
        path = self.files[file]
        at = self._at(ref, selector)
        before = self._pages()
        if at["tag"] == "input" and at["type"] == "file":
            self.page.locator(f'[data-aa="{at["ref"]}"]').set_input_files(path)
        else:
            with self.page.expect_file_chooser(timeout=15000) as chooser:
                self.page.mouse.click(at["x"], at["y"])
            chooser.value.set_files(path)
        return f"gave {file!r} to [{at['ref']}]." + self._settle(before, 1.5)

    def scroll(self, down: int = 600, ref: str = "") -> str:
        """Scroll the page (negative: up), or bring a numbered control into view."""
        if ref:
            self._at(ref)
            return f"[{ref}] is in view."
        self.page.evaluate("(dy) => { (document.scrollingElement || document.documentElement).scrollBy(0, dy); }", int(down))
        return "scrolled."

    def goto(self, url: str) -> str:
        """Open an address in the current tab."""
        self.page.goto(str(url), wait_until="domcontentloaded")
        return "opened." + self._settle(self._pages(), 1.0)

    def back(self) -> str:
        self.page.evaluate("() => history.back()")
        return "went back." + self._settle(self._pages(), 1.0)

    def tabs(self, switch_to: int = 0, close: int = 0) -> str:
        """The tabs of this window; ``switch_to`` / ``close`` one by its number (from 1)."""
        pages = self._pages()
        if close and 1 <= close <= len(pages) and len(pages) > 1:
            gone = pages[close - 1]
            gone.close()
            pages = self._pages()
            if gone is self.page:
                self.page = pages[-1]
        if switch_to and 1 <= switch_to <= len(pages):
            self.page = pages[switch_to - 1]
            try:
                self.page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
        lines = []
        for i, p in enumerate(pages, 1):
            try:
                lines.append(f"{i}. {'(current) ' if p is self.page else ''}{p.title()[:70]!r} {p.url}")
            except Exception:  # noqa: BLE001
                lines.append(f"{i}. (loading)")
        return "\n".join(lines)

    def script(self, code: str) -> str:
        """Run JavaScript in the page and get its result (an arrow function or an expression)."""
        out = self.page.evaluate(str(code))
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)
        return (text or "")[:20000]

    def wait(self, seconds: float = 2) -> str:
        time.sleep(max(0.2, min(float(seconds), 30)))
        return f"waited. Now on {self._where_am_i()}."

    # --- as tools ------------------------------------------------------------------------------------------------
    def tools(self) -> list[llm.Tool]:
        s, n, b = {"type": "string"}, {"type": "number"}, {"type": "boolean"}

        def spec(**props: Any) -> dict[str, Any]:
            return {"type": "object", "properties": props, "additionalProperties": False}

        def tool(name: str, text: str, schema: dict[str, Any], fn: Callable[..., Any]) -> llm.Tool:
            return llm.Tool(name, text, schema, fn)

        which = "by its number from `controls` (ref), by a CSS selector, or - for click - by a point of the picture (x, y)"
        return [
            tool("look", "A picture of what the window shows now. Use it whenever the text does not tell you what the page looks like.", spec(), self.look),
            tool("read", "The text of the page. `find`: only the lines around a word.", spec(max_chars=n, find=s), self.read),
            tool("controls", "Everything on the page that can be acted on - boxes, lists, buttons, links - each with its number, name, what it holds and whether it is required or marked invalid. "
                             "`filter`: only those whose line contains this text. `all`: also those not visible now.", spec(filter=s, all=b), self.controls),
            tool("click", f"Click a control: {which}.", spec(ref=s, selector=s, x=n, y=n, double=b), self.click),
            tool("type", "Put text in a box, replacing what it holds (ref or selector; without either: into what has the focus). `keys`: key by key, for a box that searches as one "
                         "types. `enter`: press Enter afterwards.", {**spec(text=s, ref=s, selector=s, keys=b, enter=b), "required": ["text"]}, self.type),
            tool("press", "Press keys on what has the focus: Enter, Tab, Escape, ArrowDown, Backspace, Control+A ... (several, separated by spaces, in order).", {**spec(keys=s), "required": ["keys"]}, self.press),
            tool("choose", "Choose an entry of a native list (shown by `controls` with options=[...]) by its text.", {**spec(option=s, ref=s, selector=s), "required": ["option"]}, self.choose),
            tool("upload", "Give one of the applicant's files (by the name you were told) to a file field, or to the button that opens the file window.",
                 {**spec(file=s, ref=s, selector=s), "required": ["file"]}, self.upload),
            tool("scroll", "Scroll the page by `down` pixels (negative: up), or bring the control `ref` into view.", spec(down=n, ref=s), self.scroll),
            tool("goto", "Open an address in the current tab.", {**spec(url=s), "required": ["url"]}, self.goto),
            tool("back", "Go back one page.", spec(), self.back),
            tool("tabs", "List the tabs of this window; `switch_to` or `close` one by its number.", spec(switch_to=n, close=n), self.tabs),
            tool("script", "Run JavaScript in the page and get its result. For what the other tools do not reach: reading something exactly, a control that does not answer to a click.",
                 {**spec(code=s), "required": ["code"]}, self.script),
            tool("wait", "Wait some seconds (a page that is loading, a list that is filling).", spec(seconds=n), self.wait),
        ]
