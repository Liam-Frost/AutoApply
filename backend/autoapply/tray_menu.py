"""The tray icon's menu on Windows, drawn to the design system (docs/DESIGN_SYSTEM.md) instead of the system's grey menu.

``render`` is a pure function: state in, picture and click regions out. It uses the same tokens as
``frontend/src/style.css`` (surface, border, text, primary, the soft status colours, 14px body text, 4px spacing grid,
6 / 10 / 14px radii) and the same components: a primary button, badges, a switch, line icons, hover on ``surface-2``.
``Popup`` shows that picture in a borderless window next to the tray icon and turns clicks into actions.

Other platforms keep their native menu (macOS and GNOME draw those well, and pystray needs the main thread there).
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from . import config

LIGHT = {"surface": "#ffffff", "surface2": "#f0f3f7", "border": "#e1e6ee", "border_strong": "#c9d1dd", "text": "#14233b", "text2": "#5a6b82", "text3": "#8b98ab",
         "primary": "#1f4fd8", "primary_hover": "#1a43ba", "on_primary": "#ffffff", "ok": "#17794a", "ok_soft": "#e2f4ea", "warn": "#9a5b00", "warn_soft": "#fff1d6",
         "bad": "#b3261e", "bad_soft": "#fde8e6", "info": "#1f4fd8", "info_soft": "#e8eeff", "neutral_soft": "#edf0f5", "logo_tile": None}
DARK = {"surface": "#151d29", "surface2": "#1c2634", "border": "#273244", "border_strong": "#3a475c", "text": "#e7ecf3", "text2": "#a3b0c2", "text3": "#75839a",
        "primary": "#6f9bff", "primary_hover": "#8aadff", "on_primary": "#0b1424", "ok": "#6fd3a0", "ok_soft": "#14301f", "warn": "#f0c36a", "warn_soft": "#3a2e12",
        "bad": "#f29b94", "bad_soft": "#3d1d1b", "info": "#9dbdff", "info_soft": "#1b2a4d", "neutral_soft": "#222c3b", "logo_tile": "#ffffff"}
W, PAD, ROW = 304, 12, 36           # logical pixels
SS = 3                              # drawn at 3x and scaled down, so curves and text are smooth
TONE = {"running": "ok", "attention": "warn", "paused": "neutral", "starting": "neutral", "stopped": "bad"}


def _font(size: float, bold: bool = False):  # noqa: ANN202
    from PIL import ImageFont

    names = (["msyhbd.ttc", "segoeuib.ttf"] if bold else ["msyh.ttc", "segoeui.ttf"]) + ["PingFang.ttc", "NotoSansCJK-Regular.ttc", "DejaVuSans.ttf"]
    for n in names:
        try:
            return ImageFont.truetype(n, int(round(size)), index=1 if n.startswith("msyh") else 0)
        except OSError:
            continue
    return ImageFont.load_default()


def _logo(px: int):  # noqa: ANN202
    from PIL import Image

    for p in (config.ROOT / "frontend" / "dist" / "favicon.png", config.ROOT / "frontend" / "public" / "favicon.png"):
        if p.exists():
            return Image.open(p).convert("RGBA").resize((px, px), Image.LANCZOS)
    from .launcher import make_icon

    return make_icon("plain").resize((px, px), Image.LANCZOS)


def _icon(d: Any, name: str, x: float, y: float, s: float, color: str) -> None:
    """A 16px line icon with its top-left corner at (x, y); ``s`` is the drawing scale."""
    w = max(1, int(round(1.6 * s)))
    P = lambda *pts: [(x + px * s, y + py * s) for px, py in pts]  # noqa: E731, N806
    line = lambda *pts: d.line(P(*pts), fill=color, width=w, joint="curve")  # noqa: E731
    box = lambda x0, y0, x1, y1: [x + x0 * s, y + y0 * s, x + x1 * s, y + y1 * s]  # noqa: E731
    if name == "pause":
        line((5.5, 3.5), (5.5, 12.5))
        line((10.5, 3.5), (10.5, 12.5))
    elif name == "play":
        d.polygon(P((5, 3), (13, 8), (5, 13)), outline=color, width=w)
    elif name == "restart":      # (the page's "refresh": a circle turning clockwise into a corner arrowhead at its top right)
        # (an arc's stroke lies inside its box: its middle runs at a radius of 4.7, and the ends and the arrowhead sit on it)
        d.arc(box(2.5, 2.5, 13.5, 13.5), start=0, end=315, fill=color, width=w)
        line((11.3, 4.7), (12.7, 6.0))
        line((12.7, 3.0), (12.7, 6.0), (9.9, 6.0))
        for px, py in ((12.7, 8), (12.7, 3.0), (12.7, 6.0), (9.9, 6.0)):      # round ends and corner, as the page's icons have
            d.ellipse([x + px * s - w / 2, y + py * s - w / 2, x + px * s + w / 2, y + py * s + w / 2], fill=color)
    elif name == "power":
        d.arc(box(2.5, 3.5, 13.5, 14.5), start=-55, end=235, fill=color, width=w)
        line((8, 1.8), (8, 7.5))
    elif name == "shortcut":
        d.rounded_rectangle(box(1.5, 2.5, 14.5, 11), radius=1.6 * s, outline=color, width=w)
        line((5.5, 14), (10.5, 14))
        line((8, 11), (8, 14))
    elif name == "key":
        d.ellipse(box(2, 6, 7.5, 11.5), outline=color, width=w)
        line((7.5, 8.75), (14, 8.75))
        line((11.5, 8.75), (11.5, 11.2))
    elif name == "log":
        d.rounded_rectangle(box(3, 1.5, 13, 14.5), radius=1.6 * s, outline=color, width=w)
        line((5.6, 5.5), (10.4, 5.5))
        line((5.6, 8.2), (10.4, 8.2))
        line((5.6, 10.9), (8.6, 10.9))
    elif name == "quit":
        line((6.5, 2.5), (3, 2.5), (3, 13.5), (6.5, 13.5))
        line((7, 8), (14, 8))
        line((11.2, 5.2), (14, 8), (11.2, 10.8))
    elif name == "todo":
        d.ellipse(box(1.8, 1.8, 14.2, 14.2), outline=color, width=w)
        line((8, 4.8), (8, 8.8))
        d.ellipse(box(7.1, 10.4, 8.9, 12.2), fill=color)
    elif name == "draft":
        d.rounded_rectangle(box(3, 1.5, 13, 14.5), radius=1.6 * s, outline=color, width=w)
        line((5.6, 8.2), (7.4, 10.2), (10.6, 6.2))
    elif name == "chevron":
        line((6, 4), (10, 8), (6, 12))


def rows(st: dict[str, Any]) -> list[dict[str, Any]]:
    """What the menu contains for this state, top to bottom."""
    t = st["t"]
    out: list[dict[str, Any]] = [{"kind": "header"}, {"kind": "primary", "key": "open", "label": t["open"], "enabled": st["up"]}]
    if st["needs"] or st["drafts"]:
        out.append({"kind": "gap"})
        if st["needs"]:
            out.append({"kind": "row", "key": "todos", "icon": "todo", "label": t["todo_row"], "badge": (str(st["needs"]), "bad"), "enabled": True})
        if st["drafts"]:
            out.append({"kind": "row", "key": "drafts", "icon": "draft", "label": t["draft_row"], "badge": (str(st["drafts"]), "info"), "enabled": True})
    out.append({"kind": "sep"})
    out.append({"kind": "row", "key": "pause", "icon": "play" if st["paused"] else "pause", "label": t["resume"] if st["paused"] else t["pause"], "enabled": st["up"]})
    out.append({"kind": "row", "key": "restart", "icon": "restart", "label": t["restart"] if st["up"] else t["start"], "enabled": st["can_restart"],
                "note": t["attached_short"] if st["attached"] and st["up"] else ""})
    out.append({"kind": "row", "key": "autostart", "icon": "power", "label": t["autostart"], "switch": bool(st["autostart"]), "enabled": True})
    out.append({"kind": "row", "key": "shortcut", "icon": "shortcut", "label": t["shortcut"], "enabled": True})
    out.append({"kind": "row", "key": "log", "icon": "log", "label": t["log"], "enabled": True})
    out.append({"kind": "row", "key": "reset_admin", "icon": "key", "label": t["reset_admin"], "enabled": True})
    out.append({"kind": "sep"})
    out.append({"kind": "row", "key": "quit", "icon": "quit", "label": t["quit_attached"] if st["attached"] else t["quit"], "enabled": True})
    return out


def render(st: dict[str, Any], *, hover: str = "", scale: float = 1.0, dark: bool = False):  # noqa: ANN201
    """-> (image, regions). ``regions`` is [(key, x0, y0, x1, y1)] in device pixels for the clickable rows."""
    from PIL import Image, ImageDraw

    c = DARK if dark else LIGHT
    k = SS * scale
    items = rows(st)
    heights = {"header": 60, "primary": 36 + 4, "gap": 6, "sep": 13, "row": ROW}
    H = PAD + sum(heights[i["kind"]] for i in items) + PAD - 4  # noqa: N806
    img = Image.new("RGB", (int(W * k), int(H * k)), c["surface"])
    d = ImageDraw.Draw(img)
    f14, f14b, f16b, f12, f12b = _font(14 * k), _font(14 * k, True), _font(16 * k, True), _font(12 * k), _font(12 * k, True)
    d.rectangle([0, 0, W * k - 1, H * k - 1], outline=c["border"], width=max(1, int(round(scale))) * SS)
    regions: list[tuple[str, int, int, int, int]] = []
    y = PAD

    def text(x: float, yy: float, s: str, font: Any, fill: str, anchor: str = "lm") -> None:
        d.text((x * k, yy * k), s, font=font, fill=fill, anchor=anchor)

    def badge(right: float, yy: float, label: str, tone: str) -> float:
        tw = d.textlength(label, font=f12b) / k
        bw, bh = tw + 18, 20
        bg, fg = (c["neutral_soft"], c["text2"]) if tone == "neutral" else (c[f"{tone}_soft"], c[tone])
        d.rounded_rectangle([(right - bw) * k, (yy - bh / 2) * k, right * k, (yy + bh / 2) * k], radius=bh / 2 * k, fill=bg)
        text(right - bw / 2, yy, label, f12b, fg, "mm")
        return right - bw

    for it in items:
        kind, h = it["kind"], heights[it["kind"]]
        if kind == "header":
            if c["logo_tile"]:  # the navy check of the mark is invisible on a dark surface: it sits on a white tile there
                d.rounded_rectangle([(PAD + 2) * k, (y + 4) * k, (PAD + 38) * k, (y + 40) * k], radius=8 * k, fill=c["logo_tile"])
            logo = _logo(int(28 * k))
            img.paste(logo, (int((PAD + 6) * k), int((y + 8) * k)), logo)
            text(PAD + 48, y + 13, "AutoApply", f16b, c["text"])
            text(PAD + 48, y + 33, st["line"], f12, c["text2"])
            badge(W - PAD - 2, y + 13, st["t"][f"state_{st['state']}"], TONE[st["state"]])
        elif kind == "primary":
            on = it["enabled"]
            bg = c["primary_hover"] if hover == it["key"] and on else c["primary"] if on else c["neutral_soft"]
            d.rounded_rectangle([PAD * k, y * k, (W - PAD) * k, (y + 36) * k], radius=6 * k, fill=bg)
            text(W / 2, y + 18, it["label"], f14b, c["on_primary"] if on else c["text3"], "mm")
            if on:
                regions.append((it["key"], int(PAD * k / SS), int(y * k / SS), int((W - PAD) * k / SS), int((y + 36) * k / SS)))
        elif kind == "sep":
            d.line([(PAD * k, (y + 6) * k), ((W - PAD) * k, (y + 6) * k)], fill=c["border"], width=max(1, int(round(scale))) * SS)
        elif kind == "row":
            on = it["enabled"]
            if hover == it["key"] and on:
                d.rounded_rectangle([(PAD - 4) * k, (y + 1) * k, (W - PAD + 4) * k, (y + h - 1) * k], radius=6 * k, fill=c["surface2"])
            ink = c["text"] if on else c["text3"]
            _icon(d, it["icon"], (PAD + 6) * k, (y + h / 2 - 8) * k, k, c["text2"] if on else c["text3"])
            text(PAD + 32, y + h / 2, it["label"], f14, ink)
            right = W - PAD - 6
            if "switch" in it:
                sw, sh = 34, 20
                x0, y0 = right - sw, y + h / 2 - sh / 2
                d.rounded_rectangle([x0 * k, y0 * k, (x0 + sw) * k, (y0 + sh) * k], radius=sh / 2 * k, fill=c["primary"] if it["switch"] else c["border_strong"])
                kx = x0 + sw - sh + 3 if it["switch"] else x0 + 3
                d.ellipse([kx * k, (y0 + 3) * k, (kx + sh - 6) * k, (y0 + sh - 3) * k], fill="#ffffff")
            elif it.get("badge"):
                right = badge(right - 18, y + h / 2, *it["badge"])
                _icon(d, "chevron", (W - PAD - 20) * k, (y + h / 2 - 8) * k, k, c["text3"])
            elif it.get("note"):
                text(right, y + h / 2, it["note"], f12, c["text3"], "rm")
            if on:
                regions.append((it["key"], int((PAD - 4) * k / SS), int(y * k / SS), int((W - PAD + 4) * k / SS), int((y + h) * k / SS)))
        y += h
    return img.resize((int(round(W * scale)), int(round(H * scale))), Image.LANCZOS), regions


def system_dark() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


class Popup:
    """The menu window. Lives in its own thread with its own Tk; ``show`` may be called from any thread."""

    def __init__(self, get_state: Callable[[], dict[str, Any]], on_action: Callable[[str], None]) -> None:
        self.get_state, self.on_action = get_state, on_action
        self.q: "queue.Queue[tuple[Any, ...]]" = queue.Queue()
        self.ready = threading.Event()
        self.done = threading.Event()
        self.error: str = ""
        self.hover, self.regions, self.state = "", [], {}
        threading.Thread(target=self._run, daemon=True, name="tray-menu").start()
        self.ready.wait(8)

    @property
    def ok(self) -> bool:
        return self.ready.is_set() and not self.error

    def show(self, x: int, y: int) -> None:
        self.q.put(("show", x, y))

    def close(self) -> None:
        """Stop the menu's thread and wait until it has let go of Tk (call before the program exits)."""
        if self.ok and not self.done.is_set():
            self.q.put(("quit",))
            self.done.wait(3)

    # --- everything below runs in the menu's own thread ---------------------------------------
    def _run(self) -> None:
        try:
            import tkinter as tk

            self.tk = tk
            self.root = tk.Tk()
            self.root.withdraw()
            self.win = tk.Toplevel(self.root)
            self.win.withdraw()
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.label = tk.Label(self.win, bd=0, highlightthickness=0, cursor="arrow")
            self.label.pack()
            self.label.bind("<Motion>", self._move)
            self.label.bind("<Leave>", lambda _e: self._set_hover(""))
            self.label.bind("<Button-1>", self._click)
            self.win.bind("<FocusOut>", lambda _e: self._hide())
            self.win.bind("<Escape>", lambda _e: self._hide())
            self.scale = self.root.winfo_fpixels("1i") / 96.0
            self.root.after(60, self._poll)
        except Exception as e:  # noqa: BLE001 - no Tk on this Python: the caller falls back to the system menu
            self.error = f"{type(e).__name__}: {e}"
            self.ready.set()
            return
        self.ready.set()
        self.root.mainloop()
        # Tk objects must be released by the thread that made them, or the interpreter aborts at exit
        self.photo = self.label = self.win = self.root = self.tk = None
        import gc

        gc.collect()
        self.done.set()

    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "show":
                    self._show(msg[1], msg[2])
                elif msg[0] == "quit":
                    self.root.quit()
                    return
        except queue.Empty:
            pass
        self.root.after(60, self._poll)

    def _paint(self) -> None:
        from PIL import ImageTk

        img, self.regions = render(self.state, hover=self.hover, scale=self.scale, dark=self.dark)
        self.photo = ImageTk.PhotoImage(img, master=self.win)
        self.label.configure(image=self.photo)
        self.size = img.size

    def _show(self, x: int, y: int) -> None:
        self.state, self.hover, self.dark = self.get_state(), "", system_dark()
        self._paint()
        w, h = self.size
        left, top, right, bottom = _work_area(x, y)
        px = min(max(left + 8, x - w + 16), right - w - 8)     # the menu's right edge near the pointer, kept on the screen
        py = y - h - 12 if y - h - 12 >= top + 8 else min(y + 12, bottom - h - 8)
        self.win.geometry(f"{w}x{h}+{int(px)}+{int(py)}")
        self.win.deiconify()
        self.win.lift()
        self.win.update_idletasks()
        _round_corners(self.win)
        self.win.focus_force()

    def _hide(self) -> None:
        self.win.withdraw()

    def _at(self, e: Any) -> str:
        return next((key for key, x0, y0, x1, y1 in self.regions if x0 <= e.x < x1 and y0 <= e.y < y1), "")

    def _set_hover(self, key: str) -> None:
        if key != self.hover:
            self.hover = key
            self.label.configure(cursor="hand2" if key else "arrow")
            self._paint()

    def _move(self, e: Any) -> None:
        self._set_hover(self._at(e))

    def _click(self, e: Any) -> None:
        key = self._at(e)
        if not key:
            return
        if key == "autostart":       # a switch: stay open and show the new position
            self.on_action(key)
            self.state = self.get_state()
            self._paint()
            return
        self._hide()
        threading.Thread(target=self.on_action, args=(key,), daemon=True, name="tray-action").start()


