"""Windows shell pieces the launcher needs, called directly (no PowerShell, no extra package): the identity the
taskbar groups the program's windows and notifications under, and shortcut files that carry that identity.

The installer writes its shortcuts with the same APP_ID (scripts/package/windows/autoapply.iss), so the tray icon, a
pinned shortcut and the notifications are one program to Windows and not "pythonw.exe".
"""

from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import POINTER, byref, c_void_p, c_wchar_p, wintypes

APP_ID = "LiamFrost.AutoApply"

CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
IID_SHELL_LINK = "{000214F9-0000-0000-C000-000000000046}"
IID_PERSIST_FILE = "{0000010B-0000-0000-C000-000000000046}"
IID_PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
PKEY_APP_ID = ("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}", 5)
VT_LPWSTR = 31


class GUID(ctypes.Structure):
    _fields_ = [("d", ctypes.c_byte * 16)]

    def __init__(self, text: str):
        super().__init__()
        ctypes.memmove(self.d, uuid.UUID(text).bytes_le, 16)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort), ("p", c_void_p), ("pad", c_void_p)]


def set_app_id() -> None:
    """Tell Windows which program this process is. Without it the taskbar and notifications say pythonw.exe."""
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(c_wchar_p(APP_ID))


def _call(obj: c_void_p, index: int, *args, types: tuple = ()) -> None:
    """Call method number `index` of a COM object; a failure is an OSError with the system's message."""
    vtable = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *types)(vtable[index])
    hr = fn(obj, *args)
    if hr < 0:
        raise ctypes.WinError(hr)


def _query(obj: c_void_p, iid: str) -> c_void_p:
    out = c_void_p()
    _call(obj, 0, byref(GUID(iid)), byref(out), types=(POINTER(GUID), POINTER(c_void_p)))
    return out


def _release(obj: c_void_p) -> None:
    if obj:
        vtable = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
        ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtable[2])(obj)


def _link() -> c_void_p:
    ole = ctypes.windll.ole32
    ole.CoInitialize(None)
    link = c_void_p()
    hr = ole.CoCreateInstance(byref(GUID(CLSID_SHELL_LINK)), None, 1, byref(GUID(IID_SHELL_LINK)), byref(link))     # 1: in this process
    if hr < 0:
        raise ctypes.WinError(hr)
    return link


def make_shortcut(path: str, target: str, arguments: str = "", workdir: str = "", icon: str = "", description: str = "", app_id: str = APP_ID) -> None:
    """Write a .lnk file. IShellLinkW's methods by their position: 7 SetDescription, 9 SetWorkingDirectory,
    11 SetArguments, 17 SetIconLocation, 20 SetPath; IPropertyStore 6 SetValue, 7 Commit; IPersistFile 6 Save."""
    link = _link()
    store = files = c_void_p()
    try:
        _call(link, 20, target, types=(c_wchar_p,))
        _call(link, 11, arguments, types=(c_wchar_p,))
        if workdir:
            _call(link, 9, workdir, types=(c_wchar_p,))
        if description:
            _call(link, 7, description, types=(c_wchar_p,))
        if icon:
            _call(link, 17, icon, 0, types=(c_wchar_p, ctypes.c_int))
        if app_id:
            store = _query(link, IID_PROPERTY_STORE)
            key = PROPERTYKEY(GUID(PKEY_APP_ID[0]), PKEY_APP_ID[1])
            text = ctypes.create_unicode_buffer(app_id)          # ours: the store copies it, so it is not handed over to be freed
            value = PROPVARIANT(vt=VT_LPWSTR, p=ctypes.cast(text, c_void_p))
            _call(store, 6, byref(key), byref(value), types=(POINTER(PROPERTYKEY), POINTER(PROPVARIANT)))
            _call(store, 7)
        files = _query(link, IID_PERSIST_FILE)
        _call(files, 6, path, 1, types=(c_wchar_p, wintypes.BOOL))
    finally:
        for obj in (files, store, link):
            _release(obj)


def read_shortcut(path: str) -> dict:
    """What a .lnk file points at (used to check what make_shortcut wrote). IPersistFile 5 Load; IShellLinkW 3 GetPath,
    10 GetArguments, 8 GetWorkingDirectory; IPropertyStore 5 GetValue."""
    link = _link()
    store = files = c_void_p()
    try:
        files = _query(link, IID_PERSIST_FILE)
        _call(files, 5, path, 0, types=(c_wchar_p, wintypes.DWORD))
        buf = ctypes.create_unicode_buffer(1024)
        _call(link, 3, buf, 1024, None, 0, types=(c_wchar_p, ctypes.c_int, c_void_p, wintypes.DWORD))
        out = {"target": buf.value}
        _call(link, 10, buf, 1024, types=(c_wchar_p, ctypes.c_int))
        out["arguments"] = buf.value
        _call(link, 8, buf, 1024, types=(c_wchar_p, ctypes.c_int))
        out["workdir"] = buf.value
        store = _query(link, IID_PROPERTY_STORE)
        key, value = PROPERTYKEY(GUID(PKEY_APP_ID[0]), PKEY_APP_ID[1]), PROPVARIANT()
        _call(store, 5, byref(key), byref(value), types=(POINTER(PROPERTYKEY), POINTER(PROPVARIANT)))
        out["app_id"] = ctypes.wstring_at(value.p) if value.vt == VT_LPWSTR and value.p else ""
        ctypes.windll.ole32.PropVariantClear(byref(value))
        return out
    finally:
        for obj in (files, store, link):
            _release(obj)
