"""Synchronous application interface backed exclusively by nodriver/CDP.

Each session owns a worker event loop. Browser objects never cross that loop.
"""

from __future__ import annotations

import asyncio
import logging
import base64
import concurrent.futures
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import TimeoutError

DOM = Path(__file__).with_name("nodriver_dom.js").read_text(encoding="utf-8")


@contextmanager
def profile_lock(profile):
    """OS locks release on crashes and protect profiles across server processes."""
    if profile is None:
        yield
        return
    import os

    profile.parent.mkdir(parents=True, exist_ok=True)
    with profile.with_suffix(".lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("This account's browser is already in use; retry when it closes") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def text_spec(value, exact=False):
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": "i" if value.flags & re.I else ""}
    return {"text": str(value), "exact": exact}


class Worker:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="nodriver", daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self.loop.close()

    def call(self, coroutine, timeout=120):
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError("nodriver operation timed out") from exc

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=10)


class Context:
    def __init__(self, worker, browser, state):
        self.worker, self.browser = worker, browser
        self.origins = {o["origin"]: o for o in (state or {}).get("origins", [])}
        self.scripts = []
        self.known = {}

    @property
    def pages(self):
        self.worker.call(self.browser.update_targets())
        pages = []
        for tab in self.browser.tabs:
            key = str(tab.target.target_id)
            if key not in self.known:
                self.known[key] = Page(self, tab)
            pages.append(self.known[key])
        return pages

    def cookies(self):
        cookies = self.worker.call(self.browser.cookies.get_all())
        return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                 "expires": float(c.expires), "httpOnly": c.http_only, "secure": c.secure,
                 "sameSite": c.same_site.value if c.same_site else "Lax"} for c in cookies]

    def add_cookies(self, cookies):
        from nodriver import cdp

        params = []
        for cookie in cookies:
            values = {k: cookie[k] for k in ("name", "value", "domain", "path", "url", "secure") if k in cookie}
            values["http_only"] = cookie.get("httpOnly", False)
            if cookie.get("expires", -1) > 0:
                values["expires"] = cdp.network.TimeSinceEpoch(cookie["expires"])
            if cookie.get("sameSite"):
                values["same_site"] = cdp.network.CookieSameSite(cookie["sameSite"])
            params.append(cdp.network.CookieParam(**values))
        if params:
            self.worker.call(self.browser.cookies.set_all(params))

    def storage_state(self):
        for page in self.pages:
            try:
                origin, items = page.evaluate("() => [location.origin, Object.entries(localStorage)]")
                if origin.startswith("http"):
                    self.origins[origin] = {"origin": origin, "localStorage": [{"name": k, "value": v} for k, v in items]}
            except Exception:
                continue
        return {"cookies": self.cookies(), "origins": list(self.origins.values())}

    def add_init_script(self, script):
        from nodriver import cdp

        self.scripts.append(script)
        for page in self.pages:
            page.send(cdp.page.add_script_to_evaluate_on_new_document(script))

    def expect_page(self, timeout=15000):
        context = self
        before = {p.tab.target.target_id for p in self.pages}

        class ExpectPage:
            def __enter__(self):
                return self

            def __exit__(self, kind, value, tb):
                if kind:
                    return
                until = time.monotonic() + timeout / 1000
                while time.monotonic() < until:
                    pages = [p for p in context.pages if p.tab.target.target_id not in before]
                    if pages:
                        self.value = pages[-1]
                        return
                    time.sleep(.1)
                raise TimeoutError("Timed out waiting for a new tab")

        return ExpectPage()