def _work_area(x: int, y: int) -> tuple[int, int, int, int]:
    """The usable rectangle (without the taskbar) of the monitor under a point."""
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):  # noqa: N801
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            mon = user32.MonitorFromPoint(wintypes.POINT(x, y), 2)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(wintypes.HANDLE(mon), ctypes.byref(mi)):
                r = mi.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:  # noqa: BLE001
            pass
    return 0, 0, 100000, 100000


def _round_corners(win: Any) -> None:
    """Rounded corners and the system's soft shadow (Windows 11); a clipped rounded rectangle on older versions."""
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)) != 0:
            w, h = win.winfo_width(), win.winfo_height()
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 20, 20)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
    except Exception:  # noqa: BLE001 - square corners are fine
        pass


def dpi_aware() -> None:
    """Ask Windows for real pixels, so the menu is sharp on scaled displays. Must run before any window exists."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001 - already set, or an old Windows
            pass


def demo_state(t: dict[str, str], **over: Any) -> dict[str, Any]:
    return {"t": t, "state": "attention", "line": t["working"].format(n=1), "up": True, "attached": False, "needs": 4, "drafts": 1, "paused": False,
            "autostart": True, "can_restart": True, **over}


if __name__ == "__main__":   # python -m autoapply.tray_menu out_dir  -> pictures of the menu in a few states, for review
    from .launcher import TEXT

    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    zh, en = TEXT["zh"], TEXT["en"]
    shots = {
        "light_attention": (demo_state(zh), {"hover": "pause"}),
        "dark_attention": (demo_state(zh), {"dark": True, "hover": "todos"}),
        "light_idle_attached": (demo_state(zh, state="running", line=zh["idle"], needs=0, drafts=0, attached=True, can_restart=False, autostart=False), {}),
        "light_stopped_en": (demo_state(en, state="stopped", line=en["stopped"], up=False, needs=0, drafts=0, autostart=False), {"hover": "restart"}),
    }
    for name, (st, kw) in shots.items():
        render(st, scale=2.0, **kw)[0].save(out / f"tray_{name}.png")
        print(out / f"tray_{name}.png")
