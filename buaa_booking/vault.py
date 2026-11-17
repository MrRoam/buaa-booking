from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(payload: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise RuntimeError("本地凭据库使用 Windows DPAPI，请在 Windows 运行登录命令")
    buffer = ctypes.create_string_buffer(payload)
    incoming = Blob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(incoming), "BUAA Booking", None, None, None, 1, ctypes.byref(outgoing))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel.LocalFree(outgoing.data)


class Vault:
    def __init__(self, directory: Path):
        self.path = directory / "credentials.dpapi"

    def read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(_crypt(self.path.read_bytes(), True).decode("utf-8"))

    def write(self, values: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = _crypt(json.dumps(values, ensure_ascii=False).encode("utf-8"), False)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(encrypted)
        os.replace(temporary, self.path)