class Page:
    def __init__(self, context, tab):
        self.context, self.tab = context, tab
        self.keyboard = Keyboard(self)
        self.mouse = Mouse(self)
        self.timeout = 15000
        self.navigation_timeout = 75000

    def send(self, command):
        return self.context.worker.call(self.tab.send(command))

    def evaluate(self, expression, arg=None):
        from nodriver import cdp

        source = f"({expression})"
        # The application passes arrow functions, with occasional raw expressions.
        code = f"(() => {{ const value = {source}; return typeof value === 'function' ? value({json.dumps(arg)}) : value; }})()"
        result, error = self.send(cdp.runtime.evaluate(code, await_promise=True, return_by_value=True, user_gesture=True))
        if error:
            raise RuntimeError(error.exception.description if error.exception else error.text)
        return result.value

    @property
    def url(self):
        # Asked of the page; while it is between two addresses (a sign-in's redirects) it cannot answer, and the
        # browser's own record of the tab is used. A page that cannot be asked is not a window that was closed.
        try:
            return self.evaluate("location.href")
        except Exception:  # noqa: BLE001
            return str(getattr(self.tab.target, "url", "") or "")

    def goto(self, url, wait_until="load", timeout=None):
        from nodriver import cdp
        from types import SimpleNamespace

        if wait_until not in ("load", "domcontentloaded", "commit"):
            raise ValueError(f"Unsupported navigation wait {wait_until}")
        seconds = (timeout if timeout is not None else self.navigation_timeout) / 1000

        async def navigate():
            events, responses = [], []
            changed = asyncio.Event()

            def lifecycle(event):
                events.append(event)
                changed.set()

            def response(event):
                responses.append(event)

            self.tab.add_handler(cdp.page.LifecycleEvent, lifecycle)
            self.tab.add_handler(cdp.network.ResponseReceived, response)
            try:
                await self.tab.send(cdp.page.enable())
                await self.tab.send(cdp.page.set_lifecycle_events_enabled(True))
                await self.tab.send(cdp.network.enable())
                result = await self.tab.send(cdp.page.navigate(url))
                frame, loader, error = result[:3]
                if error:
                    raise RuntimeError(error)
                expected = "DOMContentLoaded" if wait_until == "domcontentloaded" else "load"
                if loader and wait_until != "commit":
                    while not any(e.loader_id == loader and e.name == expected for e in events):
                        changed.clear()
                        await changed.wait()
                document = [r for r in responses if r.loader_id == loader and r.type_ == cdp.network.ResourceType.DOCUMENT]
                return SimpleNamespace(status=int(document[-1].response.status)) if document else None
            finally:
                for event, callback in ((cdp.page.LifecycleEvent, lifecycle), (cdp.network.ResponseReceived, response)):
                    handlers = self.tab.handlers.get(event, [])
                    if callback in handlers:
                        handlers.remove(callback)

        return self.context.worker.call(navigate(), timeout=seconds)

    def wait_for_function(self, expression, arg=None, timeout=None):
        until = time.monotonic() + (timeout if timeout is not None else self.timeout) / 1000
        while True:
            try:
                if self.evaluate(expression, arg):
                    return
            except RuntimeError as exc:
                if "context" not in str(exc).lower():
                    raise
            if time.monotonic() >= until:
                raise TimeoutError("Timed out waiting for page condition")
            time.sleep(.1)

    def wait_for_load_state(self, state="load", timeout=None):
        if state not in ("load", "domcontentloaded"):
            raise ValueError(f"nodriver does not support load state {state}")
        condition = "document.readyState === 'complete'" if state == "load" else "document.readyState !== 'loading'"
        self.wait_for_function(condition, timeout=timeout or self.navigation_timeout)

    def wait_for_timeout(self, timeout):
        time.sleep(timeout / 1000)

    def wait_for_selector(self, selector, state="visible", timeout=None):
        return self.locator(selector).wait_for(state=state, timeout=timeout)

    def locator(self, selector, **kwargs):
        return Locator(self, [{"kind": "css", "selector": selector}]).filter(**kwargs)

    def get_by_role(self, role, name=None, exact=False, include_hidden=False):
        return Locator(self, [{"kind": "role", "role": role, "name": text_spec(name, exact) if name is not None else None, "include_hidden": include_hidden}])

    def get_by_label(self, text, exact=False):
        return Locator(self, [{"kind": "label", "text": text_spec(text, exact)}])

    def get_by_text(self, text, exact=False):
        return Locator(self, [{"kind": "text", "text": text_spec(text, exact)}])

    def inner_text(self, selector, **kwargs):
        return self.locator(selector).inner_text(**kwargs)

    def title(self):
        return self.evaluate("document.title")

    def content(self):
        return self.evaluate("document.documentElement.outerHTML")

    def is_closed(self):
        return self.tab.closed

    def close(self):
        self.context.worker.call(self.tab.close())

    def expect_file_chooser(self, timeout=15000):
        from nodriver import cdp

        page = self
        events = []

        def opened(event):
            events.append(event)

        class FileChooser:
            def set_files(self, files):
                paths = files if isinstance(files, list) else [files]
                page.send(cdp.dom.set_file_input_files([str(Path(p).resolve()) for p in paths], backend_node_id=events[0].backend_node_id))

        class ExpectFile:
            def __enter__(self):
                async def register():
                    page.tab.add_handler(cdp.page.FileChooserOpened, opened)
                page.context.worker.call(register())
                page.send(cdp.page.enable(enable_file_chooser_opened_event=True))
                page.send(cdp.page.set_intercept_file_chooser_dialog(True))
                return self

            def __exit__(self, kind, value, tb):
                try:
                    if kind:
                        return
                    until = time.monotonic() + timeout / 1000
                    while not events and time.monotonic() < until:
                        time.sleep(.1)
                    if not events:
                        raise TimeoutError("Timed out waiting for file chooser")
                    self.value = FileChooser()
                finally:
                    page.send(cdp.page.set_intercept_file_chooser_dialog(False))
                    async def unregister():
                        handlers = page.tab.handlers.get(cdp.page.FileChooserOpened, [])
                        if opened in handlers:
                            handlers.remove(opened)
                    page.context.worker.call(unregister())

        return ExpectFile()

    def screenshot(self, path=None, full_page=False, **kwargs):
        from nodriver import cdp

        clip = None
        if full_page:
            metrics = self.send(cdp.page.get_layout_metrics())
            size = metrics[-1]
            clip = cdp.page.Viewport(size.x, size.y, size.width, size.height, 1)
        data = self.send(cdp.page.capture_screenshot(format_="png", capture_beyond_viewport=full_page, clip=clip))
        raw = base64.b64decode(data)
        if path:
            Path(path).write_bytes(raw)
        return raw


