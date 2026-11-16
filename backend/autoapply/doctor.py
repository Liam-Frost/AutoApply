"""What this computer has and lacks for the program to do its whole job, with the command that fixes each lack.

On a desktop everything is usually there. On a server - no screen, no keyring, a bare system - several things the
program leans on are missing, and each used to show up only when it was needed: on the first application, on the
first PDF. This says it up front:

    autoapply doctor [--deep]          and the same list on the settings page

Each finding: id, level ("ok", "info", "warn", "bad"), title, detail, fix (a command, or ""). "bad" means some
part of the program cannot work; "warn" means it works with a limit that is named.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

from . import config

APT = "sudo apt-get install -y "


def has_screen() -> bool:
    """A display a window can be opened on: always on Windows and macOS, on Linux when a session is there."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _finding(id_: str, level: str, title: str, detail: str = "", fix: str = "") -> dict[str, str]:
    return {"id": id_, "level": level, "title": title, "detail": detail, "fix": fix}


def _secrets() -> dict[str, str]:
    from . import secrets

    d = secrets.describe()
    if d.get("problem"):
        return _finding("secrets", "bad", "保存的密码和密钥读不出来", d["detail"])
    if d["backend"] == "keyring":
        return _finding("secrets", "ok", "密码和密钥保存在系统的钥匙串里", d["detail"])
    if d.get("key") == "beside":
        return _finding("secrets", "warn", "密码和密钥保存在加密文件里，主密钥和数据放在同一个文件夹",
                        "这台电脑没有系统钥匙串。能以你的身份读这个文件夹的人，也就能读到这些密码。把主密钥放到别处更安全。",
                        "AUTOAPPLY_MASTER_KEY_FILE=/path/outside/the/data/folder")
    return _finding("secrets", "ok", "密码和密钥保存在加密文件里，主密钥在数据文件夹之外", d["detail"])


def _screen() -> dict[str, str]:
    if has_screen():
        return _finding("screen", "ok", "有图形桌面：需要你操作的窗口直接在这台电脑上打开")
    if shutil.which("Xvfb"):
        return _finding("screen", "ok", "没有图形桌面：需要你操作的窗口在网页里远程打开，拒绝隐藏窗口的网站用虚拟屏幕")
    return _finding("screen", "warn", "没有图形桌面，也没有虚拟屏幕",
                    "登录和需要你操作的步骤可以在网页里远程完成；但拒绝隐藏窗口的网站需要虚拟屏幕才能投递。", APT + "xvfb x11vnc")


def _browser(deep: bool) -> dict[str, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            if not path or not os.path.exists(path):
                return _finding("browser", "bad", "程序用的浏览器还没有下载", "", "uv run playwright install chromium")
            if deep:
                p.chromium.launch().close()
    except Exception as e:  # noqa: BLE001 - whatever stops the browser is the finding
        text = str(e)
        if sys.platform.startswith("linux") and ("shared libraries" in text or "missing dependencies" in text.lower()):
            return _finding("browser", "bad", "程序用的浏览器启动不了：系统缺少它需要的库", text.strip().splitlines()[0][:300],
                            f"sudo {config.ROOT / '.venv' / 'bin' / 'playwright'} install-deps chromium")
        return _finding("browser", "bad", "程序用的浏览器启动不了", text.strip().splitlines()[0][:300] if text.strip() else type(e).__name__)
    return _finding("browser", "ok", "程序用的浏览器可以启动" if deep else "程序用的浏览器已经下载")


def _converter() -> dict[str, str]:
    from . import convert

    if convert._has_word():
        return _finding("converter", "ok", "生成 PDF 用 Microsoft Word")
    if convert._soffice():
        return _finding("converter", "ok", "生成 PDF 用 LibreOffice")
    fix = APT + "libreoffice-writer" if sys.platform.startswith("linux") else "https://www.libreoffice.org/"
    return _finding("converter", "warn", "没有能把 Word 文档转成 PDF 的程序", "求职信、定制简历和 Word 预览需要它；没有的话这些功能不可用，其余照常。", fix)


def _fonts() -> dict[str, str] | None:
    if not sys.platform.startswith("linux"):
        return None
    if not shutil.which("fc-list"):
        return _finding("fonts", "info", "无法检查字体（没有 fc-list）")
    try:
        out = subprocess.run(["fc-list", ":lang=zh", "family"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return _finding("fonts", "info", "无法检查字体")
    if out:
        return _finding("fonts", "ok", "有中文字体")
    return _finding("fonts", "warn", "没有中文字体", "含中文的文档转成 PDF 后会是方框，截图里的中文也显示不出来。", APT + "fonts-noto-cjk")


def _disk() -> dict[str, str]:
    free = shutil.disk_usage(config.DATA if config.DATA.exists() else config.ROOT).free
    gb = free / 1e9
    if gb < 2:
        return _finding("disk", "warn", f"磁盘空间只剩 {gb:.1f} GB", "运行记录和截图会不断增加。")
    return _finding("disk", "ok", f"磁盘空间还有 {gb:.0f} GB")


def _service() -> dict[str, str] | None:
    if not sys.platform.startswith("linux"):
        return None
    from . import service

    st = service.status()
    if not st["systemd"]:
        return _finding("service", "info", "这里没有 systemd 用户服务（容器里通常如此）", "程序需要由别的东西保持运行：容器的重启策略，或你自己的进程管理器。")
    if st["active"]:
        return _finding("service", "ok", "作为服务运行：开机自动启动，出错自动重启" if st["linger"] else "作为服务运行，但只在你登录期间",
                        "" if st["linger"] else "没有打开“驻留”，注销后服务会停。", "" if st["linger"] else f"sudo loginctl enable-linger {st['user']}")
    if st["installed"]:
        return _finding("service", "warn", "服务已登记，但没有在运行", "", "autoapply service start")
    if has_screen():
        return None
    return _finding("service", "info", "没有登记成服务", "登记后开机自动启动，出错自动重启。", "autoapply service install")


def _access() -> dict[str, str] | None:
    from . import access

    c = access.conf()
    if not access.exposed(c):
        return None
    if c.get("https"):
        return _finding("access", "ok", "从其他设备访问，经由负责 HTTPS 的反向代理")
    return _finding("access", "warn", "从其他设备访问时没有加密", "登录密码，以及你在远程窗口里输入的密码，会以明文在网络上传输。请在前面放一个负责 HTTPS 的反向代理，并在“访问与安全”里打开对应的开关。")


def run(deep: bool = False) -> list[dict[str, str]]:
    """Every finding. `deep` also starts the browser once (a few seconds)."""
    checks: list[Any] = [_secrets, _screen, lambda: _browser(deep), _converter, _fonts, _disk, _service, _access]
    out = []
    for check in checks:
        try:
            f = check()
        except Exception as e:  # noqa: BLE001 - a check that breaks must not hide the others
            f = _finding(getattr(check, "__name__", "check").lstrip("_"), "info", "有一项检查没有做成", f"{type(e).__name__}: {e}")
        if f:
            out.append(f)
    return out