class Locator:
    def __init__(self, page, steps):
        self.page, self.steps = page, steps

    def _next(self, step):
        return Locator(self.page, [*self.steps, step])

    def _evaluate(self, expression, arg=None, *, multiple=False):
        source = f"({DOM}).query({json.dumps(self.steps)})"
        target = "nodes" if multiple else "nodes[0]"
        guard = "" if multiple else "if (nodes.length !== 1) throw new Error('Expected one element, found ' + nodes.length);"
        return self.page.evaluate(f"() => {{ const nodes = {source}; {guard} return ({expression})({target}, {json.dumps(arg)}); }}")

    def evaluate(self, expression, arg=None):
        self.wait_for(state="attached")
        return self._evaluate(expression, arg)

    def evaluate_all(self, expression, arg=None):
        return self._evaluate(expression, arg, multiple=True)

    def locator(self, selector, **kwargs):
        return self._next({"kind": "css", "selector": selector}).filter(**kwargs)

    def get_by_role(self, role, **kwargs):
        child = self.page.get_by_role(role, **kwargs)
        return Locator(self.page, self.steps + child.steps)

    def filter(self, has_text=None, has=None):
        if has_text is None and has is None:
            return self
        return self._next({"kind": "filter", "text": text_spec(has_text) if has_text is not None else None, "has": has.steps if has else None})

    def or_(self, other):
        return self._next({"kind": "or", "steps": other.steps})

    def nth(self, index):
        return self._next({"kind": "nth", "index": index})

    @property
    def first(self):
        return self.nth(0)

    @property
    def last(self):
        return self.nth(-1)

    def count(self):
        return self.evaluate_all("nodes => nodes.length")

    def all(self):
        return [self.nth(i) for i in range(self.count())]

    def all_inner_texts(self):
        return self.evaluate_all("nodes => nodes.map(e => e.innerText)")

    def is_visible(self, **kwargs):
        return self.evaluate_all(f"nodes => nodes.length > 0 && ({DOM}).visible(nodes[0])")

    def is_enabled(self):
        return self.evaluate("e => !e.disabled && e.getAttribute('aria-disabled') !== 'true'")

    def is_checked(self):
        return self.evaluate("e => !!e.checked")

    def wait_for(self, state="visible", timeout=None):
        if state not in ("visible", "hidden", "attached", "detached"):
            raise ValueError(f"Unsupported element state {state}")
        until = time.monotonic() + (timeout if timeout is not None else self.page.timeout) / 1000
        while True:
            present = self.count() > 0
            ready = present if state == "attached" else not present if state == "detached" else self.is_visible() if state == "visible" else not self.is_visible()
            if ready:
                return self
            if time.monotonic() >= until:
                raise TimeoutError(f"Timed out waiting for element to be {state}")
            time.sleep(.1)

    def inner_text(self, **kwargs):
        return self.evaluate("e => e.innerText")

    def input_value(self, **kwargs):
        return self.evaluate("e => e.value")

    def get_attribute(self, name, **kwargs):
        return self.evaluate("(e, name) => e.getAttribute(name)", name)

    def focus(self, **kwargs):
        self.evaluate("e => e.focus()")

    def blur(self, **kwargs):
        self.evaluate("e => e.blur()")

    def scroll_into_view_if_needed(self, **kwargs):
        self.evaluate("e => e.scrollIntoView({block:'center', inline:'center'})")

    def click(self, timeout=None, force=False, **kwargs):
        self.wait_for(timeout=timeout)
        self.scroll_into_view_if_needed()
        point = self.evaluate("e => { const r=e.getBoundingClientRect(); return [r.x+r.width/2,r.y+r.height/2]; }")
        if not force and not self.is_enabled():
            raise RuntimeError("Element is disabled")
        if not force and not self.evaluate("(e,p) => {const hit=document.elementFromPoint(...p);return e===hit || e.contains(hit);}", point):
            raise RuntimeError("Element is covered by another element")
        self.page.mouse.click(*point)

    def fill(self, value, timeout=None):
        self.wait_for(timeout=timeout)
        self.focus()
        self.page.keyboard.press("ControlOrMeta+A")
        self.page.keyboard.press("Backspace")
        self.page.keyboard.type(str(value))

    def press(self, key, **kwargs):
        self.focus()
        self.page.keyboard.press(key)

    def press_sequentially(self, text, **kwargs):
        self.focus()
        self.page.keyboard.type(text, **kwargs)

    def set_checked(self, checked, **kwargs):
        if self.is_checked() != checked:
            self.click(**kwargs)
        if self.is_checked() != checked:
            raise RuntimeError("Checkbox did not reach requested state")

    def select_option(self, value=None, *, label=None, index=None, timeout=None, **kwargs):
        self.wait_for(state="attached", timeout=timeout)
        values = value if isinstance(value, list) else [value]
        labels = label if isinstance(label, list) else [label]
        indexes = [] if index is None else (index if isinstance(index, list) else [index])      # the drivers choose by position
        return self.evaluate("""(e, args) => {
          const [values, labels, indexes] = args;
          const chosen = [...e.options].filter((o, i) => values.includes(o.value) || labels.includes(o.label) || indexes.includes(i));
          if (!chosen.length) throw new Error('Select option not found');
          for (const o of e.options) o.selected = chosen.includes(o);
          e.dispatchEvent(new Event('input', {bubbles:true}));
          e.dispatchEvent(new Event('change', {bubbles:true}));
          return chosen.map(o => o.value);
        }""", [values, labels, indexes])

    def set_input_files(self, files, **kwargs):
        from nodriver import cdp

        self.wait_for(state="attached", timeout=kwargs.get("timeout"))
        expression = f"({DOM}).query({json.dumps(self.steps)})[0]"
        result, error = self.page.send(cdp.runtime.evaluate(expression))
        if error or not result.object_id:
            raise RuntimeError("File input could not be resolved")
        paths = files if isinstance(files, list) else [files]
        try:
            self.page.send(cdp.dom.set_file_input_files([str(Path(p).resolve()) for p in paths], object_id=result.object_id))
        finally:
            self.page.send(cdp.runtime.release_object(result.object_id))


class Keyboard:
    def __init__(self, page):
        self.page = page

    def type(self, text, delay=0):
        from nodriver import cdp

        for chunk in str(text) if delay else [str(text)]:
            self.page.send(cdp.input_.insert_text(chunk))
            if delay:
                time.sleep(delay / 1000)

    def press(self, key):
        from nodriver import cdp
        import sys

        parts = key.split("+")
        modifiers = 0
        for modifier in parts[:-1]:
            if modifier == "ControlOrMeta":
                modifier = "Meta" if sys.platform == "darwin" else "Control"
            modifiers |= {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}[modifier]
        key = parts[-1]
        code = {"Enter": 13, "Tab": 9, "Backspace": 8, "Escape": 27, "ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39, "Delete": 46, "Home": 36, "End": 35}.get(key, ord(key.upper()) if len(key) == 1 else 0)
        self.page.send(cdp.input_.dispatch_key_event("keyDown", key=key, windows_virtual_key_code=code, modifiers=modifiers, text="\r" if key == "Enter" else None))
        self.page.send(cdp.input_.dispatch_key_event("keyUp", key=key, windows_virtual_key_code=code, modifiers=modifiers))


class Mouse:
    def __init__(self, page):
        self.page = page

    def click(self, x, y):
        from nodriver import cdp

        self.page.send(cdp.input_.dispatch_mouse_event("mousePressed", x, y, button=cdp.input_.MouseButton.LEFT, click_count=1))
        self.page.send(cdp.input_.dispatch_mouse_event("mouseReleased", x, y, button=cdp.input_.MouseButton.LEFT, click_count=1))

    def wheel(self, x, y):
        from nodriver import cdp

        self.page.send(cdp.input_.dispatch_mouse_event("mouseWheel", 100, 100, delta_x=x, delta_y=y))


@contextmanager
def open_page(state, *, headless, executable, args, profile=None):
    import nodriver
    import tempfile

    worker = Worker()
    browser = None
    temporary = tempfile.TemporaryDirectory(prefix="autoapply-nodriver-") if profile is None else None
    profile = Path(temporary.name) if temporary else profile
    profile.mkdir(parents=True, exist_ok=True)
    try:
        async def create():
            return nodriver.Browser(nodriver.Config(headless=headless, browser_executable_path=executable, browser_args=args, user_data_dir=str(profile)))
        browser = worker.call(create())
        worker.call(browser.start())
        context = Context(worker, browser, state)
        context.add_cookies((state or {}).get("cookies", []))
        page = context.pages[0]
        origins = {o["origin"]: {x["name"]: x["value"] for x in o.get("localStorage", [])} for o in (state or {}).get("origins", [])}
        import uuid
        marker = "autoapply.restore." + uuid.uuid4().hex
        context.add_init_script(f"(() => {{ const data = {json.dumps(origins)}; if (!data[location.origin] || sessionStorage.getItem('{marker}')) return; for (const [k,v] of Object.entries(data[location.origin])) localStorage.setItem(k,v); sessionStorage.setItem('{marker}','1'); }})()")
        yield page
    finally:
        try:
            if browser:
                # Closing the window is housekeeping: it must never turn what happened in it into a failure. A Chrome
                # that takes its time to go (it is writing its profile) is waited for, then ended; either way the
                # caller gets its own result, not "TimeoutError" from here.
                async def stop():
                    process = browser._process
                    browser.stop()
                    if process:
                        try:
                            await asyncio.wait_for(process.wait(), timeout=10)
                        except (asyncio.TimeoutError, TimeoutError):
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                try:
                    worker.call(stop(), timeout=20)
                except Exception as e:  # noqa: BLE001
                    logging.getLogger("autoapply.nodriver").warning("the browser window did not close in order (%s)", type(e).__name__)
        finally:
            worker.close()
            if temporary:
                temporary.cleanup()
